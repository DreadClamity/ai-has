import json
import re
import time
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from langchain_google_genai.embeddings import GoogleGenerativeAIError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.core.rbac import get_current_user
from app.database import get_db
from app.rag.pipeline import answer_question
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    CitationOut,
    ConversationOut,
    FeedbackRequest,
    MessageOut,
    PendingAction,
    ToolResultOut,
)
from app.services.llm import LLMUnavailable
from app.guardrails.pii import redact_pii
from app.guardrails.ratelimit import chat_limiter
from app.services.messages import add_message
from app.tools.executor import (
    ToolOutcome,
    attach_message,
    confirm_tool_call,
    deny_tool_call,
    find_pending_tool_call,
    propose_tool_call,
)

router = APIRouter(prefix="/chat", tags=["Chat"])

YES = re.compile(
    r"^(yes|y|yep|yeah|sure|ok|okay|confirm|go ahead|please do|do it)[\s!.]*$", re.IGNORECASE
)
NO = re.compile(
    r"^(no|n|nope|cancel|stop|don't|do not|never mind|nevermind)[\s!.]*$", re.IGNORECASE
)


def _valid_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid id format")


def _get_owned_conversation(db: Session, conversation_id: str, user_id: str) -> dict:
    row = db.execute(
        text(
            """
            SELECT id::text AS id, status::text AS status
            FROM conversations
            WHERE id = CAST(:cid AS uuid) AND user_id = CAST(:uid AS uuid)
            """
        ),
        {"cid": _valid_uuid(conversation_id), "uid": user_id},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return dict(row)


def _inactive_detail(status: str) -> str:
    if status == "escalated":
        return "This conversation was escalated to a human IT agent, who will contact you here."
    return "This conversation is no longer active. Please start a new one."


def _result_out(outcome: ToolOutcome) -> ToolResultOut:
    return ToolResultOut(
        tool_call_id=outcome.tool_call_id,
        tool_name=outcome.tool_name,
        status=outcome.status,
    )


@router.post("/message", response_model=ChatResponse)
def send_message(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    started = time.perf_counter()
    original_text = payload.message.strip()
    if not original_text:
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    allowed, retry_after = chat_limiter.allow(user["id"])
    if not allowed:
        db.execute(
            text(
                """
                INSERT INTO guardrail_events (event_type, severity, details)
                VALUES ('rate_limited', 'medium', CAST(:details AS jsonb))
                """
            ),
            {"details": json.dumps({"user_id": user["id"], "retry_after": retry_after})},
        )
        db.commit()
        raise HTTPException(
            status_code=429,
            detail="You are sending messages too quickly. Please wait a moment and try again.",
            headers={"Retry-After": str(retry_after)},
        )

    redaction = redact_pii(original_text)
    message_text_in = redaction.text

    if payload.conversation_id:
        conversation = _get_owned_conversation(db, payload.conversation_id, user["id"])
        if conversation["status"] != "active":
            raise HTTPException(status_code=409, detail=_inactive_detail(conversation["status"]))
        conversation_id = conversation["id"]
    else:
        conversation_id = db.execute(
            text(
                "INSERT INTO conversations (user_id) VALUES (CAST(:uid AS uuid)) "
                "RETURNING id::text"
            ),
            {"uid": user["id"]},
        ).scalar_one()

    user_message_id = add_message(db, conversation_id, "user", message_text_in)
    if redaction.found:
        db.execute(
            text("UPDATE messages SET pii_detected = TRUE WHERE id = CAST(:mid AS uuid)"),
            {"mid": user_message_id},
        )
        db.execute(
            text(
                """
                INSERT INTO guardrail_events
                    (conversation_id, message_id, event_type, severity, details)
                VALUES (CAST(:cid AS uuid), CAST(:mid AS uuid), 'pii_redacted', 'low',
                        CAST(:details AS jsonb))
                """
            ),
            {
                "cid": conversation_id,
                "mid": user_message_id,
                "details": json.dumps(redaction.findings),
            },
        )
    db.commit()

    answer, intent = "", "general_howto"
    grounded, suggest_escalation = False, False
    citations, events = [], []
    prompt_tokens = completion_tokens = None
    tool_call_id = None
    pending_action = None
    action_result = None

    pending = find_pending_tool_call(db, conversation_id)

    if pending and YES.match(message_text_in):
        outcome = confirm_tool_call(db, user, pending["id"])
        answer, intent, tool_call_id = outcome.message, "tool_action", outcome.tool_call_id
        action_result = _result_out(outcome)

    elif pending and NO.match(message_text_in):
        outcome = deny_tool_call(db, user, pending["id"])
        answer, intent, tool_call_id = outcome.message, "tool_action", outcome.tool_call_id
        action_result = _result_out(outcome)

    else:
        history_rows = db.execute(
            text(
                """
                SELECT role::text AS role, content
                FROM messages
                WHERE conversation_id = CAST(:cid AS uuid)
                  AND id <> CAST(:mid AS uuid)
                  AND role IN ('user', 'assistant')
                ORDER BY created_at DESC
                LIMIT :n
                """
            ),
            {
                "cid": conversation_id,
                "mid": user_message_id,
                "n": settings.chat_history_messages,
            },
        ).mappings().all()
        history = [dict(r) for r in reversed(history_rows)]

        try:
            result = answer_question(message_text_in, history)
        except (LLMUnavailable, GoogleGenerativeAIError) as exc:
            invalid_key = any(
                marker in str(exc).lower()
                for marker in ("api_key_invalid", "api key not valid", "api key expired")
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    "The AI service rejected its API key. Please contact the administrator."
                    if invalid_key else
                    "The AI service is unavailable right now. Please try again in a moment or ask for a human agent."
                ),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        answer, intent = result.answer, result.intent
        grounded, suggest_escalation = result.grounded, result.suggest_escalation
        citations, events = result.citations, result.events
        prompt_tokens, completion_tokens = result.prompt_tokens, result.completion_tokens

        if result.tool_request:
            outcome = propose_tool_call(
                db,
                user,
                conversation_id,
                result.tool_request["name"],
                result.tool_request["args"],
                user_initiated=result.tool_request.get("user_initiated", False),
            )
            answer = outcome.message
            tool_call_id = outcome.tool_call_id
            suggest_escalation = False
            if outcome.status == "pending_confirmation":
                pending_action = PendingAction(
                    tool_call_id=outcome.tool_call_id,
                    tool_name=outcome.tool_name,
                    summary=outcome.message,
                )
            else:
                action_result = _result_out(outcome)

    latency_ms = int((time.perf_counter() - started) * 1000)
    assistant_message_id = add_message(
        db, conversation_id, "assistant", answer, intent,
        latency_ms, prompt_tokens, completion_tokens,
    )

    for citation in citations:
        db.execute(
            text(
                """
                INSERT INTO message_citations
                    (message_id, kb_document_id, chunk_id, relevance_score, snippet, source_details)
                VALUES
                    (CAST(:mid AS uuid),
                     (SELECT id FROM kb_documents WHERE id = CAST(:doc AS uuid)),
                     :chunk, :score, :snippet, CAST(:details AS jsonb))
                """
            ),
            {
                "mid": assistant_message_id,
                "doc": citation.doc_id,
                "chunk": citation.chunk_id,
                "score": citation.relevance,
                "snippet": citation.snippet,
                "details": json.dumps({
                    "index": citation.index,
                    "title": citation.title,
                    "section": citation.section,
                    "source_filename": citation.source_filename,
                }),
            },
        )

    for event in events:
        db.execute(
            text(
                """
                INSERT INTO guardrail_events
                    (conversation_id, message_id, event_type, severity, details)
                VALUES
                    (CAST(:cid AS uuid), CAST(:mid AS uuid), :etype, :sev,
                     CAST(:details AS jsonb))
                """
            ),
            {
                "cid": conversation_id,
                "mid": assistant_message_id,
                "etype": event["event_type"],
                "sev": event["severity"],
                "details": json.dumps(event["details"]),
            },
        )

    if tool_call_id:
        attach_message(db, tool_call_id, assistant_message_id)

    db.commit()

    conversation_status = db.execute(
        text("SELECT status::text FROM conversations WHERE id = CAST(:cid AS uuid)"),
        {"cid": conversation_id},
    ).scalar_one()

    return ChatResponse(
        conversation_id=conversation_id,
        message_id=assistant_message_id,
        answer=answer,
        intent=intent,
        grounded=grounded,
        suggest_escalation=suggest_escalation,
        citations=[
            CitationOut(
                index=c.index,
                chunk_id=c.chunk_id,
                title=c.title,
                section=c.section,
                source_filename=c.source_filename,
                relevance=c.relevance,
                snippet=c.snippet,
            )
            for c in citations
        ],
        latency_ms=latency_ms,
        conversation_status=conversation_status,
        pending_action=pending_action,
        action_result=action_result,
    )


@router.get("/conversations", response_model=List[ConversationOut])
def list_conversations(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    rows = db.execute(
        text(
            """
            SELECT c.id::text AS id, c.status::text AS status, c.started_at, c.resolved_at,
                   (
                       SELECT LEFT(regexp_replace(m.content, '[[:space:]]+', ' ', 'g'), 80)
                       FROM messages m
                       WHERE m.conversation_id = c.id AND m.role = 'user'
                       ORDER BY m.created_at, m.id
                       LIMIT 1
                   ) AS title
            FROM conversations c
            WHERE c.user_id = CAST(:uid AS uuid)
            ORDER BY c.started_at DESC, c.id
            LIMIT 50
            """
        ),
        {"uid": user["id"]},
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageOut])
def list_messages(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    conversation = _get_owned_conversation(db, conversation_id, user["id"])
    rows = db.execute(
        text(
            """
            SELECT m.id::text AS id, m.role::text AS role, m.content, m.intent, m.created_at,
                   f.rating,
                   (
                       SELECT jsonb_build_object('tool_call_id', t.id, 'tool_name', t.tool_name, 'summary', m.content)
                       FROM tool_calls t
                       WHERE t.message_id = m.id
                         AND t.conversation_id = m.conversation_id
                         AND t.requires_confirmation
                         AND t.status = 'pending_confirmation'
                         AND t.created_at > NOW() - (:minutes * INTERVAL '1 minute')
                       ORDER BY t.created_at DESC
                       LIMIT 1
                   ) AS pending,
                   COALESCE((
                       SELECT jsonb_agg(
                           jsonb_build_object(
                               'index', c.source_details->'index',
                               'chunk_id', COALESCE(c.chunk_id, c.id::text),
                               'title', COALESCE(c.source_details->>'title', d.title),
                               'section', c.source_details->>'section',
                               'source_filename', COALESCE(c.source_details->>'source_filename', d.source_filename),
                               'relevance', c.relevance_score,
                               'snippet', COALESCE(c.snippet, '')
                           ) ORDER BY (c.source_details->>'index')::int NULLS LAST, c.id
                       )
                       FROM message_citations c
                       LEFT JOIN kb_documents d ON d.id = c.kb_document_id
                       WHERE c.message_id = m.id
                   ), '[]'::jsonb) AS citations
            FROM messages m
            LEFT JOIN message_feedback f ON f.message_id = m.id AND f.user_id = CAST(:uid AS uuid)
            WHERE m.conversation_id = CAST(:cid AS uuid)
            ORDER BY m.created_at, m.id
            """
        ),
        {"cid": conversation["id"], "uid": user["id"], "minutes": settings.tool_confirm_minutes},
    ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/conversations/{conversation_id}/resolve")
def resolve_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    updated = db.execute(
        text(
            """
            UPDATE conversations
            SET status = 'resolved_by_ai', resolved_at = NOW()
            WHERE id = CAST(:cid AS uuid)
              AND user_id = CAST(:uid AS uuid)
              AND status = 'active'
            RETURNING id
            """
        ),
        {"cid": _valid_uuid(conversation_id), "uid": user["id"]},
    ).first()
    db.commit()
    if updated is None:
        raise HTTPException(status_code=404, detail="Active conversation not found")
    return {"status": "resolved_by_ai"}


@router.post("/feedback")
def submit_feedback(
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    owned = db.execute(
        text(
            """
            SELECT 1
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.id = CAST(:mid AS uuid)
              AND m.role = 'assistant'
              AND c.user_id = CAST(:uid AS uuid)
            """
        ),
        {"mid": _valid_uuid(payload.message_id), "uid": user["id"]},
    ).first()
    if owned is None:
        raise HTTPException(status_code=404, detail="Message not found")

    db.execute(
        text(
            """
            INSERT INTO message_feedback (message_id, user_id, rating, comment)
            VALUES (CAST(:mid AS uuid), CAST(:uid AS uuid), :rating, :comment)
            ON CONFLICT (message_id, user_id)
            DO UPDATE SET rating = EXCLUDED.rating, comment = EXCLUDED.comment
            """
        ),
        {
            "mid": payload.message_id,
            "uid": user["id"],
            "rating": payload.rating,
            "comment": payload.comment,
        },
    )
    db.commit()
    return {"status": "ok"}

import json
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.rbac import get_current_user, require_roles
from app.database import get_db
from app.schemas.agent import ResolveRequest, TextRequest, TicketDetailOut, TicketOut
from app.services.automation import emit_event
from app.guardrails.pii import redact_pii
from app.services.messages import add_message

router = APIRouter(prefix="/agent", tags=["Agent Dashboard"])
employee_router = APIRouter(prefix="/chat", tags=["Chat"])

agent_only = require_roles("agent", "admin")

TICKET_SELECT = """
    SELECT t.id::text AS id, t.ticket_key, t.external_ref, t.title, t.description,
           t.category, t.priority::text AS priority, t.status::text AS status,
           t.conversation_id::text AS conversation_id,
           t.assignee_id::text AS assignee_id, a.full_name AS assignee_name,
           r.full_name AS requester_name, r.email AS requester_email,
           t.created_at, t.updated_at, t.resolved_at
    FROM tickets t
    JOIN users r ON r.id = t.requester_id
    LEFT JOIN users a ON a.id = t.assignee_id
"""


def _valid_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid id format")


def _ticket_event(db: Session, ticket_id: str, actor_id: str, event_type: str, details: dict) -> None:
    db.execute(
        text(
            """
            INSERT INTO ticket_events (ticket_id, actor_id, event_type, details)
            VALUES (CAST(:tid AS uuid), CAST(:uid AS uuid), :etype, CAST(:details AS jsonb))
            """
        ),
        {"tid": ticket_id, "uid": actor_id, "etype": event_type, "details": json.dumps(details)},
    )


def _load_ticket_context(db: Session, ticket_id: str) -> dict:
    row = db.execute(
        text(
            """
            SELECT t.id::text AS id, t.ticket_key, t.status::text AS status,
                   t.assignee_id::text AS assignee_id,
                   t.conversation_id::text AS conversation_id,
                   c.status::text AS conversation_status
            FROM tickets t
            LEFT JOIN conversations c ON c.id = t.conversation_id
            WHERE t.id = CAST(:tid AS uuid)
            """
        ),
        {"tid": ticket_id},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return dict(row)


def _require_owner(ticket: dict, agent: dict) -> None:
    if ticket["assignee_id"] != agent["id"] and agent["role"] != "admin":
        raise HTTPException(status_code=403, detail="Claim this ticket first")


@router.get("/tickets", response_model=List[TicketOut])
def list_tickets(
    status: str = Query("", pattern="^(|open|in_progress|escalated|resolved|closed)$"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _agent: dict = Depends(agent_only),
):
    rows = db.execute(
        text(
            TICKET_SELECT
            + """
            WHERE (:status = '' OR t.status::text = :status)
            ORDER BY
                CASE t.status::text WHEN 'escalated' THEN 0 WHEN 'open' THEN 1
                     WHEN 'in_progress' THEN 2 ELSE 3 END,
                CASE t.priority::text WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                     WHEN 'medium' THEN 2 ELSE 3 END,
                t.created_at
            LIMIT :limit
            """
        ),
        {"status": status, "limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/tickets/{ticket_id}", response_model=TicketDetailOut)
def ticket_detail(
    ticket_id: str,
    db: Session = Depends(get_db),
    _agent: dict = Depends(agent_only),
):
    tid = _valid_uuid(ticket_id)
    ticket = db.execute(
        text(TICKET_SELECT + " WHERE t.id = CAST(:tid AS uuid)"), {"tid": tid}
    ).mappings().first()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    messages, conversation_status = [], None
    if ticket["conversation_id"]:
        messages = [
            dict(r)
            for r in db.execute(
                text(
                    """
                    SELECT id::text AS id, role::text AS role, content, intent, created_at
                    FROM messages
                    WHERE conversation_id = CAST(:cid AS uuid)
                    ORDER BY created_at
                    """
                ),
                {"cid": ticket["conversation_id"]},
            ).mappings().all()
        ]
        conversation_status = db.execute(
            text("SELECT status::text FROM conversations WHERE id = CAST(:cid AS uuid)"),
            {"cid": ticket["conversation_id"]},
        ).scalar_one_or_none()

    events = [
        dict(r)
        for r in db.execute(
            text(
                """
                SELECT event_type, details, created_at
                FROM ticket_events
                WHERE ticket_id = CAST(:tid AS uuid)
                ORDER BY created_at
                """
            ),
            {"tid": tid},
        ).mappings().all()
    ]

    return {
        "ticket": dict(ticket),
        "messages": messages,
        "events": events,
        "conversation_status": conversation_status,
    }


@router.post("/tickets/{ticket_id}/claim")
def claim_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    agent: dict = Depends(agent_only),
):
    tid = _valid_uuid(ticket_id)
    row = db.execute(
        text(
            """
            UPDATE tickets
            SET assignee_id = CAST(:uid AS uuid), status = 'in_progress', updated_at = NOW()
            WHERE id = CAST(:tid AS uuid)
              AND status IN ('open', 'escalated')
              AND assignee_id IS NULL
            RETURNING conversation_id::text AS conversation_id
            """
        ),
        {"uid": agent["id"], "tid": tid},
    ).mappings().first()
    if row is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ticket cannot be claimed (already assigned or closed)")

    if row["conversation_id"]:
        db.execute(
            text(
                "UPDATE conversations SET assigned_agent_id = CAST(:uid AS uuid) "
                "WHERE id = CAST(:cid AS uuid)"
            ),
            {"uid": agent["id"], "cid": row["conversation_id"]},
        )
    _ticket_event(db, tid, agent["id"], "claimed", {"agent": agent["email"]})
    db.commit()
    return {"status": "in_progress"}


@router.post("/tickets/{ticket_id}/reply")
def reply_to_employee(
    ticket_id: str,
    payload: TextRequest,
    db: Session = Depends(get_db),
    agent: dict = Depends(agent_only),
):
    ticket = _load_ticket_context(db, _valid_uuid(ticket_id))
    _require_owner(ticket, agent)
    if not ticket["conversation_id"] or ticket["conversation_status"] != "escalated":
        raise HTTPException(status_code=409, detail="This ticket has no live conversation")

    message_id = add_message(db, ticket["conversation_id"], "agent", payload.content.strip())
    db.execute(
        text("UPDATE tickets SET updated_at = NOW() WHERE id = CAST(:tid AS uuid)"),
        {"tid": ticket["id"]},
    )
    db.commit()
    return {"message_id": message_id}


@router.post("/tickets/{ticket_id}/resolve")
def resolve_ticket(
    ticket_id: str,
    payload: ResolveRequest,
    db: Session = Depends(get_db),
    agent: dict = Depends(agent_only),
):
    ticket = _load_ticket_context(db, _valid_uuid(ticket_id))
    _require_owner(ticket, agent)
    if ticket["status"] in ("resolved", "closed"):
        raise HTTPException(status_code=409, detail="Ticket is already resolved")

    db.execute(
        text(
            """
            UPDATE tickets
            SET status = 'resolved', resolved_at = NOW(), updated_at = NOW()
            WHERE id = CAST(:tid AS uuid)
            """
        ),
        {"tid": ticket["id"]},
    )
    note = payload.note.strip()
    if ticket["conversation_id"]:
        db.execute(
            text(
                """
                UPDATE conversations SET status = 'closed', resolved_at = NOW()
                WHERE id = CAST(:cid AS uuid) AND status = 'escalated'
                """
            ),
            {"cid": ticket["conversation_id"]},
        )
        closing = f"Your ticket {ticket['ticket_key']} has been resolved."
        add_message(
            db, ticket["conversation_id"], "agent", f"{closing} {note}".strip()
        )
    _ticket_event(db, ticket["id"], agent["id"], "resolved", {"note": note})
    db.commit()

    emit_event("ticket.resolved", {"ticket_key": ticket["ticket_key"], "resolved_by": agent["email"]})
    return {"status": "resolved"}


@employee_router.post("/conversations/{conversation_id}/agent-message")
def message_to_agent(
    conversation_id: str,
    payload: TextRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    row = db.execute(
        text(
            """
            SELECT id::text AS id, status::text AS status
            FROM conversations
            WHERE id = CAST(:cid AS uuid) AND user_id = CAST(:uid AS uuid)
            """
        ),
        {"cid": _valid_uuid(conversation_id), "uid": user["id"]},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if row["status"] != "escalated":
        raise HTTPException(status_code=409, detail="This conversation is not with a human agent")

    redaction = redact_pii(payload.content.strip())
    message_id = add_message(db, row["id"], "user", redaction.text)
    if redaction.found:
        db.execute(
            text("UPDATE messages SET pii_detected = TRUE WHERE id = CAST(:mid AS uuid)"),
            {"mid": message_id},
        )
    db.commit()
    return {"message_id": message_id}
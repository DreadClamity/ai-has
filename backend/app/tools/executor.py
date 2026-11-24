import json
import time
from dataclasses import dataclass
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.services.automation import emit_event
from app.tools.base import ToolContext, ToolDenied, ToolError, ToolNotFound
from app.tools.registry import TOOLS


@dataclass
class ToolOutcome:
    tool_call_id: str
    conversation_id: str
    tool_name: str
    status: str
    message: str


def _insert_call(db, conversation_id, tool_name, arguments, status, requires_confirmation, error=None) -> str:
    return db.execute(
        text(
            """
            INSERT INTO tool_calls
                (conversation_id, tool_name, arguments, status, requires_confirmation, error)
            VALUES
                (CAST(:cid AS uuid), :name, CAST(:args AS jsonb),
                 CAST(:status AS tool_status), :rc, :err)
            RETURNING id::text
            """
        ),
        {
            "cid": conversation_id,
            "name": tool_name[:80],
            "args": json.dumps(arguments, default=str),
            "status": status,
            "rc": requires_confirmation,
            "err": error,
        },
    ).scalar_one()


def _finish_call(db, tool_call_id, status, result, error, duration_ms) -> None:
    db.execute(
        text(
            """
            UPDATE tool_calls
            SET status = CAST(:status AS tool_status),
                result = CAST(:result AS jsonb),
                error = :err,
                duration_ms = :dur
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {
            "status": status,
            "result": json.dumps(result, default=str) if result is not None else None,
            "err": error,
            "dur": duration_ms,
            "id": tool_call_id,
        },
    )


def _log_guardrail(db, conversation_id, event_type, severity, details) -> None:
    db.execute(
        text(
            """
            INSERT INTO guardrail_events (conversation_id, event_type, severity, details)
            VALUES (CAST(:cid AS uuid), :etype, :sev, CAST(:details AS jsonb))
            """
        ),
        {
            "cid": conversation_id,
            "etype": event_type,
            "sev": severity,
            "details": json.dumps(details, default=str),
        },
    )


def _role_allowed(spec, user: dict) -> bool:
    return user["role"] in spec.allowed_roles


def _run(db: Session, user: dict, conversation_id: str, tool_call_id: str, spec, args) -> ToolOutcome:
    started = time.perf_counter()
    status, error, result_data, message, event = "success", None, None, "", None

    try:
        data = spec.handler(ToolContext(db=db, user=user, conversation_id=conversation_id), args)
        event = data.pop("_event", None)
        message = data.pop("message")
        result_data = data
    except ToolDenied as exc:
        db.rollback()
        status, error, message = "denied", str(exc), str(exc)
    except ToolError as exc:
        db.rollback()
        status, error, message = "failed", str(exc), str(exc)
    except Exception as exc:
        db.rollback()
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"[:500]
        message = (
            "Something went wrong while running that action. "
            "Please try again or ask for a human agent."
        )

    duration_ms = int((time.perf_counter() - started) * 1000)
    _finish_call(db, tool_call_id, status, result_data, error, duration_ms)
    db.commit()

    if event and status == "success":
        emit_event(event[0], event[1])

    return ToolOutcome(tool_call_id, conversation_id, spec.name, status, message)


def propose_tool_call(
    db: Session,
    user: dict,
    conversation_id: str,
    tool_name: str,
    raw_args: dict,
    user_initiated: bool = False,
) -> ToolOutcome:
    spec = TOOLS.get(tool_name)
    if spec is None:
        call_id = _insert_call(db, conversation_id, tool_name, raw_args, "denied", True, "unknown tool")
        _log_guardrail(db, conversation_id, "unknown_tool_requested", "medium", {"tool": tool_name})
        db.commit()
        return ToolOutcome(call_id, conversation_id, tool_name, "denied", "I can't perform that action.")

    if not _role_allowed(spec, user):
        call_id = _insert_call(
            db, conversation_id, tool_name, raw_args, "denied",
            spec.requires_confirmation, "role not allowed",
        )
        _log_guardrail(
            db, conversation_id, "unauthorized_tool", "medium",
            {"tool": tool_name, "role": user["role"]},
        )
        db.commit()
        return ToolOutcome(
            call_id, conversation_id, tool_name, "denied",
            "You don't have permission to use that action.",
        )

    try:
        args = spec.args_model(**dict(raw_args))
    except (ValidationError, TypeError) as exc:
        call_id = _insert_call(
            db, conversation_id, tool_name, raw_args, "failed",
            spec.requires_confirmation, str(exc)[:500],
        )
        db.commit()
        return ToolOutcome(
            call_id, conversation_id, tool_name, "failed",
            "I couldn't understand the details for that action. Could you rephrase it or give me a bit more information?",
        )

    if spec.requires_confirmation and not user_initiated:
        db.execute(
            text(
                """
                UPDATE tool_calls
                SET status = 'denied', error = 'superseded by a newer request'
                WHERE conversation_id = CAST(:cid AS uuid)
                  AND status = 'pending_confirmation'
                  AND requires_confirmation = TRUE
                """
            ),
            {"cid": conversation_id},
        )
        call_id = _insert_call(
            db, conversation_id, tool_name, args.model_dump(), "pending_confirmation", True
        )
        db.commit()
        return ToolOutcome(
            call_id, conversation_id, tool_name, "pending_confirmation",
            f'I can {spec.describe(args, user)}. Reply "yes" to confirm or "no" to cancel.',
        )

    call_id = _insert_call(
        db, conversation_id, tool_name, args.model_dump(), "pending_confirmation", False
    )
    db.commit()
    return _run(db, user, conversation_id, call_id, spec, args)


def _load_owned_call(db: Session, tool_call_id: str, user_id: str) -> dict:
    row = db.execute(
        text(
            """
            SELECT t.id::text AS id, t.conversation_id::text AS conversation_id,
                   t.tool_name, t.arguments, t.status::text AS status,
                   (t.created_at < NOW() - (:minutes * INTERVAL '1 minute')) AS expired
            FROM tool_calls t
            JOIN conversations c ON c.id = t.conversation_id
            WHERE t.id = CAST(:tid AS uuid) AND c.user_id = CAST(:uid AS uuid)
            """
        ),
        {"tid": tool_call_id, "uid": user_id, "minutes": settings.tool_confirm_minutes},
    ).mappings().first()
    if row is None:
        raise ToolNotFound(tool_call_id)
    return dict(row)


def confirm_tool_call(db: Session, user: dict, tool_call_id: str) -> ToolOutcome:
    call = _load_owned_call(db, tool_call_id, user["id"])
    name, conversation_id = call["tool_name"], call["conversation_id"]

    if call["status"] != "pending_confirmation":
        return ToolOutcome(
            call["id"], conversation_id, name, call["status"],
            "That request is no longer waiting for confirmation.",
        )

    if call["expired"]:
        _finish_call(db, call["id"], "denied", None, "confirmation expired", 0)
        db.commit()
        return ToolOutcome(
            call["id"], conversation_id, name, "denied",
            "That confirmation expired. Please ask me again if you still need it.",
        )

    spec = TOOLS.get(name)
    if spec is None or not _role_allowed(spec, user):
        _finish_call(db, call["id"], "denied", None, "role not allowed", 0)
        _log_guardrail(db, conversation_id, "unauthorized_tool", "medium", {"tool": name, "role": user["role"]})
        db.commit()
        return ToolOutcome(
            call["id"], conversation_id, name, "denied",
            "You don't have permission to use that action.",
        )

    try:
        args = spec.args_model(**call["arguments"])
    except (ValidationError, TypeError) as exc:
        _finish_call(db, call["id"], "failed", None, str(exc)[:500], 0)
        db.commit()
        return ToolOutcome(
            call["id"], conversation_id, name, "failed",
            "I couldn't process that request. Please try asking again.",
        )

    return _run(db, user, conversation_id, call["id"], spec, args)


def deny_tool_call(db: Session, user: dict, tool_call_id: str) -> ToolOutcome:
    call = _load_owned_call(db, tool_call_id, user["id"])
    if call["status"] == "pending_confirmation":
        _finish_call(db, call["id"], "denied", None, "cancelled by user", 0)
        db.commit()
    return ToolOutcome(
        call["id"], call["conversation_id"], call["tool_name"], "denied",
        "No problem, I've cancelled that.",
    )


def find_pending_tool_call(db: Session, conversation_id: str) -> Optional[dict]:
    row = db.execute(
        text(
            """
            SELECT id::text AS id
            FROM tool_calls
            WHERE conversation_id = CAST(:cid AS uuid)
              AND status = 'pending_confirmation'
              AND requires_confirmation = TRUE
              AND created_at > NOW() - (:minutes * INTERVAL '1 minute')
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"cid": conversation_id, "minutes": settings.tool_confirm_minutes},
    ).mappings().first()
    return dict(row) if row else None


def attach_message(db: Session, tool_call_id: str, message_id: str) -> None:
    db.execute(
        text(
            "UPDATE tool_calls SET message_id = CAST(:mid AS uuid) "
            "WHERE id = CAST(:tid AS uuid)"
        ),
        {"mid": message_id, "tid": tool_call_id},
    )
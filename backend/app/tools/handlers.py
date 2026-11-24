import json
from typing import Optional

from sqlalchemy import text

from app.config import settings
from app.services.automation import AutomationError, create_jira_issue, reset_ad_password
from app.tools.base import (
    CreateTicketArgs,
    EscalateArgs,
    ResetPasswordArgs,
    TicketStatusArgs,
    ToolContext,
    ToolDenied,
    ToolError,
)


def _insert_ticket(ctx: ToolContext, category, title, description, priority, status) -> dict:
    row = ctx.db.execute(
        text(
            """
            INSERT INTO tickets
                (conversation_id, requester_id, category, title, description, priority, status)
            VALUES
                (CAST(:cid AS uuid), CAST(:uid AS uuid), :category, :title, :description,
                 CAST(:priority AS ticket_priority), CAST(:status AS ticket_status))
            RETURNING id::text AS id, ticket_key
            """
        ),
        {
            "cid": ctx.conversation_id,
            "uid": ctx.user["id"],
            "category": category,
            "title": title,
            "description": description,
            "priority": priority,
            "status": status,
        },
    ).mappings().first()
    return dict(row)


def _log_ticket_event(ctx: ToolContext, ticket_id: str, event_type: str, details: dict) -> None:
    ctx.db.execute(
        text(
            """
            INSERT INTO ticket_events (ticket_id, actor_id, event_type, details)
            VALUES (CAST(:tid AS uuid), CAST(:uid AS uuid), :etype, CAST(:details AS jsonb))
            """
        ),
        {
            "tid": ticket_id,
            "uid": ctx.user["id"],
            "etype": event_type,
            "details": json.dumps(details),
        },
    )


def _sync_to_jira(ctx: ToolContext, ticket: dict, title: str, description: str, priority: str) -> Optional[str]:
    try:
        issue = create_jira_issue(
            summary=f"[{ticket['ticket_key']}] {title}",
            description=description,
            priority=priority,
            reporter_email=ctx.user["email"],
        )
    except AutomationError:
        return None
    ctx.db.execute(
        text("UPDATE tickets SET external_ref = :ref WHERE id = CAST(:id AS uuid)"),
        {"ref": issue.get("key"), "id": ticket["id"]},
    )
    return issue.get("key")


def reset_password(ctx: ToolContext, args: ResetPasswordArgs) -> dict:
    used = ctx.db.execute(
        text(
            """
            SELECT COUNT(*)
            FROM tool_calls t
            JOIN conversations c ON c.id = t.conversation_id
            WHERE c.user_id = CAST(:uid AS uuid)
              AND t.tool_name = 'reset_password'
              AND t.status = 'success'
              AND t.created_at > NOW() - INTERVAL '24 hours'
            """
        ),
        {"uid": ctx.user["id"]},
    ).scalar_one()
    if used >= settings.reset_limit_per_day:
        raise ToolDenied(
            "You have reached the daily limit for password resets. "
            "Please ask for a human IT agent if you still need help."
        )

    try:
        result = reset_ad_password(ctx.user["email"])
    except AutomationError as exc:
        raise ToolError(
            "I couldn't reach the account system right now. Please try again shortly "
            "or ask for a human agent."
        ) from exc

    reference = result.get("reference")
    return {
        "message": (
            "Done. A password reset link was sent to your registered address and stays "
            f"valid for {result.get('link_expires_minutes', 30)} minutes (reference {reference}). "
            "For your security I never show or ask for passwords in chat."
        ),
        "reference": reference,
        "_event": ("password.reset_requested", {"reference": reference, "user_id": ctx.user["id"]}),
    }


def create_ticket(ctx: ToolContext, args: CreateTicketArgs) -> dict:
    ticket = _insert_ticket(ctx, args.category, args.title, args.description, args.priority, "open")
    jira_key = _sync_to_jira(ctx, ticket, args.title, args.description, args.priority)
    _log_ticket_event(ctx, ticket["id"], "created", {"source": "ai_assistant", "jira": jira_key})

    jira_note = f" (Jira {jira_key})" if jira_key else " (Jira sync will be retried by IT)"
    return {
        "message": (
            f'Done. I created ticket {ticket["ticket_key"]}{jira_note}: "{args.title}". '
            "An IT agent will follow up."
        ),
        "ticket_key": ticket["ticket_key"],
        "external_ref": jira_key,
        "_event": (
            "ticket.created",
            {"ticket_key": ticket["ticket_key"], "jira": jira_key, "priority": args.priority},
        ),
    }


def escalate_to_agent(ctx: ToolContext, args: EscalateArgs) -> dict:
    current = ctx.db.execute(
        text("SELECT status::text FROM conversations WHERE id = CAST(:cid AS uuid)"),
        {"cid": ctx.conversation_id},
    ).scalar_one()
    if current != "active":
        raise ToolDenied("This conversation is already with a human agent.")

    rows = ctx.db.execute(
        text(
            """
            SELECT role::text AS role, content
            FROM messages
            WHERE conversation_id = CAST(:cid AS uuid)
            ORDER BY created_at DESC
            LIMIT 8
            """
        ),
        {"cid": ctx.conversation_id},
    ).mappings().all()
    transcript = "\n".join(f"{r['role']}: {r['content']}" for r in reversed(rows))

    title = f"Escalation: {args.reason[:120]}"
    description = f"Reason: {args.reason}\n\nRecent conversation:\n{transcript}"
    ticket = _insert_ticket(ctx, "escalation", title, description, "high", "escalated")

    ctx.db.execute(
        text(
            """
            UPDATE conversations
            SET status = 'escalated', escalation_reason = :reason
            WHERE id = CAST(:cid AS uuid)
            """
        ),
        {"reason": args.reason, "cid": ctx.conversation_id},
    )

    jira_key = _sync_to_jira(ctx, ticket, title, description, "high")
    _log_ticket_event(ctx, ticket["id"], "escalated", {"reason": args.reason, "jira": jira_key})

    return {
        "message": (
            f"I've escalated this to a human IT agent (ticket {ticket['ticket_key']}). "
            "They have the conversation history and will continue from here."
        ),
        "ticket_key": ticket["ticket_key"],
        "external_ref": jira_key,
        "_event": (
            "ticket.escalated",
            {"ticket_key": ticket["ticket_key"], "jira": jira_key, "reason": args.reason},
        ),
    }


def get_ticket_status(ctx: ToolContext, args: TicketStatusArgs) -> dict:
    key = args.ticket_key.strip().upper()
    if key:
        rows = ctx.db.execute(
            text(
                """
                SELECT ticket_key, external_ref, title, status::text AS status,
                       priority::text AS priority
                FROM tickets
                WHERE requester_id = CAST(:uid AS uuid)
                  AND (ticket_key = :key OR external_ref = :key)
                """
            ),
            {"uid": ctx.user["id"], "key": key},
        ).mappings().all()
        if not rows:
            return {"message": f"I couldn't find a ticket {key} under your account."}
    else:
        rows = ctx.db.execute(
            text(
                """
                SELECT ticket_key, external_ref, title, status::text AS status,
                       priority::text AS priority
                FROM tickets
                WHERE requester_id = CAST(:uid AS uuid)
                ORDER BY created_at DESC
                LIMIT 5
                """
            ),
            {"uid": ctx.user["id"]},
        ).mappings().all()
        if not rows:
            return {"message": "You don't have any tickets yet."}

    lines = [
        f"{r['ticket_key']} ({r['external_ref'] or 'no Jira key'}): {r['title']} - "
        f"status {r['status']}, priority {r['priority']}"
        for r in rows
    ]
    return {"message": "Here is what I found:\n" + "\n".join(lines)}
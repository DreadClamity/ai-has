from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.rbac import require_roles
from app.database import get_db

router = APIRouter(prefix="/metrics", tags=["Metrics"])

WINDOW = "NOW() - (:days * INTERVAL '1 day')"


@router.get("/dashboard")
def dashboard(
    days: int = Query(14, ge=1, le=90),
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_roles("admin")),
):
    params = {"days": days}

    conv = db.execute(
        text(
            f"""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE status = 'resolved_by_ai') AS resolved_by_ai,
                   COUNT(*) FILTER (WHERE status IN ('escalated', 'closed')) AS escalated
            FROM conversations
            WHERE started_at >= {WINDOW}
            """
        ),
        params,
    ).mappings().first()

    latency = db.execute(
        text(
            f"""
            SELECT ROUND(AVG(latency_ms)) AS avg_ms,
                   ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)::numeric) AS p95_ms
            FROM messages
            WHERE role = 'assistant' AND latency_ms IS NOT NULL AND created_at >= {WINDOW}
            """
        ),
        params,
    ).mappings().first()

    tickets = db.execute(
        text(
            f"""
            SELECT COUNT(*) FILTER (WHERE created_at >= {WINDOW}) AS opened,
                   COUNT(*) FILTER (WHERE resolved_at >= {WINDOW}) AS resolved,
                   COUNT(*) FILTER (WHERE status IN ('open', 'in_progress', 'escalated')) AS backlog,
                   ROUND((AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 60)
                          FILTER (WHERE resolved_at >= {WINDOW}))::numeric, 1) AS mttr_minutes
            FROM tickets
            """
        ),
        params,
    ).mappings().first()

    feedback = db.execute(
        text(
            f"""
            SELECT COUNT(*) FILTER (WHERE rating = 1) AS up,
                   COUNT(*) FILTER (WHERE rating = -1) AS down
            FROM message_feedback
            WHERE created_at >= {WINDOW}
            """
        ),
        params,
    ).mappings().first()

    total = conv["total"]
    summary = {
        "total_conversations": total,
        "resolved_by_ai": conv["resolved_by_ai"],
        "escalated": conv["escalated"],
        "no_outcome": total - conv["resolved_by_ai"] - conv["escalated"],
        "deflection_rate_pct": round(100.0 * conv["resolved_by_ai"] / total, 1) if total else None,
        "avg_latency_ms": latency["avg_ms"],
        "p95_latency_ms": latency["p95_ms"],
        "tickets_opened": tickets["opened"],
        "tickets_resolved": tickets["resolved"],
        "open_backlog": tickets["backlog"],
        "mttr_minutes": tickets["mttr_minutes"],
        "feedback_up": feedback["up"],
        "feedback_down": feedback["down"],
    }

    daily = db.execute(
        text(
            """
            SELECT d::date AS day,
                   COALESCE(k.total_conversations, 0) AS total_conversations,
                   COALESCE(k.resolved_by_ai, 0) AS resolved_by_ai,
                   COALESCE(k.escalated, 0) AS escalated,
                   k.deflection_rate_pct,
                   l.avg_latency_ms,
                   l.p95_latency_ms,
                   COALESCE(m.tickets_resolved, 0) AS tickets_resolved,
                   m.mttr_minutes
            FROM generate_series(
                     CURRENT_DATE - ((:days - 1) * INTERVAL '1 day'),
                     CURRENT_DATE,
                     INTERVAL '1 day') AS d
            LEFT JOIN v_kpi_deflection_daily k ON k.day = d::date
            LEFT JOIN v_kpi_latency_daily l ON l.day = d::date
            LEFT JOIN v_kpi_mttr_daily m ON m.day = d::date
            ORDER BY d
            """
        ),
        params,
    ).mappings().all()

    guardrails = db.execute(
        text(
            f"""
            SELECT event_type, severity, COUNT(*) AS count
            FROM guardrail_events
            WHERE created_at >= {WINDOW}
            GROUP BY event_type, severity
            ORDER BY count DESC
            """
        ),
        params,
    ).mappings().all()

    tools = db.execute(
        text(
            f"""
            SELECT tool_name, status::text AS status, COUNT(*) AS count,
                   ROUND(AVG(duration_ms)) AS avg_ms
            FROM tool_calls
            WHERE created_at >= {WINDOW}
            GROUP BY tool_name, status
            ORDER BY tool_name, status
            """
        ),
        params,
    ).mappings().all()

    intents = db.execute(
        text(
            f"""
            SELECT COALESCE(intent, 'unknown') AS intent, COUNT(*) AS count
            FROM messages
            WHERE role = 'assistant' AND created_at >= {WINDOW}
            GROUP BY 1
            ORDER BY count DESC
            """
        ),
        params,
    ).mappings().all()

    return {
        "days": days,
        "summary": summary,
        "daily": [dict(r) for r in daily],
        "guardrails": [dict(r) for r in guardrails],
        "tools": [dict(r) for r in tools],
        "intents": [dict(r) for r in intents],
    }
import hmac
import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


class JiraStatusEvent(BaseModel):
    issue_key: str = Field(..., min_length=3, max_length=40)
    status: Literal["open", "in_progress", "escalated", "resolved", "closed"]
    comment: Optional[str] = Field(default=None, max_length=500)


@router.post("/jira")
def jira_status_webhook(
    event: JiraStatusEvent,
    x_webhook_secret: str = Header(default=""),
    db: Session = Depends(get_db),
):
    if not settings.webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook receiver is not configured")
    if not hmac.compare_digest(x_webhook_secret.encode(), settings.webhook_secret.encode()):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    row = db.execute(
        text(
            """
            UPDATE tickets
            SET status = CAST(:status AS ticket_status),
                updated_at = NOW(),
                resolved_at = CASE
                    WHEN :status IN ('resolved', 'closed') THEN COALESCE(resolved_at, NOW())
                    ELSE NULL
                END
            WHERE external_ref = :key
            RETURNING id::text AS id
            """
        ),
        {"status": event.status, "key": event.issue_key},
    ).mappings().first()

    if row is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Unknown issue key")

    db.execute(
        text(
            """
            INSERT INTO ticket_events (ticket_id, event_type, details)
            VALUES (CAST(:tid AS uuid), 'jira_status_changed', CAST(:details AS jsonb))
            """
        ),
        {
            "tid": row["id"],
            "details": json.dumps({"status": event.status, "comment": event.comment}),
        },
    )
    db.commit()
    return {"updated": True, "ticket_id": row["id"]}
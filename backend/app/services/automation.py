import logging
from urllib.parse import quote

import httpx

from app.config import settings

logger = logging.getLogger("aihas.automation")

PRIORITY_NAMES = {"low": "Low", "medium": "Medium", "high": "High", "critical": "Highest"}


class AutomationError(Exception):
    pass


def _post(path: str, body: dict, timeout: float = 5.0) -> dict:
    try:
        response = httpx.post(f"{settings.mock_jira_url}{path}", json=body, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise AutomationError(str(exc)) from exc


def create_jira_issue(summary: str, description: str, priority: str, reporter_email: str) -> dict:
    return _post(
        "/rest/api/3/issue",
        {
            "fields": {
                "project": {"key": "AIHAS"},
                "summary": summary[:255],
                "description": description,
                "priority": {"name": PRIORITY_NAMES.get(priority, "Medium")},
                "reporter": {"emailAddress": reporter_email},
            }
        },
    )


def reset_ad_password(email: str) -> dict:
    return _post(f"/ad/users/{quote(email, safe='@')}/password-reset", {})


def emit_event(event_type: str, payload: dict) -> None:
    if not settings.n8n_webhook_url:
        return
    try:
        httpx.post(
            settings.n8n_webhook_url,
            json={"event": event_type, "data": payload},
            timeout=3.0,
        )
    except httpx.HTTPError as exc:
        logger.warning("Webhook delivery failed for %s: %s", event_type, exc)
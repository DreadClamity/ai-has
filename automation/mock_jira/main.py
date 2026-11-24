import uuid
from datetime import datetime, timezone
from itertools import count
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException

app = FastAPI(title="AI-HAS Mock Services (Jira + Active Directory + Webhook sink)")

_issue_numbers = count(101)
ISSUES: Dict[str, dict] = {}
RESETS: List[dict] = []
EVENTS: List[dict] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "issues": len(ISSUES),
        "resets": len(RESETS),
        "events": len(EVENTS),
    }


@app.post("/rest/api/3/issue", status_code=201)
def create_issue(payload: Dict[str, Any]):
    fields = payload.get("fields") or {}
    if not fields.get("summary"):
        raise HTTPException(status_code=400, detail="fields.summary is required")
    key = f"AIHAS-{next(_issue_numbers)}"
    ISSUES[key] = {"key": key, "fields": fields, "status": "To Do", "created": _now()}
    return {"id": key.split("-")[1], "key": key, "self": f"/rest/api/3/issue/{key}"}


@app.get("/rest/api/3/issue/{key}")
def get_issue(key: str):
    if key not in ISSUES:
        raise HTTPException(status_code=404, detail="Issue not found")
    return ISSUES[key]


@app.get("/rest/api/3/issues")
def list_issues():
    return list(ISSUES.values())


@app.post("/ad/users/{email}/password-reset")
def reset_password(email: str):
    if not email.lower().endswith("@aihas.local"):
        raise HTTPException(status_code=404, detail="User not found in directory")
    record = {
        "reference": f"AD-RESET-{uuid.uuid4().hex[:8].upper()}",
        "email": email.lower(),
        "requested_at": _now(),
        "link_expires_minutes": 30,
    }
    RESETS.append(record)
    return {"status": "reset_link_sent", **record}


@app.get("/ad/resets")
def list_resets():
    return RESETS


@app.post("/hooks/aihas")
def receive_event(payload: Dict[str, Any]):
    EVENTS.append({"received_at": _now(), "payload": payload})
    return {"received": True}


@app.get("/hooks/events")
def list_events():
    return EVENTS
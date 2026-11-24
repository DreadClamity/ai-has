import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.rbac import get_current_user
from app.database import get_db
from app.schemas.chat import EscalateRequest, ToolActionResponse
from app.services.messages import add_message
from app.tools.base import ToolNotFound
from app.tools.executor import ToolOutcome, confirm_tool_call, deny_tool_call, propose_tool_call

router = APIRouter(prefix="/chat", tags=["Actions"])


def _valid_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid id format")


def _respond(db: Session, outcome: ToolOutcome) -> ToolActionResponse:
    add_message(db, outcome.conversation_id, "assistant", outcome.message, "tool_action")
    db.commit()
    conversation_status = db.execute(
        text("SELECT status::text FROM conversations WHERE id = CAST(:cid AS uuid)"),
        {"cid": outcome.conversation_id},
    ).scalar_one()
    return ToolActionResponse(
        tool_call_id=outcome.tool_call_id,
        status=outcome.status,
        message=outcome.message,
        conversation_status=conversation_status,
    )


@router.post("/tool-calls/{tool_call_id}/confirm", response_model=ToolActionResponse)
def confirm_action(
    tool_call_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        outcome = confirm_tool_call(db, user, _valid_uuid(tool_call_id))
    except ToolNotFound:
        raise HTTPException(status_code=404, detail="Action not found")
    return _respond(db, outcome)


@router.post("/tool-calls/{tool_call_id}/deny", response_model=ToolActionResponse)
def deny_action(
    tool_call_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        outcome = deny_tool_call(db, user, _valid_uuid(tool_call_id))
    except ToolNotFound:
        raise HTTPException(status_code=404, detail="Action not found")
    return _respond(db, outcome)


@router.post("/conversations/{conversation_id}/escalate", response_model=ToolActionResponse)
def escalate_conversation(
    conversation_id: str,
    payload: Optional[EscalateRequest] = None,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    owned = db.execute(
        text(
            "SELECT id::text FROM conversations "
            "WHERE id = CAST(:cid AS uuid) AND user_id = CAST(:uid AS uuid)"
        ),
        {"cid": _valid_uuid(conversation_id), "uid": user["id"]},
    ).first()
    if owned is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    reason = payload.reason if payload else "User requested a human agent"
    outcome = propose_tool_call(
        db, user, owned[0], "escalate_to_agent", {"reason": reason}, user_initiated=True
    )
    return _respond(db, outcome)
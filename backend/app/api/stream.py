import json
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.chat import send_message
from app.core.rbac import get_current_user
from app.database import get_db
from app.schemas.chat import ChatRequest

router = APIRouter(prefix="/chat", tags=["Chat"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/message/stream")
def stream_message(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    response = send_message(payload, db, user)

    def generate():
        yield _sse("meta", {"conversation_id": response.conversation_id})
        words = response.answer.split(" ")
        for i, word in enumerate(words):
            suffix = " " if i < len(words) - 1 else ""
            yield _sse("token", {"text": word + suffix})
            time.sleep(0.015)
        yield _sse("done", response.model_dump(mode="json"))

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
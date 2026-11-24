from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


def add_message(
    db: Session,
    conversation_id: str,
    role: str,
    content: str,
    intent: Optional[str] = None,
    latency_ms: Optional[int] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
) -> str:
    return db.execute(
        text(
            """
            INSERT INTO messages
                (conversation_id, role, content, intent, latency_ms,
                 prompt_tokens, completion_tokens)
            VALUES
                (CAST(:cid AS uuid), CAST(:role AS message_role), :content,
                 :intent, :latency, :pt, :ct)
            RETURNING id::text
            """
        ),
        {
            "cid": conversation_id,
            "role": role,
            "content": content,
            "intent": intent,
            "latency": latency_ms,
            "pt": prompt_tokens,
            "ct": completion_tokens,
        },
    ).scalar_one()
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.chat import MessageOut


class TicketOut(BaseModel):
    id: str
    ticket_key: str
    external_ref: Optional[str] = None
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    priority: str
    status: str
    conversation_id: Optional[str] = None
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None
    requester_name: str
    requester_email: str
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None


class TicketEventOut(BaseModel):
    event_type: str
    details: dict
    created_at: datetime


class TicketDetailOut(BaseModel):
    ticket: TicketOut
    messages: List[MessageOut]
    events: List[TicketEventOut]
    conversation_status: Optional[str] = None


class TextRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


class ResolveRequest(BaseModel):
    note: str = Field(default="", max_length=500)
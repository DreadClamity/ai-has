from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[str] = None


class CitationOut(BaseModel):
    index: int
    chunk_id: str
    title: Optional[str] = None
    section: Optional[str] = None
    source_filename: Optional[str] = None
    relevance: Optional[float] = None
    snippet: str


class SavedCitationOut(CitationOut):
    index: Optional[int] = None


class PendingAction(BaseModel):
    tool_call_id: str
    tool_name: str
    summary: str


class ToolResultOut(BaseModel):
    tool_call_id: str
    tool_name: str
    status: str


class ChatResponse(BaseModel):
    conversation_id: str
    message_id: str
    answer: str
    intent: str
    grounded: bool
    suggest_escalation: bool
    citations: List[CitationOut]
    latency_ms: int
    conversation_status: str = "active"
    pending_action: Optional[PendingAction] = None
    action_result: Optional[ToolResultOut] = None


class EscalateRequest(BaseModel):
    reason: str = Field(default="User requested a human agent", min_length=3, max_length=500)


class ToolActionResponse(BaseModel):
    tool_call_id: str
    status: str
    message: str
    conversation_status: str


class FeedbackRequest(BaseModel):
    message_id: str
    rating: Literal[-1, 1]
    comment: Optional[str] = Field(default=None, max_length=500)


class ConversationOut(BaseModel):
    id: str
    status: str
    started_at: datetime
    resolved_at: Optional[datetime] = None
    title: Optional[str] = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    intent: Optional[str] = None
    created_at: datetime
    citations: List[SavedCitationOut] = Field(default_factory=list)
    rating: Optional[Literal[-1, 1]] = None
    pending: Optional[PendingAction] = None

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session


class ToolError(Exception):
    pass


class ToolDenied(Exception):
    pass


class ToolNotFound(Exception):
    pass


@dataclass
class ToolContext:
    db: Session
    user: dict
    conversation_id: str


CATEGORIES = ("account_access", "network", "software", "hardware", "other")
LLM_PRIORITIES = ("low", "medium", "high")


class ResetPasswordArgs(BaseModel):
    reason: str = Field(default="", max_length=300)


class CreateTicketArgs(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=5, max_length=2000)
    category: str = "other"
    priority: Literal["low", "medium", "high"] = "medium"

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        value = str(value or "").strip().lower()
        return value if value in CATEGORIES else "other"

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, value):
        value = str(value or "").strip().lower()
        return value if value in LLM_PRIORITIES else "medium"


class EscalateArgs(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class TicketStatusArgs(BaseModel):
    ticket_key: str = Field(default="", max_length=30)
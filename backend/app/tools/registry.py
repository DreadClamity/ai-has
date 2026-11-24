from dataclasses import dataclass
from typing import Callable, Tuple

from app.tools import handlers
from app.tools.base import (
    CreateTicketArgs,
    EscalateArgs,
    ResetPasswordArgs,
    TicketStatusArgs,
)

ALL_ROLES = ("employee", "agent", "admin")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    args_model: type
    handler: Callable
    requires_confirmation: bool
    allowed_roles: Tuple[str, ...]
    describe: Callable


_SPECS = [
    ToolSpec(
        name="reset_password",
        description=(
            "Reset the signed-in user's own password and send a reset link. "
            "Use only when the user asks to reset or unlock their account."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Short reason the user gave, for the audit log.",
                }
            },
            "required": ["reason"],
        },
        args_model=ResetPasswordArgs,
        handler=handlers.reset_password,
        requires_confirmation=True,
        allowed_roles=ALL_ROLES,
        describe=lambda args, user: (
            f"reset the password for your account ({user['email']}) and send you a reset link"
        ),
    ),
    ToolSpec(
        name="create_ticket",
        description="Create a support ticket for the signed-in user when IT follow-up is needed.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short clear title of the problem."},
                "description": {
                    "type": "string",
                    "description": "Details of the problem using only facts the user gave.",
                },
                "category": {
                    "type": "string",
                    "description": "One of: account_access, network, software, hardware, other.",
                },
                "priority": {
                    "type": "string",
                    "description": "One of: low, medium, high. Use medium unless the user says it blocks their work.",
                },
            },
            "required": ["title", "description", "category"],
        },
        args_model=CreateTicketArgs,
        handler=handlers.create_ticket,
        requires_confirmation=True,
        allowed_roles=ALL_ROLES,
        describe=lambda args, user: (
            f'create a {args.priority}-priority ticket titled "{args.title}"'
        ),
    ),
    ToolSpec(
        name="escalate_to_agent",
        description="Hand the conversation to a human IT agent and create an escalation ticket.",
        parameters={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why a human is needed."}
            },
            "required": ["reason"],
        },
        args_model=EscalateArgs,
        handler=handlers.escalate_to_agent,
        requires_confirmation=True,
        allowed_roles=ALL_ROLES,
        describe=lambda args, user: (
            f"escalate this conversation to a human IT agent (reason: {args.reason})"
        ),
    ),
    ToolSpec(
        name="get_ticket_status",
        description="Look up the status of the signed-in user's own tickets.",
        parameters={
            "type": "object",
            "properties": {
                "ticket_key": {
                    "type": "string",
                    "description": "Ticket number such as HD-0001. Leave empty to list recent tickets.",
                }
            },
        },
        args_model=TicketStatusArgs,
        handler=handlers.get_ticket_status,
        requires_confirmation=False,
        allowed_roles=ALL_ROLES,
        describe=lambda args, user: "look up your ticket status",
    ),
]

TOOLS = {spec.name: spec for spec in _SPECS}

TOOL_DECLARATIONS = [
    {"name": s.name, "description": s.description, "parameters": s.parameters}
    for s in _SPECS
]
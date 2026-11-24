import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.rag.hybrid import RetrievedChunk, hybrid_retrieve
from app.guardrails.injection import detect_injection
from app.guardrails.output_check import check_output
from app.rag.prompts import ALLOWED_INTENTS, SYSTEM_PROMPT, TOOL_RULES, USER_TEMPLATE
from app.services.llm import invoke_with_tools, message_text
from app.tools.registry import TOOL_DECLARATIONS, TOOLS

GREETING = re.compile(
    r"^(hi|hello|hey|good (morning|afternoon|evening))[\s!.]*$", re.IGNORECASE
)
THANKS = re.compile(r"^(thanks|thank you|thank u|ty)( so much| a lot)?[\s!.]*$", re.IGNORECASE)
HUMAN_REQUEST = re.compile(
    r"\b(human|real person|live agent|representative|"
    r"(speak|talk) to (an? )?(agent|person|someone))\b",
    re.IGNORECASE,
)
ACTION_HINT = re.compile(
    r"\b(ticket|incident|unlock|reset|escalat\w*|status|follow[- ]?up)\b", re.IGNORECASE
)

GREETING_REPLY = (
    "Hi! I'm the IT helpdesk assistant. Tell me what's going on, for example a "
    "password, VPN, Wi-Fi, printer, MFA or software request."
)
THANKS_REPLY = (
    "You're welcome! If your issue is solved you can mark the conversation as "
    "resolved, or tell me what else you need."
)
FALLBACK_REPLY = (
    "I couldn't find a reliable answer to that in our IT knowledge base, so I "
    "don't want to guess. A human IT agent can help you with this."
)

INJECTION_REPLY = (
    "I can't help with that request. I can only help with IT support questions such "
    "as passwords, VPN, Wi-Fi, printers, MFA and software access."
)

TOOL_INTENTS = {
    "reset_password": "password_reset",
    "create_ticket": "ticket_request",
    "escalate_to_agent": "human_request",
    "get_ticket_status": "ticket_status",
}


@dataclass
class Citation:
    index: int
    chunk_id: str
    doc_id: Optional[str]
    title: Optional[str]
    section: Optional[str]
    source_filename: Optional[str]
    relevance: Optional[float]
    snippet: str


@dataclass
class PipelineResult:
    answer: str
    intent: str
    grounded: bool
    suggest_escalation: bool
    citations: List[Citation] = field(default_factory=list)
    top_vector: float = 0.0
    keyword_hit: bool = False
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    events: List[dict] = field(default_factory=list)
    tool_request: Optional[dict] = None


def parse_llm_json(raw: str) -> Optional[dict]:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def build_messages(question: str, history: List[Dict[str, str]], chunks: List[RetrievedChunk]):
    if chunks:
        context = "\n\n".join(
            f"[{i}] ({c.title} > {c.section})\n{c.text}" for i, c in enumerate(chunks, start=1)
        )
    else:
        context = "(no relevant knowledge base content was found for this question)"

    messages = [SystemMessage(content=SYSTEM_PROMPT + "\n\n" + TOOL_RULES)]
    for turn in history:
        if turn["role"] == "user":
            messages.append(HumanMessage(content=turn["content"]))
        elif turn["role"] == "assistant":
            messages.append(AIMessage(content=turn["content"]))
    messages.append(
        HumanMessage(content=USER_TEMPLATE.format(context=context, question=question))
    )
    return messages


def _snippet(text: str, limit: int = 300) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def _refusal(reason: str, intent: str, top_vector: float, keyword_hit: bool, extra=None) -> PipelineResult:
    details = {"reason": reason, "top_vector": top_vector, "keyword_hit": keyword_hit}
    if extra:
        details.update(extra)
    return PipelineResult(
        answer=FALLBACK_REPLY,
        intent=intent,
        grounded=False,
        suggest_escalation=True,
        top_vector=top_vector,
        keyword_hit=keyword_hit,
        events=[{"event_type": reason, "severity": "low", "details": details}],
    )


def answer_question(question: str, history: List[Dict[str, str]]) -> PipelineResult:
    text_in = question.strip()

    injection = detect_injection(text_in)
    if injection.blocked:
        return PipelineResult(
            INJECTION_REPLY,
            "blocked_injection",
            False,
            False,
            events=[
                {
                    "event_type": "injection_blocked",
                    "severity": "high",
                    "details": {"score": injection.score, "matches": injection.matches},
                }
            ],
        )

    if GREETING.match(text_in):
        return PipelineResult(GREETING_REPLY, "smalltalk", False, False)
    if THANKS.match(text_in):
        return PipelineResult(THANKS_REPLY, "smalltalk", False, False)
    if HUMAN_REQUEST.search(text_in):
        return PipelineResult(
            "",
            "human_request",
            False,
            False,
            tool_request={
                "name": "escalate_to_agent",
                "args": {"reason": "User asked to speak with a human agent"},
                "user_initiated": True,
            },
        )

    retrieval = hybrid_retrieve(text_in)
    if not retrieval.confident and not ACTION_HINT.search(text_in):
        return _refusal(
            "refused_low_confidence",
            "out_of_scope",
            retrieval.top_vector,
            retrieval.keyword_hit,
        )

    chunks = retrieval.chunks if retrieval.confident else []
    response = invoke_with_tools(build_messages(text_in, history, chunks), TOOL_DECLARATIONS)
    usage = getattr(response, "usage_metadata", None) or {}
    prompt_tokens = usage.get("input_tokens")
    completion_tokens = usage.get("output_tokens")

    def finish(result: PipelineResult) -> PipelineResult:
        result.prompt_tokens, result.completion_tokens = prompt_tokens, completion_tokens
        return result

    tool_calls = getattr(response, "tool_calls", None) or []
    if tool_calls:
        call = tool_calls[0]
        name = call.get("name")
        if name in TOOLS:
            return finish(
                PipelineResult(
                    answer="",
                    intent=TOOL_INTENTS.get(name, "general_howto"),
                    grounded=False,
                    suggest_escalation=False,
                    top_vector=retrieval.top_vector,
                    keyword_hit=retrieval.keyword_hit,
                    tool_request={"name": name, "args": dict(call.get("args") or {})},
                )
            )
        return finish(
            _refusal(
                "unknown_tool_requested",
                "out_of_scope",
                retrieval.top_vector,
                retrieval.keyword_hit,
                extra={"tool": name},
            )
        )

    data = parse_llm_json(message_text(response.content))
    if data is None:
        return finish(
            _refusal(
                "llm_output_invalid",
                "out_of_scope",
                retrieval.top_vector,
                retrieval.keyword_hit,
            )
        )

    intent = data.get("intent") if data.get("intent") in ALLOWED_INTENTS else "general_howto"
    answer = str(data.get("answer") or "").strip()
    answerable = bool(data.get("answerable"))
    needs_human = bool(data.get("needs_human"))

    if bool(data.get("clarify")) and answer and "?" in answer:
        return finish(
            PipelineResult(
                answer,
                intent,
                False,
                False,
                top_vector=retrieval.top_vector,
                keyword_hit=retrieval.keyword_hit,
            )
        )

    cited_numbers: List[int] = []
    for n in data.get("sources_used") or []:
        if isinstance(n, int) and 1 <= n <= len(chunks) and n not in cited_numbers:
            cited_numbers.append(n)

    if not answerable or not answer:
        return finish(
            _refusal(
                "refused_llm_not_answerable",
                intent if intent != "general_howto" else "out_of_scope",
                retrieval.top_vector,
                retrieval.keyword_hit,
            )
        )

    if not cited_numbers:
        result = _refusal(
            "ungrounded_answer",
            intent,
            retrieval.top_vector,
            retrieval.keyword_hit,
            extra={"discarded_answer_preview": answer[:200]},
        )
        result.events[0]["severity"] = "medium"
        return finish(result)

    verdict = check_output(answer, [c.text for c in chunks])
    if not verdict.ok:
        result = _refusal(
            "output_blocked",
            intent,
            retrieval.top_vector,
            retrieval.keyword_hit,
            extra={"issues": verdict.issues},
        )
        result.events[0]["severity"] = "high" if "prompt_leak" in verdict.issues else "medium"
        return finish(result)
    answer = verdict.answer

    citations = []
    for n in cited_numbers:
        chunk = chunks[n - 1]
        citations.append(
            Citation(
                index=n,
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                title=chunk.title,
                section=chunk.section,
                source_filename=chunk.source_filename,
                relevance=chunk.vector_relevance,
                snippet=_snippet(chunk.text),
            )
        )

    return finish(
        PipelineResult(
            answer=answer,
            intent=intent,
            grounded=True,
            suggest_escalation=needs_human,
            citations=citations,
            top_vector=retrieval.top_vector,
            keyword_hit=retrieval.keyword_hit,
        )
    )
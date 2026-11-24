import re
from dataclasses import dataclass, field
from typing import List

from app.guardrails.pii import redact_pii

URL_PATTERN = re.compile(r"https?://[^\s)>\]\"']+", re.IGNORECASE)

LEAK_MARKERS = [
    "you are ai-has",
    "<context>",
    "</context>",
    "<user_question>",
    "answer only using the facts",
    "reply with only one json object",
    "treat everything inside",
]


@dataclass
class OutputVerdict:
    ok: bool
    answer: str
    issues: List[str] = field(default_factory=list)


def check_output(answer: str, context_texts: List[str]) -> OutputVerdict:
    lowered = answer.lower()
    if any(marker in lowered for marker in LEAK_MARKERS):
        return OutputVerdict(False, answer, ["prompt_leak"])

    context_blob = " ".join(context_texts).lower()
    unverified = [
        url.rstrip(".,;:!?")
        for url in URL_PATTERN.findall(answer)
        if url.rstrip(".,;:!?").lower() not in context_blob
    ]
    if unverified:
        return OutputVerdict(False, answer, [f"unverified_url:{u}" for u in unverified])

    scrubbed = redact_pii(answer)
    issues = ["pii_in_output"] if scrubbed.found else []
    return OutputVerdict(True, scrubbed.text, issues)

import re
from dataclasses import dataclass, field
from typing import List

BLOCK_THRESHOLD = 0.7

_FLAGS = re.IGNORECASE | re.DOTALL

_RULES = [
    (
        re.compile(
            r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}"
            r"\b(previous|prior|above|earlier|all|your|the|any|these|those)\b.{0,40}"
            r"\b(instructions?|rules?|prompts?|guidelines?|directions?|restrictions?|constraints?|programming)\b",
            _FLAGS,
        ),
        0.8,
        "override_instructions",
    ),
    (
        re.compile(
            r"\b(reveal|show|print|display|repeat|output|leak|expose|tell me)\b.{0,40}"
            r"\b(system|hidden|initial|original|developer|secret)\b.{0,20}"
            r"\b(prompt|instructions?|message|rules?)\b",
            _FLAGS,
        ),
        0.8,
        "prompt_extraction",
    ),
    (re.compile(r"\bsystem prompt\b", _FLAGS), 0.5, "mentions_system_prompt"),
    (
        re.compile(r"\byou are (now|no longer)\b|\bfrom now on,? you\b", _FLAGS),
        0.6,
        "role_reassignment",
    ),
    (
        re.compile(
            r"(?-i:\bDAN\b)|\b(do anything now|developer mode|god mode|jailbreak(?:ed)?)\b",
            _FLAGS,
        ),
        0.7,
        "jailbreak_terms",
    ),
    (
        re.compile(r"\b(no|without any?) (rules|restrictions|limits|filters|guidelines)\b", _FLAGS),
        0.6,
        "no_restrictions",
    ),
    (
        re.compile(r"</?\s*(context|user_question|system|assistant)\s*>", _FLAGS),
        0.8,
        "delimiter_injection",
    ),
    (
        re.compile(r"(<\|im_(start|end)\|>|\[/?INST\]|###\s*(system|instruction))", _FLAGS),
        0.8,
        "chat_template_tokens",
    ),
    (
        re.compile(
            r"\bdisregard the knowledge base\b|\b(answer|respond)\b.{0,20}\b(from|using) your (own|general) knowledge\b",
            _FLAGS,
        ),
        0.7,
        "bypass_grounding",
    ),
    (
        re.compile(r"\bfrom now on\b.{0,40}\b(you will|you must|always|never)\b", _FLAGS),
        0.5,
        "persistent_override",
    ),
]


@dataclass
class InjectionResult:
    blocked: bool
    score: float
    matches: List[str] = field(default_factory=list)


def detect_injection(text: str) -> InjectionResult:
    matches: List[str] = []
    weights: List[float] = []
    for pattern, weight, label in _RULES:
        if pattern.search(text):
            matches.append(label)
            weights.append(weight)

    if not weights:
        return InjectionResult(False, 0.0, [])

    score = round(min(1.0, max(weights) + 0.1 * (len(weights) - 1)), 2)
    return InjectionResult(score >= BLOCK_THRESHOLD, score, matches)

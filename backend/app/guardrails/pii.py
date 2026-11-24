import re
from dataclasses import dataclass, field
from typing import Dict

API_KEY = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"
)
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
SECRET_STATEMENT = re.compile(
    r"(?i)\b(password|passcode|passwd|pwd|pin|otp|mfa code|verification code|one[- ]time code)\b"
    r"(\s*(?:is|was|=|:)\s*)(\S+)"
)
CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
US_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
PH_SSS = re.compile(r"(?<!\d)\d{2}-\d{7}-\d(?!\d)")
PH_TIN = re.compile(r"(?<!\d)\d{3}-\d{3}-\d{3}(?:-\d{3,5})?(?!\d)")
PH_MOBILE = re.compile(r"(?<!\d)(?:\+?63[\s-]?|0)9\d{2}[\s-]?\d{3}[\s-]?\d{4}(?!\d)")
INTL_PHONE = re.compile(r"(?<!\w)\+\d{1,3}[\s-]?\(?\d{2,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}(?!\d)")
US_PHONE = re.compile(r"(?<!\d)\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
EMPLOYEE_ID = re.compile(r"\bEMP[-\s]?\d{3,8}\b", re.IGNORECASE)


@dataclass
class RedactionResult:
    text: str
    findings: Dict[str, int] = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return bool(self.findings)


def luhn_valid(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def redact_pii(text: str) -> RedactionResult:
    findings: Dict[str, int] = {}

    def bump(label: str) -> None:
        findings[label] = findings.get(label, 0) + 1

    def simple(pattern: re.Pattern, label: str, value: str) -> str:
        def repl(_match):
            bump(label)
            return f"[{label}]"

        return pattern.sub(repl, value)

    def secret_repl(match):
        value = match.group(3).strip(".,;!?\"'")
        if len(value) >= 4 and re.search(r"[\d\W_]", value):
            bump("SECRET")
            return f"{match.group(1)}{match.group(2)}[SECRET]"
        return match.group(0)

    def card_repl(match):
        if luhn_valid(match.group(0)):
            bump("CARD")
            return "[CARD]"
        return match.group(0)

    result = simple(API_KEY, "API_KEY", text)
    result = simple(EMAIL, "EMAIL", result)
    result = SECRET_STATEMENT.sub(secret_repl, result)
    result = CARD_CANDIDATE.sub(card_repl, result)
    result = simple(US_SSN, "ID_NUMBER", result)
    result = simple(PH_SSS, "ID_NUMBER", result)
    result = simple(PH_TIN, "ID_NUMBER", result)
    result = simple(PH_MOBILE, "PHONE", result)
    result = simple(INTL_PHONE, "PHONE", result)
    result = simple(US_PHONE, "PHONE", result)
    result = simple(EMPLOYEE_ID, "EMPLOYEE_ID", result)

    return RedactionResult(text=result, findings=findings)

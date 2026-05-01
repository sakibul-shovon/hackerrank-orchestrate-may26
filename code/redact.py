import re

PATTERNS = [
    (re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"), "[REDACTED_CARD]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                    "[REDACTED_SSN]"),
    (re.compile(r"(?i)\b(?:cvv|cvc)\s*[:#]?\s*\d{3,4}\b"),    "[REDACTED_CVV]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{20,}"),          "[REDACTED_TOKEN]"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"),                       "[REDACTED_KEY]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
]

def redact(text: str) -> str:
    if not text:
        return text
    for p, repl in PATTERNS:
        text = p.sub(repl, text)
    return text

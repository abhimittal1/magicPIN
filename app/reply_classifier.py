from __future__ import annotations

import re
from dataclasses import dataclass


AUTO_REPLY_PATTERNS = [
    r"thank you for contacting",
    r"our team will respond",
    r"automated assistant",
    r"auto(?:mated)? reply",
    r"we will get back to you",
]
STOP_PATTERNS = [
    r"not interested", r"stop messaging", r"unsubscribe", r"do not message", r"leave me alone",
    # Hindi / Hinglish opt-out
    r"opt.?out", r"mat bhejo", r"message mat", r"band karo", r"nahi chahiye",
    r"\bhatao\b", r"rok do", r"remove kar", r"mujhe mat",
]
ABUSIVE_PATTERNS = [r"spam", r"idiot", r"stupid", r"useless"]
BUSY_PATTERNS = [
    r"\bbusy\b",
    r"ping me later",
    r"message me later",
    r"call me later",
    r"follow.?up later",
    r"not now",
    r"later\b",
    r"baad mein",
    r"abhi nahi",
    r"after some time",
    r"message me tomorrow",
    r"talk later",
]


@dataclass(frozen=True)
class ReplyClassification:
    kind: str
    confidence: float


class ReplyClassifier:
    """Deterministic fast-path for only the highest-confidence terminal replies."""

    def classify(self, message: str) -> ReplyClassification:
        text = message.strip().lower()
        if self._matches(ABUSIVE_PATTERNS, text):
            return ReplyClassification(kind="abusive", confidence=0.95)
        if self._matches(STOP_PATTERNS, text):
            return ReplyClassification(kind="explicit_no_or_stop", confidence=0.98)
        if self._matches(AUTO_REPLY_PATTERNS, text):
            return ReplyClassification(kind="auto_reply", confidence=0.95)
        if self._matches(BUSY_PATTERNS, text):
            return ReplyClassification(kind="busy_wait", confidence=0.90)
        return ReplyClassification(kind="ambiguous", confidence=0.0)

    def _matches(self, patterns: list[str], text: str) -> bool:
        return any(re.search(pattern, text) for pattern in patterns)
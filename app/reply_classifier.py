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
BUSY_PATTERNS = [r"busy", r"later", r"tomorrow", r"after some time", r"call later"]
COMMIT_PATTERNS = [r"\byes\b", r"go ahead", r"let's do it", r"lets do it", r"send it", r"proceed", r"share it", r"what's next", r"whats next"]
OFF_TOPIC_PATTERNS = [r"gst", r"tax", r"ca\b", r"payroll", r"rent agreement"]
ABUSIVE_PATTERNS = [r"spam", r"idiot", r"stupid", r"useless"]


@dataclass(frozen=True)
class ReplyClassification:
    kind: str
    confidence: float


class ReplyClassifier:
    def classify(self, message: str) -> ReplyClassification:
        text = message.strip().lower()
        if self._matches(ABUSIVE_PATTERNS, text):
            return ReplyClassification(kind="abusive", confidence=0.95)
        if self._matches(STOP_PATTERNS, text):
            return ReplyClassification(kind="explicit_no_or_stop", confidence=0.98)
        if self._matches(AUTO_REPLY_PATTERNS, text):
            return ReplyClassification(kind="auto_reply", confidence=0.95)
        if self._matches(BUSY_PATTERNS, text):
            return ReplyClassification(kind="later_busy", confidence=0.8)
        if self._matches(OFF_TOPIC_PATTERNS, text):
            return ReplyClassification(kind="off_topic", confidence=0.75)
        if self._matches(COMMIT_PATTERNS, text):
            return ReplyClassification(kind="explicit_yes_or_commit", confidence=0.9)
        _hindi_q = any(text.startswith(w) for w in ("kaun", "kya", "kaise", "kyun", "kab", "kitna", "kaunsa", "kahan"))
        if "?" in text or text.startswith(("what", "how", "when", "can", "why", "who")) or _hindi_q:
            return ReplyClassification(kind="question", confidence=0.7)
        return ReplyClassification(kind="ambiguous", confidence=0.4)

    def _matches(self, patterns: list[str], text: str) -> bool:
        return any(re.search(pattern, text) for pattern in patterns)
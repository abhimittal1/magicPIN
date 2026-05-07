from __future__ import annotations

import re
from dataclasses import dataclass


SIGNAL_REGISTRY: list[tuple[str, float, list[str]]] = [
    ("abusive", 0.95, [
        r"spam", r"idiot", r"stupid", r"useless",
    ]),
    ("explicit_no_or_stop", 0.98, [
        r"not interested", r"stop messaging", r"unsubscribe", r"do not message", r"leave me alone",
        r"opt.?out", r"mat bhejo", r"message mat", r"band karo", r"nahi chahiye",
        r"\bhatao\b", r"rok do", r"remove kar", r"mujhe mat",
    ]),
    ("auto_reply", 0.95, [
        r"thank you for contacting",
        r"our team will respond",
        r"automated assistant",
        r"auto(?:mated)? reply",
        r"we will get back to you",
    ]),
    ("busy_wait", 0.90, [
        r"\bbusy\b", r"ping me later", r"message me later", r"call me later",
        r"follow.?up later", r"not now", r"later\b", r"baad mein",
        r"abhi nahi", r"after some time", r"message me tomorrow", r"talk later",
    ]),
]


@dataclass(frozen=True)
class InboundSignal:
    kind: str
    confidence: float


class IntentRouter:
    """Deterministic fast-path for only the highest-confidence terminal replies."""

    def route(self, message: str) -> InboundSignal:
        text = message.strip().lower()
        for kind, confidence, patterns in SIGNAL_REGISTRY:
            if any(re.search(p, text) for p in patterns):
                return InboundSignal(kind=kind, confidence=confidence)
        return InboundSignal(kind="ambiguous", confidence=0.0)
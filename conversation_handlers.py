from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.reply_classifier import ReplyClassifier


@dataclass
class ConversationState:
    conversation_id: str
    merchant_id: str | None = None
    customer_id: str | None = None
    trigger_id: str | None = None
    turns: list[dict[str, Any]] = field(default_factory=list)


def respond(state: ConversationState, merchant_message: str) -> dict:
    classifier = ReplyClassifier()
    classification = classifier.classify(merchant_message)
    if classification.kind in {"explicit_no_or_stop", "abusive"}:
        return {"action": "end", "rationale": "The conversation ended on an explicit stop or hostile message."}
    if classification.kind == "auto_reply":
        return {
            "action": "wait",
            "wait_seconds": get_settings().default_auto_reply_wait_seconds,
            "rationale": "An auto-reply was detected, so the bot is waiting before trying again.",
        }
    if classification.kind == "explicit_yes_or_commit":
        return {
            "action": "send",
            "body": "Great. I am switching into action mode and will keep the next step concrete.",
            "cta": "binary_yes_no",
            "rationale": "The merchant committed, so the handler moves forward instead of re-qualifying.",
        }
    return {
        "action": "send",
        "body": "Understood. I can keep this simple and move one step at a time. Reply YES if you want me to continue.",
        "cta": "binary_yes_no",
        "rationale": "The signal is unclear, so the handler asks for a light confirmation.",
    }
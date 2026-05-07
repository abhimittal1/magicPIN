from __future__ import annotations

from app.composer import OutreachEngine
from app.config import get_settings
from app.evidence import FactPicker
from app.llm_client import LLMWriter
from app.planner import StrategyEngine
from app.validator import OutputGuard


_compose_service = OutreachEngine(
    planner=StrategyEngine(),
    evidence_selector=FactPicker(),
    wording_service=LLMWriter(get_settings()),
    validator=OutputGuard(),
)


def compose(category: dict, merchant: dict, trigger: dict, customer: dict | None = None) -> dict:
    composed = _compose_service.draft_from_raw(
        category=category,
        merchant=merchant,
        trigger=trigger,
        customer=customer,
    )
    return {
        "body": composed.body,
        "cta": composed.cta,
        "send_as": composed.send_as,
        "suppression_key": composed.suppression_key,
        "rationale": composed.rationale,
    }
from __future__ import annotations

from app.composer import ComposeService
from app.config import get_settings
from app.evidence import EvidenceSelector
from app.llm_client import WordingService
from app.planner import PlanBuilder
from app.validator import MessageValidator


_compose_service = ComposeService(
    planner=PlanBuilder(),
    evidence_selector=EvidenceSelector(),
    wording_service=WordingService(get_settings()),
    validator=MessageValidator(),
)


def compose(category: dict, merchant: dict, trigger: dict, customer: dict | None = None) -> dict:
    composed = _compose_service.compose_from_contexts(
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
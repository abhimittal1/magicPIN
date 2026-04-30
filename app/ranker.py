from __future__ import annotations

from app.schemas import MessagePlan, ResolvedContext


class TriggerRanker:
    def score(self, resolved: ResolvedContext, plan: MessagePlan) -> float:
        trigger = resolved.trigger
        urgency = float(trigger.get("urgency", 1))
        evidence_bonus = min(len(plan.evidence_facts), 6) * 0.35
        risk_penalty = len(plan.risk_flags) * 0.6
        scope_bonus = 0.4 if trigger.get("scope") == "customer" else 0.2
        history_bonus = 0.4 if resolved.merchant.get("conversation_history") else 0.0
        return urgency + evidence_bonus + scope_bonus + history_bonus - risk_penalty
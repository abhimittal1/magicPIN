from __future__ import annotations

from app.evidence import EvidenceSelector
from app.llm_client import WordingService, build_template_params
from app.planner import PlanBuilder
from app.schemas import ComposedMessage, MessagePlan, ResolvedContext
from app.validator import MessageValidator


class ComposeService:
    def __init__(self, planner: PlanBuilder, evidence_selector: EvidenceSelector, wording_service: WordingService, validator: MessageValidator) -> None:
        self.planner = planner
        self.evidence_selector = evidence_selector
        self.wording_service = wording_service
        self.validator = validator

    def plan(self, resolved: ResolvedContext) -> MessagePlan:
        plan = self.planner.build(resolved)
        plan.evidence_facts = self.evidence_selector.select(plan, resolved)
        return plan

    def compose_resolved(self, resolved: ResolvedContext, previous_body: str | None = None) -> ComposedMessage:
        plan = self.plan(resolved)
        body, rationale = self.wording_service.draft(plan, resolved)
        composed = ComposedMessage(
            body=body.strip(),
            cta=plan.cta_type,
            send_as=plan.send_as,
            suppression_key=resolved.trigger.get("suppression_key", ""),
            rationale=rationale.strip() or plan.rationale_seed,
            template_name=plan.template_name,
            template_params=[],
        )
        issues = self.validator.validate(composed, plan, resolved, previous_body=previous_body)
        if issues:
            fallback_body, fallback_rationale = self.wording_service._fallback(plan, resolved)
            composed = ComposedMessage(
                body=fallback_body,
                cta=plan.cta_type,
                send_as=plan.send_as,
                suppression_key=resolved.trigger.get("suppression_key", ""),
                rationale=fallback_rationale + f" Validation fallback: {', '.join(issues)}.",
                template_name=plan.template_name,
                template_params=[],
            )
        composed.template_params = build_template_params(plan, composed)
        return composed

    def compose_from_contexts(
        self,
        category: dict,
        merchant: dict,
        trigger: dict,
        customer: dict | None = None,
    ) -> ComposedMessage:
        from app.resolver import ContextResolver  # local import to avoid cycle
        from app.store import RuntimeStore

        resolver = ContextResolver(RuntimeStore())
        resolved = resolver.resolve_contexts(category=category, merchant=merchant, trigger=trigger, customer=customer)
        return self.compose_resolved(resolved)
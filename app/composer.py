from __future__ import annotations

from app.evidence import FactPicker
from app.llm_client import LLMWriter, build_template_params
from app.planner import StrategyEngine
from app.schemas import OutreachDraft, SendStrategy, AssembledScene
from app.validator import OutputGuard


class OutreachEngine:
    def __init__(self, planner: StrategyEngine, evidence_selector: FactPicker, wording_service: LLMWriter, validator: OutputGuard) -> None:
        self.planner = planner
        self.evidence_selector = evidence_selector
        self.wording_service = wording_service
        self.validator = validator

    def strategize(self, resolved: AssembledScene) -> SendStrategy:
        plan = self.planner.strategize(resolved)
        plan.evidence_facts = self.evidence_selector.pick(plan, resolved)
        return plan

    def draft(self, resolved: AssembledScene, previous_body: str | None = None) -> OutreachDraft:
        plan = self.strategize(resolved)
        body, rationale = self.wording_service.draft(plan, resolved)
        composed = OutreachDraft(
            body=body.strip(),
            cta=plan.cta_type,
            send_as=plan.send_as,
            suppression_key=resolved.trigger.get("suppression_key", ""),
            rationale=rationale.strip() or plan.rationale_seed,
            template_name=plan.template_name,
            template_params=[],
        )
        issues = self.validator.check(composed, plan, resolved, previous_body=previous_body)
        if issues:
            fallback_body, fallback_rationale = self.wording_service._fallback(plan, resolved)
            composed = OutreachDraft(
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

    def draft_from_raw(
        self,
        category: dict,
        merchant: dict,
        trigger: dict,
        customer: dict | None = None,
    ) -> OutreachDraft:
        from app.resolver import SceneLoader  # local import to avoid cycle
        from app.store import AgentMemory

        resolver = SceneLoader(AgentMemory())
        resolved = resolver.assemble(category=category, merchant=merchant, trigger=trigger, customer=customer)
        return self.draft(resolved)
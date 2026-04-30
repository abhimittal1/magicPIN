from __future__ import annotations

from app.schemas import MessagePlan, ResolvedContext
from app.voices import build_tone_profile


RESEARCH_KINDS = {"research_digest", "regulation_change", "cde_opportunity"}
EVENT_KINDS = {"festival_upcoming", "ipl_match_today", "competitor_opened", "category_seasonal", "supply_alert"}
PERFORMANCE_KINDS = {"perf_dip", "perf_spike", "milestone_reached", "review_theme_emerged", "seasonal_perf_dip"}
ACCOUNT_KINDS = {"renewal_due", "gbp_unverified", "winback_eligible", "dormant_with_vera"}
CUSTOMER_KINDS = {
    "recall_due",
    "customer_lapsed_soft",
    "customer_lapsed_hard",
    "appointment_tomorrow",
    "trial_followup",
    "chronic_refill_due",
    "wedding_package_followup",
}


class PlanBuilder:
    def build(self, resolved: ResolvedContext) -> MessagePlan:
        trigger = resolved.trigger
        merchant = resolved.merchant
        category = resolved.category
        customer = resolved.customer
        trigger_kind = trigger.get("kind", "generic")
        sparse_trigger = bool(resolved.flags.get("needs_sparse_fallback"))
        if trigger_kind == "active_planning_intent":
            family = "planning"
        elif trigger_kind == "curious_ask_due":
            family = "curiosity"
        elif trigger_kind in RESEARCH_KINDS:
            family = "research"
        elif trigger_kind in EVENT_KINDS:
            family = "event"
        elif trigger_kind in PERFORMANCE_KINDS:
            family = "performance"
        elif trigger_kind in ACCOUNT_KINDS:
            family = "account"
        elif trigger_kind in CUSTOMER_KINDS or trigger.get("scope") == "customer":
            family = "customer_followup"
        else:
            family = "fallback"

        if sparse_trigger:
            if family == "customer_followup":
                family = "customer_sparse"
            elif family not in {"planning", "curiosity", "research", "event", "performance", "account"}:
                family = "fallback"

        send_as = "merchant_on_behalf" if trigger.get("scope") == "customer" else "vera"
        cta_type = self._cta_type(family, resolved)
        template_name = self._template_name(send_as, family)
        rationale_seed = self._rationale_seed(family, trigger_kind, resolved)
        primary_goal = self._primary_goal(family, trigger_kind, resolved)

        risk_flags = []
        if resolved.flags.get("placeholder_payload"):
            risk_flags.append("placeholder_trigger")
        if resolved.flags.get("category_trigger_mismatch"):
            risk_flags.append("category_trigger_mismatch")
        if customer is not None and not resolved.flags.get("customer_opted_in"):
            risk_flags.append("customer_no_opt_in")

        return MessagePlan(
            trigger_family=family,
            audience="customer" if customer is not None else "merchant",
            send_as=send_as,
            primary_goal=primary_goal,
            cta_type=cta_type,
            template_name=template_name,
            template_params_seed=[merchant.get("identity", {}).get("name", "")],
            rationale_seed=rationale_seed,
            tone_profile=build_tone_profile(category, merchant, customer),
            risk_flags=risk_flags,
        )

    def _cta_type(self, family: str, resolved: ResolvedContext) -> str:
        payload = resolved.trigger.get("payload", {}) or {}
        if family == "customer_followup" and payload.get("available_slots"):
            return "multi_choice_slot"
        if family in {"planning", "account"}:
            return "binary_yes_no"
        if family == "customer_sparse":
            return "open_ended"
        if family == "event" and resolved.trigger.get("kind") == "supply_alert":
            return "binary_yes_no"
        return "open_ended"

    def _template_name(self, send_as: str, family: str) -> str:
        prefix = "merchant" if send_as == "merchant_on_behalf" else "vera"
        return f"{prefix}_{family}_v1"

    def _primary_goal(self, family: str, trigger_kind: str, resolved: ResolvedContext) -> str:
        if resolved.flags.get("mismatch_kind"):
            return f"acknowledge the {trigger_kind} signal safely without inventing category-specific details"
        if resolved.flags.get("placeholder_payload") and family == "event":
            return "turn a sparse event signal into one practical next step without inventing dates or offers"
        if resolved.flags.get("placeholder_payload") and family == "performance":
            return "turn a sparse performance signal into one safe action without inventing metrics"
        if resolved.flags.get("placeholder_payload") and family == "account":
            return "make the account issue concrete without pretending there is missing setup data"
        if family == "planning":
            return "move directly from intent to a concrete draft"
        if family == "curiosity":
            return "ask one low-friction question and offer a useful artifact in return"
        if family == "research":
            return "translate the trigger into a cited insight and one helpful next step"
        if family == "performance":
            return "explain why now using merchant numbers and suggest one practical action"
        if family == "customer_followup":
            return "send a precise reminder or re-engagement note that respects customer preferences"
        if family == "customer_sparse":
            return "send a cautious continuity follow-up without inventing missing logistics"
        if family == "account":
            return "make the account issue concrete and propose one clear next step"
        return f"handle {trigger_kind} safely without inventing details"

    def _rationale_seed(self, family: str, trigger_kind: str, resolved: ResolvedContext) -> str:
        merchant_name = resolved.merchant.get("identity", {}).get("name", "merchant")
        if family == "planning":
            return f"{merchant_name} already expressed planning intent, so the reply must switch into action mode immediately."
        if family == "customer_sparse":
            if trigger_kind in {"appointment_tomorrow", "chronic_refill_due", "recall_due"}:
                return "This reminder trigger is sparse, so keep the note warm, short, and limited to confirmation or simple follow-up."
            return "This trigger is sparse, so the message should stay conservative and rely only on customer state plus merchant identity."
        mismatch_kind = resolved.flags.get("mismatch_kind")
        if mismatch_kind:
            category_slug = resolved.category.get("slug", "this category")
            return f"The {mismatch_kind} trigger does not cleanly fit the {category_slug} category here, so stay generic and avoid unsupported operational details."
        if resolved.flags.get("placeholder_payload") and family in {"event", "performance", "account"}:
            return f"The {trigger_kind} trigger is placeholder-driven, so acknowledge the signal and suggest a next step without inventing specifics."
        return f"This message is driven by the {trigger_kind} trigger and should stay grounded in the pushed context."
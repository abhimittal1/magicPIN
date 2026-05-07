from __future__ import annotations

from typing import Any

from app.schemas import AssembledScene
from app.store import AgentMemory


KIND_SCOPE_MAP = {
    "appointment_tomorrow": {"dentists", "salons", "gyms"},
    "chronic_refill_due": {"pharmacies"},
    "recall_due": {"dentists", "pharmacies"},
    "supply_alert": {"pharmacies"},
    "trial_followup": {"gyms"},
    "wedding_package_followup": {"salons"},
}


class SceneLoader:
    def __init__(self, store: AgentMemory) -> None:
        self.store = store

    def load_for_trigger(self, trigger_id: str) -> AssembledScene | None:
        trigger = self.store.fetch("trigger", trigger_id)
        if trigger is None:
            return None
        merchant_id = trigger.get("merchant_id")
        if not merchant_id:
            return None
        merchant = self.store.fetch("merchant", merchant_id)
        if merchant is None:
            return None
        category_slug = merchant.get("category_slug")
        if not category_slug:
            return None
        category = self.store.fetch("category", category_slug)
        if category is None:
            return None
        customer = None
        customer_id = trigger.get("customer_id")
        if customer_id:
            customer = self.store.fetch("customer", customer_id)
        return self.assemble(category, merchant, trigger, customer)

    def assemble(
        self,
        category: dict[str, Any],
        merchant: dict[str, Any],
        trigger: dict[str, Any],
        customer: dict[str, Any] | None,
    ) -> AssembledScene:
        payload = trigger.get("payload", {}) or {}
        active_offers = [offer for offer in merchant.get("offers", []) if offer.get("status") == "active"]
        category_slug = category.get("slug", "")
        trigger_kind = trigger.get("kind", "")
        allowed_categories = KIND_SCOPE_MAP.get(trigger_kind)
        placeholder_payload = bool(payload.get("placeholder")) or payload == {"placeholder": True}
        mismatch_kind = trigger_kind if allowed_categories and category_slug not in allowed_categories else None
        category_trigger_mismatch = mismatch_kind is not None
        customer_opted_in = bool((customer or {}).get("preferences", {}).get("reminder_opt_in", False))
        flags = {
            "placeholder_payload": placeholder_payload,
            "category_trigger_mismatch": category_trigger_mismatch,
            "mismatch_kind": mismatch_kind,
            "has_active_offer": bool(active_offers),
            "active_offer_titles": [offer.get("title", "") for offer in active_offers],
            "customer_opted_in": customer_opted_in,
            "needs_sparse_fallback": placeholder_payload or category_trigger_mismatch,
        }
        return AssembledScene(
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer,
            flags=flags,
        )

    def load_for_merchant(self, merchant_id: str) -> AssembledScene | None:
        """Resolve category + merchant without a trigger — used for reply context lookups."""
        merchant = self.store.fetch("merchant", merchant_id)
        if merchant is None:
            return None
        category_slug = merchant.get("category_slug")
        if not category_slug:
            return None
        category = self.store.fetch("category", category_slug)
        if category is None:
            return None
        return self.assemble(category, merchant, {}, None)
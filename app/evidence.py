from __future__ import annotations

from typing import Any

from app.schemas import EvidenceFact, MessagePlan, ResolvedContext
from app.voices import customer_salutation, merchant_salutation


PERCENTAGE_HINTS = {
    "ctr",
    "pct",
    "percent",
    "percentage",
    "rate",
    "ratio",
    "share",
    "lift",
    "drop",
    "dip",
    "spike",
    "change",
    "growth",
    "decline",
}

DEDUPED_IDENTITY_LABELS = {"merchant_name", "merchant_salutation"}


def _format_number(value: float) -> str:
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def humanize_percentage(value: int | float | str) -> str:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if -1 <= numeric_value <= 1:
        numeric_value *= 100
    return f"{_format_number(numeric_value)}%"


def humanize_boolean(key: str, value: bool | str) -> str:
    normalized: bool | None
    if isinstance(value, bool):
        normalized = value
    elif isinstance(value, str) and value.lower() in {"true", "false"}:
        normalized = value.lower() == "true"
    else:
        normalized = None
    if normalized is None:
        return str(value)
    if "verified" in key:
        return "verified" if normalized else "not verified"
    return "yes" if normalized else "no"


def humanize_number(value: int | float) -> str:
    return _format_number(float(value))


def humanize_scalar(key: str, value: Any) -> str:
    normalized_key = key.lower()
    if isinstance(value, bool):
        return humanize_boolean(normalized_key, value)
    if isinstance(value, str):
        return humanize_boolean(normalized_key, value)
    if isinstance(value, (int, float)):
        if any(token in normalized_key.split("_") for token in PERCENTAGE_HINTS):
            return humanize_percentage(value)
        return humanize_number(value)
    return str(value)


class EvidenceSelector:
    def select(self, plan: MessagePlan, resolved: ResolvedContext) -> list[EvidenceFact]:
        facts: list[EvidenceFact] = []
        trigger = resolved.trigger
        merchant = resolved.merchant
        category = resolved.category
        customer = resolved.customer
        payload = trigger.get("payload", {}) or {}

        facts.extend(self._trigger_payload_facts(payload, category))
        facts.extend(self._merchant_facts(plan, resolved))
        facts.extend(self._customer_facts(plan, customer, merchant, category))
        facts.extend(self._category_facts(plan, category, merchant))

        deduped: list[EvidenceFact] = []
        seen: set[tuple[str, str]] = set()
        seen_labels: set[str] = set()
        for fact in facts:
            key = (fact.label, fact.text)
            if key in seen:
                continue
            if fact.label in DEDUPED_IDENTITY_LABELS and fact.label in seen_labels:
                continue
            seen.add(key)
            seen_labels.add(fact.label)
            deduped.append(fact)
        return deduped[:12]

    def _trigger_payload_facts(self, payload: dict[str, Any], category: dict[str, Any]) -> list[EvidenceFact]:
        facts: list[EvidenceFact] = []
        if payload.get("top_item_id"):
            digest_item = self._find_digest_item(category, payload["top_item_id"])
            if digest_item is not None:
                facts.append(EvidenceFact("trigger_item_title", digest_item.get("title", ""), "trigger.digest"))
                if digest_item.get("source"):
                    facts.append(EvidenceFact("trigger_item_source", digest_item["source"], "trigger.digest"))
                if digest_item.get("summary"):
                    facts.append(EvidenceFact("trigger_item_summary", digest_item["summary"], "trigger.digest"))
                if digest_item.get("actionable"):
                    facts.append(EvidenceFact("trigger_item_actionable", digest_item["actionable"], "trigger.digest"))
        if payload.get("digest_item_id"):
            digest_item = self._find_digest_item(category, payload["digest_item_id"])
            if digest_item is not None:
                facts.append(EvidenceFact("digest_item_title", digest_item.get("title", ""), "trigger.digest"))
                if digest_item.get("date"):
                    facts.append(EvidenceFact("digest_item_date", digest_item["date"], "trigger.digest"))
                if digest_item.get("source"):
                    facts.append(EvidenceFact("digest_item_source", digest_item["source"], "trigger.digest"))
        if payload.get("available_slots"):
            labels = [slot.get("label", "") for slot in payload["available_slots"] if slot.get("label")]
            if labels:
                facts.append(EvidenceFact("available_slots", "; ".join(labels[:3]), "trigger.payload"))
        for key, value in payload.items():
            if key in {"placeholder", "metric_or_topic", "available_slots", "top_item_id", "digest_item_id"}:
                continue
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                facts.append(EvidenceFact(f"trigger_{key}", humanize_scalar(key, value), "trigger.payload"))
            elif isinstance(value, list) and value and all(isinstance(item, str) for item in value):
                facts.append(EvidenceFact(f"trigger_{key}", "; ".join(value[:4]), "trigger.payload"))
        return facts

    def _merchant_facts(self, plan: MessagePlan, resolved: ResolvedContext) -> list[EvidenceFact]:
        merchant = resolved.merchant
        category = resolved.category
        facts = [
            EvidenceFact("merchant_salutation", merchant_salutation(category, merchant), "merchant.identity"),
            EvidenceFact("merchant_name", merchant.get("identity", {}).get("name", ""), "merchant.identity"),
            EvidenceFact("merchant_locality", merchant.get("identity", {}).get("locality", ""), "merchant.identity"),
        ]
        performance = merchant.get("performance", {})
        if plan.trigger_family in {"performance", "account", "event", "fallback"}:
            for key in ("views", "calls", "directions", "ctr"):
                if performance.get(key) is not None:
                    facts.append(EvidenceFact(f"merchant_{key}", humanize_scalar(key, performance[key]), "merchant.performance"))
        subscription = merchant.get("subscription", {})
        if subscription.get("days_remaining") is not None:
            facts.append(EvidenceFact("subscription_days_remaining", humanize_scalar("days_remaining", subscription["days_remaining"]), "merchant.subscription"))
        if subscription.get("status"):
            facts.append(EvidenceFact("subscription_status", subscription["status"], "merchant.subscription"))
        active_offers = [offer.get("title", "") for offer in merchant.get("offers", []) if offer.get("status") == "active" and offer.get("title")]
        if active_offers:
            facts.append(EvidenceFact("active_offers", "; ".join(active_offers[:3]), "merchant.offers"))
        signals = merchant.get("signals", [])
        if signals:
            facts.append(EvidenceFact("merchant_signals", "; ".join(signals[:4]), "merchant.signals"))
        history = merchant.get("conversation_history", [])
        if history:
            last_turn = history[-1]
            if last_turn.get("body"):
                facts.append(EvidenceFact("last_conversation_turn", last_turn["body"], "merchant.history"))
        aggregate = merchant.get("customer_aggregate", {})
        for key, value in aggregate.items():
            if isinstance(value, (str, int, float, bool)):
                facts.append(EvidenceFact(f"customer_aggregate_{key}", humanize_scalar(key, value), "merchant.customer_aggregate"))
        return facts

    def _customer_facts(
        self,
        plan: MessagePlan,
        customer: dict[str, Any] | None,
        merchant: dict[str, Any],
        category: dict[str, Any],
    ) -> list[EvidenceFact]:
        if customer is None:
            return []
        relationship = customer.get("relationship", {})
        preferences = customer.get("preferences", {})
        facts = [
            EvidenceFact("customer_name", customer_salutation(customer), "customer.identity"),
            EvidenceFact("customer_language", str(customer.get("identity", {}).get("language_pref", "")), "customer.identity"),
            EvidenceFact("customer_state", str(customer.get("state", "")), "customer.state"),
        ]
        for key in ("first_visit", "last_visit", "visits_total", "lifetime_value"):
            if relationship.get(key) is not None:
                facts.append(EvidenceFact(f"relationship_{key}", humanize_scalar(key, relationship[key]), "customer.relationship"))
        for key, value in preferences.items():
            if isinstance(value, (str, int, float, bool)):
                facts.append(EvidenceFact(f"customer_preference_{key}", humanize_scalar(key, value), "customer.preferences"))
        services = relationship.get("services_received", [])
        if services:
            facts.append(EvidenceFact("services_received", "; ".join(str(item) for item in services[:5]), "customer.relationship"))
        return facts

    def _category_facts(self, plan: MessagePlan, category: dict[str, Any], merchant: dict[str, Any]) -> list[EvidenceFact]:
        peer_stats = category.get("peer_stats", {})
        facts: list[EvidenceFact] = []
        if plan.trigger_family in {"performance", "event", "fallback"}:
            if peer_stats.get("avg_ctr") is not None:
                facts.append(EvidenceFact("peer_avg_ctr", humanize_scalar("avg_ctr", peer_stats["avg_ctr"]), "category.peer_stats"))
            if peer_stats.get("avg_review_count") is not None:
                facts.append(EvidenceFact("peer_avg_review_count", humanize_scalar("avg_review_count", peer_stats["avg_review_count"]), "category.peer_stats"))
        if plan.trigger_family == "curiosity":
            seasonal = category.get("seasonal_beats", [])
            if seasonal:
                facts.append(EvidenceFact("seasonal_note", seasonal[0].get("note", ""), "category.seasonal_beats"))
        return facts

    def _find_digest_item(self, category: dict[str, Any], item_id: str) -> dict[str, Any] | None:
        for item in category.get("digest", []):
            if item.get("id") == item_id:
                return item
        return None
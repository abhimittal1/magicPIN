from __future__ import annotations

import re
from typing import Any

from app.evidence import humanize_scalar
from app.schemas import OutreachDraft, SendStrategy, AssembledScene


NUMBER_RE = re.compile(r"\b\d[\dTtZz,.:/%+-]*\b")
SAFE_NUMERICS = {"1", "2", "3", "4", "5", "10", "15", "30", "48", "90"}
FILLER_SIGNALS = [
    re.compile(r"let me look into that", re.IGNORECASE),
    re.compile(r"give me a moment", re.IGNORECASE),
    re.compile(r"could you share a little more context", re.IGNORECASE),
]
PROBE_SIGNALS = [
    re.compile(r"\bwould you\b", re.IGNORECASE),
    re.compile(r"\bdo you\b", re.IGNORECASE),
    re.compile(r"\bcan you tell\b", re.IGNORECASE),
    re.compile(r"\bhow about\b", re.IGNORECASE),
]
AFFIRMATIVE_SIGNALS = [
    re.compile(r"\byes\b", re.IGNORECASE),
    re.compile(r"go ahead", re.IGNORECASE),
    re.compile(r"let'?s do it", re.IGNORECASE),
    re.compile(r"whats next|what's next", re.IGNORECASE),
    re.compile(r"next kya", re.IGNORECASE),
    re.compile(r"\bhaan\b", re.IGNORECASE),
    re.compile(r"theek hai", re.IGNORECASE),
    re.compile(r"kar do", re.IGNORECASE),
]


def _extract_numeric_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in NUMBER_RE.findall(text):
        normalized = re.sub(r"[^\d.]", "", match)
        if normalized:
            tokens.add(normalized.lstrip("0") or "0")
        if any(separator in match for separator in ("-", ":", "/", "+", ".")):
            for part in re.split(r"[^\d]+", match):
                if part:
                    normalized_part = part.lstrip("0") or "0"
                    tokens.add(normalized_part)
                    if any(separator in match for separator in (":", "T")):
                        numeric_part = int(part)
                        if 0 <= numeric_part <= 23:
                            hour_12 = numeric_part % 12 or 12
                            tokens.add(str(hour_12))
    return tokens


def _numbers_from_context_value(value: Any, key: str = "") -> set[str]:
    tokens: set[str] = set()
    if value is None or isinstance(value, bool):
        return tokens
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            tokens.update(_numbers_from_context_value(child_value, str(child_key)))
        return tokens
    if isinstance(value, list):
        for item in value:
            tokens.update(_numbers_from_context_value(item, key))
        return tokens
    if isinstance(value, (int, float)):
        tokens.update(_extract_numeric_tokens(str(value)))
        tokens.update(_extract_numeric_tokens(humanize_scalar(key, value)))
        return tokens
    if isinstance(value, str):
        tokens.update(_extract_numeric_tokens(value))
    return tokens


def _chk_empty(
    composed: OutreachDraft, plan: SendStrategy, resolved: AssembledScene, prev: str | None
) -> list[str]:
    return ["empty_body"] if not composed.body.strip() else []


def _chk_send_as(
    composed: OutreachDraft, plan: SendStrategy, resolved: AssembledScene, prev: str | None
) -> list[str]:
    return ["wrong_send_as"] if composed.send_as != plan.send_as else []


def _chk_taboo(
    composed: OutreachDraft, plan: SendStrategy, resolved: AssembledScene, prev: str | None
) -> list[str]:
    taboo = {str(item).lower() for item in resolved.category.get("voice", {}).get("vocab_taboo", [])}
    body_lower = composed.body.lower()
    return [f"taboo:{word}" for word in taboo if word and word in body_lower]


def _chk_repeated(
    composed: OutreachDraft, plan: SendStrategy, resolved: AssembledScene, prev: str | None
) -> list[str]:
    if prev and composed.body.strip() == prev.strip():
        return ["repeated_body"]
    return []


def _chk_numbers(
    composed: OutreachDraft, plan: SendStrategy, resolved: AssembledScene, prev: str | None
) -> list[str]:
    allowed: set[str] = set()
    for fact in plan.evidence_facts:
        allowed.update(_extract_numeric_tokens(fact.text))
    for context in (resolved.category, resolved.merchant, resolved.trigger, resolved.customer or {}):
        allowed.update(_numbers_from_context_value(context))
    allowed.update(SAFE_NUMERICS)
    if plan.cta_type == "multi_choice_slot":
        allowed.update({"1", "2", "3"})
    unsupported = sorted(t for t in _extract_numeric_tokens(composed.body) if t not in allowed)
    return ["unsupported_numbers:" + ",".join(unsupported[:5])] if unsupported else []


def _chk_customer_on_behalf(
    composed: OutreachDraft, plan: SendStrategy, resolved: AssembledScene, prev: str | None
) -> list[str]:
    if plan.send_as != "merchant_on_behalf":
        return []
    issues: list[str] = []
    body_lower = composed.body.lower()
    customer_name = (resolved.customer or {}).get("identity", {}).get("name", "")
    if customer_name and customer_name.lower() not in body_lower[:80]:
        issues.append("missing_customer_name")
    active_offers = resolved.flags.get("active_offer_titles", [])
    if active_offers:
        if "₹" in composed.body and not any(offer in composed.body for offer in active_offers):
            issues.append("inactive_or_missing_offer_reference")
    return issues


def _chk_gbp(
    composed: OutreachDraft, plan: SendStrategy, resolved: AssembledScene, prev: str | None
) -> list[str]:
    if resolved.trigger.get("kind") != "gbp_unverified":
        return []
    issues: list[str] = []
    body_lower = composed.body.lower()
    payload = resolved.trigger.get("payload", {}) or {}
    verification_path = payload.get("verification_path")
    if verification_path:
        normalized_path = humanize_scalar("verification_path", verification_path).lower()
        path_covered = normalized_path in body_lower or ("postcard" in body_lower and "phone call" in body_lower)
        if not path_covered:
            issues.append("missing_verification_path")
    estimated_uplift = payload.get("estimated_uplift_pct")
    if estimated_uplift is not None:
        uplift_text = humanize_scalar("estimated_uplift_pct", estimated_uplift)
        if uplift_text not in composed.body:
            issues.append("missing_estimated_uplift")
    if "not verified" not in body_lower and "verify nahi" not in body_lower:
        issues.append("missing_verification_status")
    return issues


_COMPOSE_CHECKERS = [
    _chk_empty,
    _chk_send_as,
    _chk_taboo,
    _chk_repeated,
    _chk_numbers,
    _chk_customer_on_behalf,
    _chk_gbp,
]


class OutputGuard:
    def check(self, composed: OutreachDraft, plan: SendStrategy, resolved: AssembledScene, previous_body: str | None = None) -> list[str]:
        return [issue for fn in _COMPOSE_CHECKERS for issue in fn(composed, plan, resolved, previous_body)]

    def check_reply(
        self,
        body: str,
        incoming_message: str,
        previous_bot_body: str | None = None,
    ) -> list[str]:
        issues: list[str] = []
        stripped = body.strip()
        if not stripped:
            issues.append("empty_reply")
            return issues
        if any(pattern.search(stripped) for pattern in FILLER_SIGNALS):
            issues.append("generic_reply")
        if previous_bot_body and stripped == previous_bot_body.strip():
            issues.append("repeated_reply")
        if any(pattern.search(incoming_message) for pattern in AFFIRMATIVE_SIGNALS):
            if any(pattern.search(stripped) for pattern in PROBE_SIGNALS):
                issues.append("qualification_after_commit")
        return issues

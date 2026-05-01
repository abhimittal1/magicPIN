from __future__ import annotations

import re

from app.evidence import humanize_scalar
from app.schemas import ComposedMessage, MessagePlan, ResolvedContext


NUM_PATTERN = re.compile(r"\b\d[\dTtZz,.:/%+-]*\b")
GENERIC_REPLY_PATTERNS = [
    re.compile(r"let me look into that", re.IGNORECASE),
    re.compile(r"give me a moment", re.IGNORECASE),
    re.compile(r"could you share a little more context", re.IGNORECASE),
]
QUALIFYING_PATTERNS = [
    re.compile(r"\bwould you\b", re.IGNORECASE),
    re.compile(r"\bdo you\b", re.IGNORECASE),
    re.compile(r"\bcan you tell\b", re.IGNORECASE),
    re.compile(r"\bhow about\b", re.IGNORECASE),
]
COMMIT_PATTERNS = [
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
    for match in NUM_PATTERN.findall(text):
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


class MessageValidator:
    def validate(self, composed: ComposedMessage, plan: MessagePlan, resolved: ResolvedContext, previous_body: str | None = None) -> list[str]:
        issues: list[str] = []
        if not composed.body.strip():
            issues.append("empty_body")
        if composed.send_as != plan.send_as:
            issues.append("wrong_send_as")
        taboo = {str(item).lower() for item in resolved.category.get("voice", {}).get("vocab_taboo", [])}
        body_lower = composed.body.lower()
        for word in taboo:
            if word and word in body_lower:
                issues.append(f"taboo:{word}")
        if previous_body and composed.body.strip() == previous_body.strip():
            issues.append("repeated_body")
        allowed_numbers = set()
        for fact in plan.evidence_facts:
            allowed_numbers.update(_extract_numeric_tokens(fact.text))
        if plan.cta_type == "multi_choice_slot":
            allowed_numbers.update({"1", "2", "3"})
        body_numbers = _extract_numeric_tokens(composed.body)
        unsupported_numbers = sorted(token for token in body_numbers if token not in allowed_numbers)
        if unsupported_numbers:
            issues.append("unsupported_numbers:" + ",".join(unsupported_numbers[:5]))
        if plan.send_as == "merchant_on_behalf":
            active_offers = resolved.flags.get("active_offer_titles", [])
            if active_offers:
                rupee_body = any(offer in composed.body for offer in active_offers)
                any_rupee = "₹" in composed.body
                if any_rupee and not rupee_body:
                    issues.append("inactive_or_missing_offer_reference")
        if resolved.trigger.get("kind") == "gbp_unverified":
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

    def validate_reply(
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
        if any(pattern.search(stripped) for pattern in GENERIC_REPLY_PATTERNS):
            issues.append("generic_reply")
        if previous_bot_body and stripped == previous_bot_body.strip():
            issues.append("repeated_reply")
        if any(pattern.search(incoming_message) for pattern in COMMIT_PATTERNS):
            if any(pattern.search(stripped) for pattern in QUALIFYING_PATTERNS):
                issues.append("qualification_after_commit")
        return issues
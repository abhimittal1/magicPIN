from __future__ import annotations

from datetime import timedelta

from app.config import Settings
from app.llm_client import WordingService
from app.reply_classifier import ReplyClassification, ReplyClassifier
from app.resolver import ContextResolver
from app.store import ConversationRecord, RuntimeStore, parse_iso, utc_now_iso
from app.validator import MessageValidator


class ReplyManager:
    def __init__(self, store: RuntimeStore, resolver: ContextResolver, classifier: ReplyClassifier, settings: Settings, wording_service: WordingService) -> None:
        self.store = store
        self.resolver = resolver
        self.classifier = classifier
        self.settings = settings
        self.wording_service = wording_service
        self.validator = MessageValidator()

    def handle(
        self,
        conversation_id: str,
        merchant_id: str | None,
        customer_id: str | None,
        from_role: str,
        message: str,
        received_at: str,
        turn_number: int,
    ) -> dict:
        record = self.store.create_conversation(
            conversation_id=conversation_id,
            merchant_id=merchant_id,
            customer_id=customer_id,
            trigger_id=self._existing_trigger_id(conversation_id),
            send_as=None,
            suppression_key=None,
            prompt_version=self.settings.prompt_version,
        )
        effective_customer_id = customer_id or record.customer_id
        inbound_role = self._normalize_from_role(from_role, effective_customer_id)
        self.store.add_turn(conversation_id, from_role=inbound_role, message=message, ts=received_at)

        classification = self.classifier.classify(message)
        if classification.kind == "auto_reply":
            return self._handle_auto_reply(record, received_at)
        if classification.kind in {"explicit_no_or_stop", "abusive"}:
            self.store.mark_ended(conversation_id)
            self.store.suppress(record.suppression_key)
            return {"action": "end", "rationale": "The contact explicitly opted out or turned hostile, so the conversation is ending gracefully."}
        if classification.kind == "busy_wait":
            wait_seconds = self.settings.default_busy_wait_seconds
            self.store.mark_wait(conversation_id, self._future_iso(received_at, wait_seconds))
            return {"action": "wait", "wait_seconds": wait_seconds, "rationale": "busy_wait"}

        decision = self.wording_service.classify_and_reply(
            message=message,
            from_role=inbound_role,
            turns=record.turns,
            resolved=self._resolve_for_reply(record),
        )
        previous_bot_body = self._last_bot_turn(record)
        if decision["action"] == "send":
            issues = self.validator.validate_reply(
                body=decision.get("body") or "",
                incoming_message=message,
                previous_bot_body=previous_bot_body,
            )
            if issues:
                decision = self.wording_service._reply_decision_fallback(
                    message=message,
                    from_role=inbound_role,
                    resolved=self._resolve_for_reply(record),
                )
                if decision["action"] == "send":
                    decision["rationale"] = f"{decision['rationale']}; repaired_reply:{','.join(issues)}"
        if decision["action"] == "wait":
            wait_seconds = decision.get("wait_seconds") or self.settings.default_busy_wait_seconds
            self.store.mark_wait(conversation_id, self._future_iso(received_at, wait_seconds))
            return {"action": "wait", "wait_seconds": wait_seconds, "rationale": decision["rationale"]}
        if decision["action"] == "end":
            self.store.mark_ended(conversation_id)
            self.store.suppress(record.suppression_key)
            if decision.get("body"):
                self.store.add_turn(conversation_id, from_role="bot", message=decision["body"], ts=utc_now_iso(), action="end")
                return {"action": "end", "body": decision["body"], "cta": "open_ended", "rationale": decision["rationale"]}
            return {"action": "end", "rationale": decision["rationale"]}

        body = decision.get("body") or "Could you share a little more context?"
        self.store.add_turn(conversation_id, from_role="bot", message=body, ts=utc_now_iso(), action="send")
        # When the inbound message is from a customer, surface send_as so the caller
        # knows the reply should be voiced as the merchant, not as Vera directly.
        send_as = "merchant_on_behalf" if inbound_role == "customer" else "vera"
        return {"action": "send", "body": body, "cta": "open_ended", "send_as": send_as, "rationale": decision["rationale"]}

    def _normalize_from_role(self, from_role: str, customer_id: str | None) -> str:
        normalized = (from_role or "").strip().lower()
        if normalized in {"customer", "merchant"}:
            return normalized
        return "customer" if customer_id else "merchant"

    def _handle_auto_reply(self, record: ConversationRecord, received_at: str) -> dict:
        hits = self.store.increment_auto_reply_hits(record.conversation_id)
        if not record.trigger_id and record.suppression_key and hits == 1:
            self.store.mark_ended(record.conversation_id)
            self.store.suppress(record.suppression_key)
            return {"action": "end", "rationale": "An auto-reply was detected, so the conversation is being closed immediately rather than wasting further turns."}
        if hits == 1:
            body = "Looks like this is an auto-reply. When the owner sees this, just reply YES and I will continue with the useful next step."
            self.store.add_turn(record.conversation_id, from_role="bot", message=body, ts=utc_now_iso(), action="send")
            return {"action": "send", "body": body, "cta": "binary_yes_no", "rationale": "auto_reply_first_probe"}
        if hits == 2:
            wait_seconds = max(self.settings.default_auto_reply_wait_seconds, 86400)
            self.store.mark_wait(record.conversation_id, self._future_iso(received_at, wait_seconds))
            return {"action": "wait", "wait_seconds": wait_seconds, "rationale": "auto_reply_wait_after_repeat"}
        self.store.mark_ended(record.conversation_id)
        self.store.suppress(record.suppression_key)
        return {"action": "end", "rationale": "Repeated auto-replies indicate no real engagement, so the conversation is being closed."}

    def _existing_trigger_id(self, conversation_id: str) -> str | None:
        record = self.store.get_conversation(conversation_id)
        return None if record is None else record.trigger_id

    def _resolve_for_reply(self, record: ConversationRecord):
        if record.trigger_id:
            return self.resolver.resolve_trigger_id(record.trigger_id)
        if record.merchant_id:
            return self.resolver.resolve_merchant_id(record.merchant_id)
        return None

    def _future_iso(self, base: str, wait_seconds: int) -> str:
        start = parse_iso(base) or parse_iso(utc_now_iso())
        future = start + timedelta(seconds=wait_seconds)
        return future.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _last_bot_turn(self, record: ConversationRecord) -> str | None:
        for turn in reversed(record.turns):
            if turn.from_role == "bot":
                return turn.message
        return None

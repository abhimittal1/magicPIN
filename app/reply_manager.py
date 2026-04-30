from __future__ import annotations

from datetime import timedelta

from app.config import Settings
from app.llm_client import WordingService
from app.reply_classifier import ReplyClassification, ReplyClassifier
from app.resolver import ContextResolver
from app.store import ConversationRecord, RuntimeStore, parse_iso, utc_now_iso


class ReplyManager:
    def __init__(self, store: RuntimeStore, resolver: ContextResolver, classifier: ReplyClassifier, settings: Settings, wording_service: WordingService) -> None:
        self.store = store
        self.resolver = resolver
        self.classifier = classifier
        self.settings = settings
        self.wording_service = wording_service

    def handle(
        self,
        conversation_id: str,
        merchant_id: str | None,
        customer_id: str | None,
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
        self.store.add_turn(conversation_id, from_role="merchant" if customer_id is None else "customer", message=message, ts=received_at)

        classification = self.classifier.classify(message)
        if classification.kind == "auto_reply":
            return self._handle_auto_reply(record, received_at)
        if classification.kind in {"explicit_no_or_stop", "abusive"}:
            self.store.mark_ended(conversation_id)
            self.store.suppress(record.suppression_key)
            return {"action": "end", "rationale": "The contact explicitly opted out or turned hostile, so the conversation is ending gracefully."}
        if classification.kind == "later_busy":
            wait_until = self._future_iso(received_at, self.settings.default_busy_wait_seconds)
            self.store.mark_wait(conversation_id, wait_until)
            return {"action": "wait", "wait_seconds": self.settings.default_busy_wait_seconds, "rationale": "The contact asked for time, so the bot is backing off before retrying."}
        if classification.kind == "off_topic":
            body = "I will leave that topic to the right expert for now. On this thread, I can still keep the next step simple if you want."
            self.store.add_turn(conversation_id, from_role="bot", message=body, ts=utc_now_iso(), action="send")
            return {"action": "send", "body": body, "cta": "open_ended", "rationale": "The ask is out of scope, so the reply declines politely and redirects to the original thread."}
        if classification.kind == "explicit_yes_or_commit":
            body, rationale = self._action_mode_reply(record, message)
            self.store.add_turn(conversation_id, from_role="bot", message=body, ts=utc_now_iso(), action="send")
            return {"action": "send", "body": body, "cta": "open_ended", "rationale": rationale}
        if classification.kind == "question":
            body, rationale = self._question_reply(record, message)
            self.store.add_turn(conversation_id, from_role="bot", message=body, ts=utc_now_iso(), action="send")
            return {"action": "send", "body": body, "cta": "open_ended", "rationale": rationale}

        body, rationale = self.wording_service.chat_reply(
            message=message,
            from_role="customer" if customer_id else "merchant",
            turns=record.turns,
            resolved=self._resolve_for_reply(record),
        )
        self.store.add_turn(conversation_id, from_role="bot", message=body, ts=utc_now_iso(), action="send")
        return {"action": "send", "body": body, "cta": "open_ended", "rationale": rationale}

    def _existing_trigger_id(self, conversation_id: str) -> str | None:
        record = self.store.get_conversation(conversation_id)
        return None if record is None else record.trigger_id

    def _resolve_for_reply(self, record: ConversationRecord):
        if record.trigger_id:
            return self.resolver.resolve_trigger_id(record.trigger_id)
        if record.merchant_id:
            return self.resolver.resolve_merchant_id(record.merchant_id)
        return None

    def _handle_auto_reply(self, record: ConversationRecord, received_at: str) -> dict:
        self.store.mark_ended(record.conversation_id)
        self.store.suppress(record.suppression_key)
        return {"action": "end", "rationale": "An auto-reply was detected, so the conversation is being closed immediately rather than wasting further turns."}

    def _action_mode_reply(self, record: ConversationRecord, message: str) -> tuple[str, str]:
        return self.wording_service.chat_reply(
            message=message,
            from_role="customer" if record.customer_id else "merchant",
            turns=record.turns,
            resolved=self._resolve_for_reply(record),
        )

    def _question_reply(self, record: ConversationRecord, message: str) -> tuple[str, str]:
        return self.wording_service.chat_reply(
            message=message,
            from_role="customer" if record.customer_id else "merchant",
            turns=record.turns,
            resolved=self._resolve_for_reply(record),
        )

    def _future_iso(self, base: str, wait_seconds: int) -> str:
        start = parse_iso(base) or parse_iso(utc_now_iso())
        future = start + timedelta(seconds=wait_seconds)
        return future.replace(microsecond=0).isoformat().replace("+00:00", "Z")
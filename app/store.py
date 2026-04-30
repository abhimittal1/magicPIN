from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


@dataclass
class VersionedContext:
    version: int
    payload: dict[str, Any]
    stored_at: str


@dataclass(frozen=True)
class ContextUpsertResult:
    accepted: bool
    current_version: int | None = None
    reason: str | None = None
    details: str | None = None


@dataclass
class ConversationTurn:
    from_role: str
    message: str
    ts: str
    action: str | None = None


@dataclass
class ConversationRecord:
    conversation_id: str
    merchant_id: str | None = None
    customer_id: str | None = None
    trigger_id: str | None = None
    send_as: str | None = None
    suppression_key: str | None = None
    wait_until: str | None = None
    auto_reply_hits: int = 0
    ended: bool = False
    prompt_version: str | None = None
    turns: list[ConversationTurn] = field(default_factory=list)


class RuntimeStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._contexts: dict[tuple[str, str], VersionedContext] = {}
        self._conversations: dict[str, ConversationRecord] = {}
        self._suppressed: set[str] = set()
        self.started_at = datetime.now(timezone.utc)

    def upsert_context(self, scope: str, context_id: str, version: int, payload: dict[str, Any]) -> ContextUpsertResult:
        with self._lock:
            key = (scope, context_id)
            current = self._contexts.get(key)
            if current is not None:
                if version < current.version:
                    return ContextUpsertResult(
                        accepted=False,
                        current_version=current.version,
                        reason="stale_version",
                        details=(
                            f"Received version {version} for {scope}/{context_id}, "
                            f"but version {current.version} is already stored."
                        ),
                    )
                if version == current.version:
                    if current.payload == payload:
                        return ContextUpsertResult(accepted=True, current_version=current.version)
                    return ContextUpsertResult(
                        accepted=False,
                        current_version=current.version,
                        reason="same_version_conflict",
                        details=(
                            f"Received version {version} for {scope}/{context_id}, but the stored payload for "
                            "that version is different. Reset the runtime store or resend with a higher version."
                        ),
                    )
            self._contexts[key] = VersionedContext(version=version, payload=payload, stored_at=utc_now_iso())
            return ContextUpsertResult(accepted=True, current_version=version)

    def get_context(self, scope: str, context_id: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._contexts.get((scope, context_id))
            return None if entry is None else entry.payload

    def count_contexts(self) -> dict[str, int]:
        counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        with self._lock:
            for scope, _ in self._contexts:
                counts[scope] = counts.get(scope, 0) + 1
        return counts

    def create_conversation(
        self,
        conversation_id: str,
        merchant_id: str | None,
        customer_id: str | None,
        trigger_id: str | None,
        send_as: str | None,
        suppression_key: str | None,
        prompt_version: str | None,
    ) -> ConversationRecord:
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None:
                record = ConversationRecord(
                    conversation_id=conversation_id,
                    merchant_id=merchant_id,
                    customer_id=customer_id,
                    trigger_id=trigger_id,
                    send_as=send_as,
                    suppression_key=suppression_key,
                    prompt_version=prompt_version,
                )
                self._conversations[conversation_id] = record
            return record

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        with self._lock:
            return self._conversations.get(conversation_id)

    def add_turn(self, conversation_id: str, from_role: str, message: str, ts: str, action: str | None = None) -> None:
        with self._lock:
            record = self._conversations.setdefault(conversation_id, ConversationRecord(conversation_id=conversation_id))
            record.turns.append(ConversationTurn(from_role=from_role, message=message, ts=ts, action=action))

    def has_sent_body(self, conversation_id: str, body: str) -> bool:
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None:
                return False
            return any(turn.message == body and turn.from_role == "bot" for turn in record.turns)

    def suppress(self, suppression_key: str | None) -> None:
        if not suppression_key:
            return
        with self._lock:
            self._suppressed.add(suppression_key)

    def is_suppressed(self, suppression_key: str | None) -> bool:
        if not suppression_key:
            return False
        with self._lock:
            return suppression_key in self._suppressed

    def mark_wait(self, conversation_id: str, wait_until: str) -> None:
        with self._lock:
            record = self._conversations.setdefault(conversation_id, ConversationRecord(conversation_id=conversation_id))
            record.wait_until = wait_until

    def is_waiting(self, conversation_id: str, now_iso: str) -> bool:
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None or record.wait_until is None:
                return False
            wait_until = parse_iso(record.wait_until)
            current = parse_iso(now_iso)
            if wait_until is None or current is None:
                return False
            return current < wait_until

    def increment_auto_reply_hits(self, conversation_id: str) -> int:
        with self._lock:
            record = self._conversations.setdefault(conversation_id, ConversationRecord(conversation_id=conversation_id))
            record.auto_reply_hits += 1
            return record.auto_reply_hits

    def mark_ended(self, conversation_id: str) -> None:
        with self._lock:
            record = self._conversations.setdefault(conversation_id, ConversationRecord(conversation_id=conversation_id))
            record.ended = True

    def clear(self) -> None:
        with self._lock:
            self._contexts.clear()
            self._conversations.clear()
            self._suppressed.clear()
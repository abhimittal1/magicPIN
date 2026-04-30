from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ContextScope = Literal["category", "merchant", "customer", "trigger"]
SendAs = Literal["vera", "merchant_on_behalf"]
ReplyAction = Literal["send", "wait", "end"]


class ContextPushRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: ContextScope
    context_id: str
    version: int = Field(ge=1)
    payload: dict[str, Any]
    delivered_at: str


class ContextPushResponse(BaseModel):
    accepted: bool
    ack_id: str | None = None
    stored_at: str | None = None
    reason: str | None = None
    current_version: int | None = None
    details: str | None = None


class TickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    now: str
    available_triggers: list[str] = Field(default_factory=list)


class TickAction(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: str | None = None
    send_as: SendAs
    trigger_id: str
    template_name: str
    template_params: list[str] = Field(default_factory=list)
    body: str
    cta: str
    suppression_key: str
    rationale: str


class TickResponse(BaseModel):
    actions: list[TickAction] = Field(default_factory=list)


class ReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    merchant_id: str | None = None
    customer_id: str | None = None
    from_role: str
    message: str
    received_at: str
    turn_number: int


class ReplyResponse(BaseModel):
    action: ReplyAction
    body: str | None = None
    cta: str | None = None
    wait_seconds: int | None = None
    rationale: str


class HealthzResponse(BaseModel):
    status: str
    uptime_seconds: int
    contexts_loaded: dict[str, int]


class MetadataResponse(BaseModel):
    team_name: str
    team_members: list[str]
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str


class LLMDraft(BaseModel):
    body: str
    rationale: str


@dataclass(frozen=True)
class EvidenceFact:
    label: str
    text: str
    source: str


@dataclass
class MessagePlan:
    trigger_family: str
    audience: str
    send_as: SendAs
    primary_goal: str
    cta_type: str
    template_name: str
    template_params_seed: list[str] = field(default_factory=list)
    rationale_seed: str = ""
    tone_profile: list[str] = field(default_factory=list)
    evidence_facts: list[EvidenceFact] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedContext:
    category: dict[str, Any]
    merchant: dict[str, Any]
    trigger: dict[str, Any]
    customer: dict[str, Any] | None
    flags: dict[str, Any]


@dataclass
class ComposedMessage:
    body: str
    cta: str
    send_as: SendAs
    suppression_key: str
    rationale: str
    template_name: str
    template_params: list[str]
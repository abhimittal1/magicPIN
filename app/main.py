from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.composer import ComposeService
from app.config import get_settings
from app.evidence import EvidenceSelector
from app.llm_client import WordingService
from app.planner import PlanBuilder
from app.ranker import TriggerRanker
from app.reply_classifier import ReplyClassifier
from app.reply_manager import ReplyManager
from app.resolver import ContextResolver
from app.schemas import ContextPushRequest, ContextPushResponse, HealthzResponse, MetadataResponse, ReplyRequest, ReplyResponse, TickAction, TickRequest, TickResponse
from app.store import RuntimeStore, utc_now_iso
from app.validator import MessageValidator


settings = get_settings()
store = RuntimeStore()
resolver = ContextResolver(store)
wording_service = WordingService(settings)
compose_service = ComposeService(
    planner=PlanBuilder(),
    evidence_selector=EvidenceSelector(),
    wording_service=wording_service,
    validator=MessageValidator(),
)
ranker = TriggerRanker()
reply_manager = ReplyManager(store=store, resolver=resolver, classifier=ReplyClassifier(), settings=settings, wording_service=wording_service)

app = FastAPI(title="magicpin Challenge Bot")


@app.get("/v1/healthz", response_model=HealthzResponse)
async def healthz() -> HealthzResponse:
    uptime = int((datetime.now(store.started_at.tzinfo) - store.started_at).total_seconds())
    return HealthzResponse(status="ok", uptime_seconds=uptime, contexts_loaded=store.count_contexts())


@app.get("/v1/metadata", response_model=MetadataResponse)
async def metadata() -> MetadataResponse:
    return MetadataResponse(
        team_name=settings.team_name,
        team_members=settings.team_members,
        model=settings.openai_model if settings.llm_enabled else "deterministic-fallback",
        approach="deterministic planner + evidence selector + LangChain OpenAI wording + validator",
        contact_email=settings.contact_email,
        version=settings.bot_version,
        submitted_at=settings.submitted_at,
    )


@app.post("/v1/context", response_model=ContextPushResponse)
async def push_context(body: ContextPushRequest) -> ContextPushResponse:
    result = store.upsert_context(body.scope, body.context_id, body.version, body.payload)
    if not result.accepted:
        response = ContextPushResponse(
            accepted=False,
            reason=result.reason or "stale_version",
            current_version=result.current_version,
            details=result.details,
        )
        return JSONResponse(status_code=409, content=response.model_dump())
    return ContextPushResponse(
        accepted=True,
        ack_id=f"ack_{body.context_id}_v{body.version}",
        stored_at=utc_now_iso(),
    )


@app.post("/v1/tick", response_model=TickResponse)
async def tick(body: TickRequest) -> TickResponse:
    candidates: list[tuple[float, str]] = []
    for trigger_id in body.available_triggers:
        resolved = resolver.resolve_trigger_id(trigger_id)
        if resolved is None:
            continue
        suppression_key = resolved.trigger.get("suppression_key")
        if store.is_suppressed(suppression_key):
            continue
        plan = compose_service.plan(resolved)
        score = ranker.score(resolved, plan)
        candidates.append((score, trigger_id))

    actions: list[TickAction] = []
    for _, trigger_id in sorted(candidates, key=lambda item: item[0], reverse=True)[: settings.max_actions_per_tick]:
        resolved = resolver.resolve_trigger_id(trigger_id)
        if resolved is None:
            continue
        composed = compose_service.compose_resolved(resolved)
        conversation_id = f"conv_{uuid4().hex[:12]}"
        record = store.create_conversation(
            conversation_id=conversation_id,
            merchant_id=resolved.trigger.get("merchant_id"),
            customer_id=resolved.trigger.get("customer_id"),
            trigger_id=trigger_id,
            send_as=composed.send_as,
            suppression_key=composed.suppression_key,
            prompt_version=settings.prompt_version,
        )
        store.add_turn(conversation_id, from_role="bot", message=composed.body, ts=utc_now_iso(), action="send")
        store.suppress(composed.suppression_key)
        actions.append(
            TickAction(
                conversation_id=conversation_id,
                merchant_id=resolved.trigger.get("merchant_id", ""),
                customer_id=resolved.trigger.get("customer_id"),
                send_as=composed.send_as,
                trigger_id=trigger_id,
                template_name=composed.template_name,
                template_params=composed.template_params,
                body=composed.body,
                cta=composed.cta,
                suppression_key=composed.suppression_key,
                rationale=composed.rationale,
            )
        )
        record.send_as = composed.send_as
    return TickResponse(actions=actions)


@app.post("/v1/reply", response_model=ReplyResponse)
async def reply(body: ReplyRequest) -> ReplyResponse:
    return ReplyResponse.model_validate(
        reply_manager.handle(
        conversation_id=body.conversation_id,
        merchant_id=body.merchant_id,
        customer_id=body.customer_id,
        message=body.message,
        received_at=body.received_at,
        turn_number=body.turn_number,
        )
    )


@app.post("/v1/teardown")
async def teardown() -> dict:
    if not settings.enable_teardown:
        raise HTTPException(status_code=404, detail="teardown disabled")
    store.clear()
    return {"cleared": True, "cleared_at": utc_now_iso()}
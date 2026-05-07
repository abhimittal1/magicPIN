from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.composer import OutreachEngine
from app.config import get_settings
from app.evidence import FactPicker
from app.llm_client import LLMWriter
from app.planner import StrategyEngine
from app.ranker import ActionPrioritizer
from app.reply_classifier import IntentRouter
from app.reply_manager import DialogHandler
from app.resolver import SceneLoader
from app.schemas import ContextPushRequest, ContextPushResponse, HealthzResponse, MetadataResponse, ReplyRequest, ReplyResponse, TickAction, TickRequest, TickResponse
from app.store import AgentMemory, utc_now_iso
from app.validator import OutputGuard


settings = get_settings()
store = AgentMemory()
resolver = SceneLoader(store)
wording_service = LLMWriter(settings)
compose_service = OutreachEngine(
    planner=StrategyEngine(),
    evidence_selector=FactPicker(),
    wording_service=wording_service,
    validator=OutputGuard(),
)
ranker = ActionPrioritizer()
reply_manager = DialogHandler(store=store, resolver=resolver, classifier=IntentRouter(), settings=settings, wording_service=wording_service)

app = FastAPI(title="magicpin Challenge Bot")


@app.get("/v1/healthz", response_model=HealthzResponse)
async def healthz() -> HealthzResponse:
    uptime = int((datetime.now(store.started_at.tzinfo) - store.started_at).total_seconds())
    return HealthzResponse(status="ok", uptime_seconds=uptime, contexts_loaded=store.tally())


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
    result = store.accept(body.scope, body.context_id, body.version, body.payload)
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
        resolved = resolver.load_for_trigger(trigger_id)
        if resolved is None:
            continue
        suppression_key = resolved.trigger.get("suppression_key")
        if store.is_suppressed(suppression_key):
            continue
        plan = compose_service.strategize(resolved)
        score = ranker.rank(resolved, plan)
        candidates.append((score, trigger_id))

    actions: list[TickAction] = []
    effective_limit = min(max(settings.max_actions_per_tick, len(candidates)), 20)
    for _, trigger_id in sorted(candidates, key=lambda item: item[0], reverse=True)[:effective_limit]:
        resolved = resolver.load_for_trigger(trigger_id)
        if resolved is None:
            continue
        composed = compose_service.draft(resolved)
        conversation_id = f"conv_{uuid4().hex[:12]}"
        record = store.open_thread(
            conversation_id=conversation_id,
            merchant_id=resolved.trigger.get("merchant_id"),
            customer_id=resolved.trigger.get("customer_id"),
            trigger_id=trigger_id,
            send_as=composed.send_as,
            suppression_key=composed.suppression_key,
            prompt_version=settings.prompt_version,
        )
        store.append_entry(conversation_id, from_role="bot", message=composed.body, ts=utc_now_iso(), action="send")
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
        reply_manager.process(
        conversation_id=body.conversation_id,
        merchant_id=body.merchant_id,
        customer_id=body.customer_id,
        from_role=body.from_role,
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

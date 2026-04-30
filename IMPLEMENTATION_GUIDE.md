# Implementation Guide

This file is the build-and-verify map for the challenge bot. It matches the code now present in the repo and is meant to be followed step by step.

## Architecture

The bot is split into two layers:

1. A reusable composition core for `compose(category, merchant, trigger, customer?)`
2. A FastAPI wrapper that exposes the challenge endpoints under `/v1/*`

The flow is:

`context store -> resolver -> planner -> evidence selector -> LangChain/OpenAI wording -> validator -> endpoint response`

## Environment

Create `.env` from `.env.example` and fill these first:

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `TEAM_NAME`
- `TEAM_MEMBERS`
- `CONTACT_EMAIL`
- `BOT_VERSION`
- `SUBMITTED_AT`

The remaining values have sensible defaults for local work.

## Dependencies

Main runtime libraries:

- `fastapi`
- `uvicorn`
- `pydantic`
- `python-dotenv`
- `langchain`
- `langchain-openai`
- `openai`

Verification libraries:

- `pytest`
- `httpx`

## Module map

- `app/config.py`: loads `.env` and exposes cached settings
- `app/store.py`: versioned context storage, suppression keys, and conversation records
- `app/resolver.py`: merges category, merchant, trigger, and optional customer into one resolved object
- `app/planner.py`: determines trigger family, send-as, CTA, template name, and risk flags
- `app/evidence.py`: selects only allowed facts using the required precedence rule
- `app/voices.py`: derives salutation, language hints, and tone profile
- `app/llm_client.py`: uses `ChatOpenAI` through LangChain structured output for wording, with deterministic fallback if no API key or model failure
- `app/validator.py`: blocks unsupported numbers, taboo words, wrong send-as, repeated bodies, and invalid offer references
- `app/ranker.py`: ranks candidate triggers before expensive wording
- `app/reply_classifier.py`: heuristic-first reply classification
- `app/reply_manager.py`: follow-up actions for `/v1/reply`
- `app/main.py`: endpoint implementation and service wiring
- `bot.py`: pure compose entrypoint for one-shot generation and submission building
- `conversation_handlers.py`: optional multi-turn wrapper

## Endpoint contract

### `POST /v1/context`

Input:

```json
{
  "scope": "category",
  "context_id": "dentists",
  "version": 1,
  "payload": {"slug": "dentists"},
  "delivered_at": "2026-04-29T00:00:00Z"
}
```

Behavior:

- stores the payload by `(scope, context_id)`
- rejects same-or-lower version as `stale_version`
- never calls the LLM

### `GET /v1/healthz`

Output:

```json
{
  "status": "ok",
  "uptime_seconds": 10,
  "contexts_loaded": {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
}
```

### `GET /v1/metadata`

Returns team info and model metadata from `.env`.

### `POST /v1/tick`

Input:

```json
{
  "now": "2026-04-29T00:00:00Z",
  "available_triggers": ["trg_001_research_digest_dentists"]
}
```

Behavior:

- resolves each trigger from store state
- ranks it before wording
- skips expired or suppressed triggers
- returns at most `MAX_ACTIONS_PER_TICK`

### `POST /v1/reply`

Input:

```json
{
  "conversation_id": "conv_123",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Yes, go ahead",
  "received_at": "2026-04-29T00:00:00Z",
  "turn_number": 2
}
```

Behavior:

- classifies the reply without using the LLM first
- handles auto-replies, opt-outs, busy/later, off-topic, questions, and explicit commits
- returns exactly one of `send`, `wait`, or `end`

### `POST /v1/teardown`

Optional local reset endpoint. Controlled by `ENABLE_TEARDOWN`.

## Verification sequence

1. Install dependencies.
2. Run `python -m compileall app bot.py conversation_handlers.py`.
3. Run `pytest tests/test_contract.py`.
4. Start the server: `uvicorn app.main:app --host 0.0.0.0 --port 8080`.
5. Point `judge_simulator.py` to `http://localhost:8080` and run the warmup and replay smoke checks.
6. Run `python scripts/evaluate_expanded.py` to inspect the 30 canonical expanded pairs.
7. Run `python scripts/generate_submission.py` to create `submission.jsonl`.

## What is intentionally conservative in this first implementation

- Sparse placeholder triggers fall back to safer phrasing instead of speculative detail.
- Reply handling is heuristic-first and lightweight.
- The validator is strict on unsupported numbers and offer references.
- The wording layer can run without an API key through deterministic fallback, which keeps local verification stable.

## Next implementation targets

1. Improve active-planning drafts so they generate richer artifacts without inventing unsupported facts.
2. Make the reply manager reuse prior trigger evidence more deeply during follow-up.
3. Add a stronger offline evaluator aligned to the five rubric dimensions.
4. Add more tests around placeholder-trigger and category-mismatch cases from `expanded/test_pairs.json`.
# magicpin Challenge Bot

A stateful Merchant AI Assistant service. Stores category / merchant / customer / trigger context pushed by the judge, decides when to proactively message on `/v1/tick`, and continues conversations intelligently on `/v1/reply`.

Core design: deterministic planner first → evidence selection → LLM wording → validation pipeline.

---

## Quick start

```powershell
# 1. Activate the virtual environment (Windows)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies (first time only)
pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env
# Edit .env — set OPENAI_API_KEY and your team details

# 4. Start the server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8081

# 5. Verify it is up
# GET http://localhost:8081/v1/healthz  →  {"status": "ok", ...}
```

---

## Environment variables

All settings are read from `.env`. Copy `.env.example` to `.env` to get started.

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | **Yes** | — | OpenAI key — bot falls back to deterministic templates without it |
| `OPENAI_MODEL` | No | `gpt-4.1-mini` | Model name |
| `OPENAI_TEMPERATURE` | No | `0` | Generation temperature |
| `OPENAI_TIMEOUT_SECONDS` | No | `20` | Per-request LLM timeout |
| `TEAM_NAME` | No | `Your Team` | Returned by `/v1/metadata` |
| `TEAM_MEMBERS` | No | `Alice` | Comma-separated names |
| `CONTACT_EMAIL` | No | `team@example.com` | Returned by `/v1/metadata` |
| `BOT_VERSION` | No | `0.1.0` | Returned by `/v1/metadata` |
| `PORT` | No | `8080` | Server port |
| `ENABLE_TEARDOWN` | No | `true` | Enable `POST /v1/teardown` for test resets |
| `MAX_ACTIONS_PER_TICK` | No | `1` | Max proactive messages returned per tick |
| `DEFAULT_BUSY_WAIT_SECONDS` | No | `1800` | Wait time returned on busy signal |

---

## Running tests

```powershell
# Unit + contract tests (18 tests, no server needed)
.\.venv\Scripts\python.exe -m pytest tests/ -q

# Judge simulator (server must be running on port 8081)
.\.venv\Scripts\python.exe judge_simulator.py

# Generate submission.jsonl from the 30 expanded test pairs
.\.venv\Scripts\python.exe scripts\generate_submission.py
# Expected: Wrote 30 lines to submission.jsonl

# Expanded evaluation — score breakdown per pair
.\.venv\Scripts\python.exe scripts\evaluate_expanded.py
```

---

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/context` | Push category / merchant / customer / trigger context |
| `POST` | `/v1/tick` | Generate proactive messages for available triggers |
| `POST` | `/v1/reply` | Send an inbound message, get the next bot action |
| `GET` | `/v1/healthz` | Liveness check + context counts |
| `GET` | `/v1/metadata` | Team / model info |
| `POST` | `/v1/teardown` | Reset all in-memory state (test use only) |

### `/v1/context` response codes

| HTTP status | `reason` field | Meaning |
|---|---|---|
| `200` | — | `accepted=true`, stored |
| `409` | `same_version_conflict` | Same version pushed with a different payload |
| `409` | `stale_version` | Older version than what is already stored |

### `/v1/reply` action values

| `action` | Meaning |
|---|---|
| `send` | Bot sends a reply — `body` is populated |
| `wait` | Bot is waiting — `wait_seconds` is set |
| `end` | Conversation is closing — no further turns |

---

## Architecture

```
Judge → POST /v1/context  → AgentMemory (versioned store)
      → POST /v1/tick     → SceneLoader → StrategyEngine → FactPicker
                                        → LLMWriter → OutputGuard → TickAction[]
      → POST /v1/reply    → IntentRouter (fast-path: auto-reply / hostile / busy)
                                        → LLMWriter.classify_and_reply → OutputGuard
```

| Module | Role |
|---|---|
| `app/main.py` | FastAPI endpoints, service wiring |
| `app/store.py` | In-memory versioned context store + conversation state |
| `app/resolver.py` | Assembles category + merchant + trigger + customer into `AssembledScene` |
| `app/planner.py` | Maps trigger kind → family via `TRIGGER_DISPATCH` dict, builds `SendStrategy` |
| `app/evidence.py` | Picks concrete facts from context for use as message anchors |
| `app/composer.py` | Orchestrates planner → evidence → wording → validation |
| `app/llm_client.py` | LangChain + OpenAI wording; falls back to templates when no key |
| `app/validator.py` | `_COMPOSE_CHECKERS` pipeline — catches hallucinations and contract violations |
| `app/reply_classifier.py` | `SIGNAL_REGISTRY`-driven fast-path intent scanner |
| `app/reply_manager.py` | Full reply state machine — routes to end / wait / send |
| `app/ranker.py` | Scores triggers for prioritisation inside tick |
| `app/voices.py` | Category + language voice settings |
| `app/schemas.py` | Pydantic request / response models |
| `app/config.py` | Settings loaded from `.env` |

---

## Scripts

| Script | What it does |
|---|---|
| `scripts/generate_submission.py` | Runs all 30 test pairs, writes `submission.jsonl` |
| `scripts/evaluate_expanded.py` | Expanded evaluation preview — score breakdown per pair |
| `scripts/analyze_eval.py` | Analyses an existing `expanded-evaluation.jsonl` file |

---

## Manual test playbook

See `test.md` for the full Postman-compatible request sequence covering:
- Context contract checks (idempotency, same-version conflict, stale version)
- All 18+ trigger kinds across 6 core families
- `/v1/reply` flows: commit, busy, auto-reply, hostile, off-topic
- Customer-facing message checks

Base URL for manual tests: `http://localhost:8081`

---

## Note on judge_simulator.py

`judge_simulator.py` runs the seed dataset only. For the real 30-pair canonical set use `scripts/evaluate_expanded.py`.

The simulator reads your API key from the `OPENAI_API_KEY` environment variable (set in `.env`). Do not hardcode keys in source files.
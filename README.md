# magicpin Challenge Bot

This repo now contains a working FastAPI scaffold for the magicpin merchant-assistant challenge. The core design is deterministic planning first, GPT wording second, and validation after generation.

## Quick start

1. Create or activate the existing virtual environment.
2. Install dependencies from `requirements.txt`.
3. Copy `.env.example` to `.env` and fill in `OPENAI_API_KEY`, team metadata, and optional model overrides.
4. Start the API with `uvicorn app.main:app --host 0.0.0.0 --port 8080`.
5. Run contract checks with `pytest tests/test_contract.py`.
6. Run the provided smoke harness with `python judge_simulator.py`.

## Main modules

- `app/main.py`: FastAPI endpoints and service wiring
- `app/store.py`: in-memory versioned context store and conversation state
- `app/resolver.py`: category/merchant/trigger/customer resolution and flags
- `app/planner.py`: deterministic trigger-family planner
- `app/evidence.py`: evidence selection with strict context precedence
- `app/llm_client.py`: LangChain + OpenAI wording layer with deterministic fallback
- `app/validator.py`: hallucination and contract checks
- `app/reply_manager.py`: reply state machine for auto-replies, opt-outs, and action transitions
- `bot.py`: challenge-facing `compose()` entrypoint
- `conversation_handlers.py`: optional `respond()` entrypoint

## Scripts

- `python scripts/generate_submission.py`: generate `submission.jsonl` from `expanded/test_pairs.json`
- `python scripts/evaluate_expanded.py`: generate an expanded evaluation preview across the 30 canonical pairs

## Important note

`judge_simulator.py` only loads the seed dataset, not the expanded canonical set. Use `scripts/evaluate_expanded.py` for the real edge cases.
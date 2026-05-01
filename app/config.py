from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env", override=False)
if not os.getenv("OPENAI_API_KEY"):
    load_dotenv(ROOT_DIR / ".env.example", override=False)


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


def _get_csv(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def _is_placeholder_api_key(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return True
    return any(token in normalized for token in ["sk-your-", "your_openai_api_key", "replace_me", "here"])


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    openai_temperature: float
    openai_timeout_seconds: int
    team_name: str
    team_members: list[str]
    contact_email: str
    bot_version: str
    submitted_at: str
    dataset_seed_dir: str
    dataset_expanded_dir: str
    test_pairs_path: str
    host: str
    port: int
    log_level: str
    enable_teardown: bool
    max_actions_per_tick: int
    default_busy_wait_seconds: int
    default_auto_reply_wait_seconds: int
    prompt_version: str

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key) and not _is_placeholder_api_key(self.openai_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        openai_temperature=_get_float("OPENAI_TEMPERATURE", 0.0),
        openai_timeout_seconds=_get_int("OPENAI_TIMEOUT_SECONDS", 20),
        team_name=os.getenv("TEAM_NAME", "Your Team"),
        team_members=_get_csv("TEAM_MEMBERS", ["Alice"]),
        contact_email=os.getenv("CONTACT_EMAIL", "team@example.com"),
        bot_version=os.getenv("BOT_VERSION", "0.1.0"),
        submitted_at=os.getenv("SUBMITTED_AT", "2026-04-29T00:00:00Z"),
        dataset_seed_dir=os.getenv("DATASET_SEED_DIR", "./dataset"),
        dataset_expanded_dir=os.getenv("DATASET_EXPANDED_DIR", "./expanded"),
        test_pairs_path=os.getenv("TEST_PAIRS_PATH", "./expanded/test_pairs.json"),
        host=os.getenv("HOST", "0.0.0.0"),
        port=_get_int("PORT", 8080),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        enable_teardown=_get_bool("ENABLE_TEARDOWN", True),
        max_actions_per_tick=_get_int("MAX_ACTIONS_PER_TICK", 1),
        default_busy_wait_seconds=_get_int("DEFAULT_BUSY_WAIT_SECONDS", 1800),
        default_auto_reply_wait_seconds=_get_int("DEFAULT_AUTO_REPLY_WAIT_SECONDS", 14400),
        prompt_version=os.getenv("PROMPT_VERSION", "composer_v1"),
    )
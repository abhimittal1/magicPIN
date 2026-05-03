from __future__ import annotations

import json
from pathlib import Path
import os

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app, store
from app.store import utc_now_iso


client = TestClient(app)
REPO_ROOT = Path(__file__).resolve().parents[1]


def setup_function() -> None:
    store.clear()


def test_placeholder_api_key_disables_llm(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-your-openai-key-here")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.llm_enabled is False
    finally:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        get_settings.cache_clear()


def test_healthz_empty() -> None:
    response = client.get("/v1/healthz")
    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["contexts_loaded"] == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}


def test_context_versioning() -> None:
    body = {
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": {"slug": "dentists"},
        "delivered_at": utc_now_iso(),
    }
    first = client.post("/v1/context", json=body)
    second = client.post("/v1/context", json=body)
    third = client.post("/v1/context", json={**body, "version": 2})
    fourth = client.post("/v1/context", json=body)
    assert first.status_code == 200
    assert first.json()["accepted"] is True
    assert second.status_code == 200
    assert second.json()["accepted"] is True
    assert third.status_code == 200
    assert third.json()["accepted"] is True
    assert fourth.status_code == 409
    assert fourth.json()["accepted"] is False
    assert fourth.json()["reason"] == "stale_version"
    assert fourth.json()["current_version"] == 2
    assert "version 2 is already stored" in fourth.json()["details"]


def test_context_same_version_payload_conflict_rejected() -> None:
    body = {
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": {"slug": "dentists"},
        "delivered_at": utc_now_iso(),
    }

    first = client.post("/v1/context", json=body)
    second = client.post("/v1/context", json={**body, "payload": {"slug": "dentists", "display_name": "Dentists"}})

    assert first.status_code == 200
    assert first.json()["accepted"] is True
    assert second.status_code == 409
    assert second.json()["accepted"] is False
    assert second.json()["reason"] == "same_version_conflict"
    assert second.json()["current_version"] == 1
    assert "stored payload for that version is different" in second.json()["details"]


def test_context_real_dentists_payload_replay_is_idempotent() -> None:
    dentists = json.loads((REPO_ROOT / "dataset" / "categories" / "dentists.json").read_text(encoding="utf-8"))
    body = {
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": dentists,
        "delivered_at": utc_now_iso(),
    }

    first = client.post("/v1/context", json=body)
    second = client.post("/v1/context", json=body)

    assert first.status_code == 200
    assert first.json()["accepted"] is True
    assert second.status_code == 200
    assert second.json()["accepted"] is True


def test_tick_composes_seed_message() -> None:
    category = {
        "slug": "dentists",
        "voice": {"tone": "peer_clinical", "register": "respectful_collegial", "vocab_taboo": ["guaranteed"]},
        "digest": [{"id": "d_test", "title": "3-month fluoride recall improves outcomes", "source": "JIDA Oct 2026, p.14", "summary": "Useful for high-risk adults."}],
        "peer_stats": {"avg_ctr": 0.03},
    }
    merchant = {
        "merchant_id": "m_test",
        "category_slug": "dentists",
        "identity": {"name": "Dr. Meera's Dental Clinic", "owner_first_name": "Dr. Meera", "locality": "Lajpat Nagar", "languages": ["en", "hi"]},
        "subscription": {"status": "active", "days_remaining": 82},
        "performance": {"views": 2410, "calls": 18, "ctr": 0.021},
        "offers": [{"title": "Dental Cleaning @ ₹299", "status": "active"}],
        "signals": ["high_risk_adult_cohort"],
        "conversation_history": [],
        "customer_aggregate": {"high_risk_adult_count": 124},
    }
    trigger = {
        "id": "trg_test",
        "scope": "merchant",
        "kind": "research_digest",
        "source": "external",
        "merchant_id": "m_test",
        "customer_id": None,
        "payload": {"category": "dentists", "top_item_id": "d_test"},
        "urgency": 2,
        "suppression_key": "research:test",
        "expires_at": "2026-12-31T00:00:00Z",
    }

    client.post("/v1/context", json={"scope": "category", "context_id": "dentists", "version": 1, "payload": category, "delivered_at": utc_now_iso()})
    client.post("/v1/context", json={"scope": "merchant", "context_id": "m_test", "version": 1, "payload": merchant, "delivered_at": utc_now_iso()})
    client.post("/v1/context", json={"scope": "trigger", "context_id": "trg_test", "version": 1, "payload": trigger, "delivered_at": utc_now_iso()})

    response = client.post("/v1/tick", json={"now": utc_now_iso(), "available_triggers": ["trg_test"]})
    payload = response.json()
    assert response.status_code == 200
    assert len(payload["actions"]) == 1
    assert payload["actions"][0]["trigger_id"] == "trg_test"
    assert payload["actions"][0]["send_as"] == "vera"
    assert payload["actions"][0]["body"]


def test_tick_does_not_drop_judge_supplied_trigger_for_past_expires_at() -> None:
    category = {
        "slug": "restaurants",
        "voice": {"tone": "operator", "register": "practical", "vocab_taboo": ["guaranteed"]},
        "peer_stats": {"avg_ctr": 0.03},
    }
    merchant = {
        "merchant_id": "m_ipl",
        "category_slug": "restaurants",
        "identity": {"name": "Pizza Junction", "owner_first_name": "Rahul", "locality": "Delhi", "languages": ["en", "hi"]},
        "subscription": {"status": "active", "days_remaining": 82},
        "performance": {"views": 2410, "calls": 18, "ctr": 0.021},
        "offers": [{"title": "BOGO Pizza", "status": "active"}],
        "signals": ["match_day_demand"],
        "conversation_history": [],
        "customer_aggregate": {},
    }
    trigger = {
        "id": "trg_ipl",
        "scope": "merchant",
        "kind": "ipl_match_today",
        "source": "external",
        "merchant_id": "m_ipl",
        "customer_id": None,
        "payload": {"match": "DC vs MI", "venue": "Arun Jaitley Stadium", "is_weeknight": False},
        "urgency": 3,
        "suppression_key": "ipl:m_ipl:test",
        "expires_at": "2026-04-26T23:59:59+05:30",
    }

    client.post("/v1/context", json={"scope": "category", "context_id": "restaurants", "version": 1, "payload": category, "delivered_at": utc_now_iso()})
    client.post("/v1/context", json={"scope": "merchant", "context_id": "m_ipl", "version": 1, "payload": merchant, "delivered_at": utc_now_iso()})
    client.post("/v1/context", json={"scope": "trigger", "context_id": "trg_ipl", "version": 1, "payload": trigger, "delivered_at": utc_now_iso()})

    response = client.post("/v1/tick", json={"now": "2026-05-03T10:00:00Z", "available_triggers": ["trg_ipl"]})
    payload = response.json()

    assert response.status_code == 200
    assert len(payload["actions"]) == 1
    assert payload["actions"][0]["trigger_id"] == "trg_ipl"
    assert payload["actions"][0]["body"]


def test_reply_stop_ends() -> None:
    response = client.post(
        "/v1/reply",
        json={
            "conversation_id": "conv_stop",
            "merchant_id": "m_test",
            "customer_id": None,
            "from_role": "merchant",
            "message": "Stop messaging me.",
            "received_at": utc_now_iso(),
            "turn_number": 2,
        },
    )
    assert response.status_code == 200
    assert response.json()["action"] == "end"
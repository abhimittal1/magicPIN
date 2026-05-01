from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app, compose_service, resolver, settings, store
from app.evidence import EvidenceFact
from app.schemas import LLMReplyDecision
from app.schemas import ComposedMessage, MessagePlan, ResolvedContext
from app.store import utc_now_iso
from app.validator import MessageValidator


client = TestClient(app)


def setup_function() -> None:
    store.clear()


def _seed_context(scope: str, context_id: str, payload: dict) -> None:
    result = store.upsert_context(scope, context_id, 1, payload)
    assert result.accepted is True


def _seed_action_mode_contexts() -> None:
    _seed_context(
        "category",
        "dentists",
        {
            "slug": "dentists",
            "voice": {"tone": "peer_clinical", "register": "respectful_collegial", "vocab_taboo": ["guaranteed"]},
            "digest": [
                {
                    "id": "d_action",
                    "title": "3-month fluoride recall improves outcomes",
                    "source": "JIDA Oct 2026, p.14",
                    "summary": "Useful for high-risk adults.",
                }
            ],
            "peer_stats": {"avg_ctr": 0.03},
        },
    )
    _seed_context(
        "merchant",
        "m_action",
        {
            "merchant_id": "m_action",
            "category_slug": "dentists",
            "identity": {"name": "Dr. Meera's Dental Clinic", "owner_first_name": "Dr. Meera", "locality": "Lajpat Nagar", "languages": ["en", "hi"]},
            "subscription": {"status": "active", "days_remaining": 82},
            "performance": {"views": 2410, "calls": 18, "ctr": 0.021},
            "offers": [{"title": "Dental Cleaning @ ₹299", "status": "active"}],
            "signals": ["high_risk_adult_cohort"],
            "conversation_history": [],
            "customer_aggregate": {"high_risk_adult_count": 124},
        },
    )
    _seed_context(
        "trigger",
        "trg_action",
        {
            "id": "trg_action",
            "scope": "merchant",
            "kind": "research_digest",
            "source": "external",
            "merchant_id": "m_action",
            "customer_id": None,
            "payload": {"category": "dentists", "top_item_id": "d_action"},
            "urgency": 2,
            "suppression_key": "research:action",
            "expires_at": "2026-12-31T00:00:00Z",
        },
    )


def _seed_gbp_contexts() -> None:
    _seed_context(
        "category",
        "pharmacies",
        {
            "slug": "pharmacies",
            "voice": {"tone": "clear_helpful", "register": "peer", "vocab_taboo": ["guaranteed"]},
            "peer_stats": {"avg_ctr": 0.04, "avg_review_count": 88},
            "digest": [],
        },
    )
    _seed_context(
        "merchant",
        "m_gbp",
        {
            "merchant_id": "m_gbp",
            "category_slug": "pharmacies",
            "identity": {"name": "Sunrise Medicos", "owner_first_name": "Vikas", "locality": "Gomti Nagar", "languages": ["en", "hi"]},
            "subscription": {"status": "active", "days_remaining": 21},
            "performance": {"views": 4200, "calls": 46, "ctr": 0.031},
            "offers": [],
            "signals": [],
            "conversation_history": [],
            "customer_aggregate": {},
        },
    )
    _seed_context(
        "trigger",
        "trg_gbp",
        {
            "id": "trg_gbp",
            "scope": "merchant",
            "kind": "gbp_unverified",
            "source": "internal",
            "merchant_id": "m_gbp",
            "customer_id": None,
            "payload": {"verified": False, "verification_path": "postcard_or_phone_call", "estimated_uplift_pct": 0.3},
            "urgency": 3,
            "suppression_key": "gbp:m_gbp",
            "expires_at": "2026-06-30T00:00:00Z",
        },
    )


def _seed_customer_sparse_contexts() -> None:
    _seed_context(
        "category",
        "salons",
        {
            "slug": "salons",
            "voice": {
                "tone": "warm_practical",
                "register": "friendly_local",
                "vocab_taboo": ["guaranteed"],
                "vocab_allowed": ["hair spa", "keratin", "balayage"],
            },
            "peer_stats": {"avg_ctr": 0.04},
            "digest": [],
        },
    )
    _seed_context(
        "merchant",
        "m_sparse",
        {
            "merchant_id": "m_sparse",
            "category_slug": "salons",
            "identity": {"name": "Karim's Salon", "owner_first_name": "Karim", "locality": "Alambagh", "languages": ["en", "hi"]},
            "subscription": {"status": "active", "days_remaining": 40},
            "performance": {"views": 800, "calls": 14, "ctr": 0.031},
            "offers": [{"title": "Hair Spa @ ₹499", "status": "active"}],
            "signals": [],
            "conversation_history": [],
            "customer_aggregate": {},
        },
    )
    _seed_context(
        "customer",
        "c_sparse",
        {
            "customer_id": "c_sparse",
            "merchant_id": "m_sparse",
            "identity": {"name": "Aditya", "language_pref": "en"},
            "relationship": {},
            "state": "active",
            "preferences": {"reminder_opt_in": True},
        },
    )
    _seed_context(
        "trigger",
        "trg_sparse",
        {
            "id": "trg_sparse",
            "scope": "customer",
            "kind": "appointment_tomorrow",
            "source": "internal",
            "merchant_id": "m_sparse",
            "customer_id": "c_sparse",
            "payload": {"placeholder": True},
            "urgency": 3,
            "suppression_key": "appt:trg_sparse",
            "expires_at": "2026-06-30T00:00:00Z",
        },
    )


def test_reply_auto_reply_progression() -> None:
    conversation_id = "conv_auto"
    suppression_key = "auto:conv_auto"
    store.create_conversation(
        conversation_id=conversation_id,
        merchant_id="m_auto",
        customer_id=None,
        trigger_id=None,
        send_as="vera",
        suppression_key=suppression_key,
        prompt_version=settings.prompt_version,
    )
    body = {
        "conversation_id": conversation_id,
        "merchant_id": "m_auto",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Thank you for contacting us. Our team will respond shortly.",
        "received_at": utc_now_iso(),
        "turn_number": 2,
    }

    first = client.post("/v1/reply", json=body)

    record = store.get_conversation(conversation_id)
    assert first.status_code == 200
    assert record is not None
    assert first.json()["action"] == "end"
    assert record.ended is True
    assert store.is_suppressed(suppression_key) is True


def test_reply_commit_switches_to_action_mode() -> None:
    _seed_action_mode_contexts()
    conversation_id = "conv_commit"
    store.create_conversation(
        conversation_id=conversation_id,
        merchant_id="m_action",
        customer_id=None,
        trigger_id="trg_action",
        send_as="vera",
        suppression_key="research:action",
        prompt_version=settings.prompt_version,
    )

    response = client.post(
        "/v1/reply",
        json={
            "conversation_id": conversation_id,
            "merchant_id": "m_action",
            "customer_id": None,
            "from_role": "merchant",
            "message": "yes, go ahead",
            "received_at": utc_now_iso(),
            "turn_number": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "send"
    assert response.json()["body"]  # non-empty LLM reply


def test_reply_abusive_message_ends_and_suppresses() -> None:
    conversation_id = "conv_abusive"
    suppression_key = "abusive:conv_abusive"
    store.create_conversation(
        conversation_id=conversation_id,
        merchant_id="m_abusive",
        customer_id=None,
        trigger_id=None,
        send_as="vera",
        suppression_key=suppression_key,
        prompt_version=settings.prompt_version,
    )

    response = client.post(
        "/v1/reply",
        json={
            "conversation_id": conversation_id,
            "merchant_id": "m_abusive",
            "customer_id": None,
            "from_role": "merchant",
            "message": "This is useless spam.",
            "received_at": utc_now_iso(),
            "turn_number": 2,
        },
    )

    record = store.get_conversation(conversation_id)
    assert response.status_code == 200
    assert response.json()["action"] == "end"
    assert record is not None
    assert record.ended is True
    assert store.is_suppressed(suppression_key) is True


def test_reply_off_topic_redirects() -> None:
    _seed_action_mode_contexts()
    conversation_id = "conv_tax"
    store.create_conversation(
        conversation_id=conversation_id,
        merchant_id="m_action",
        customer_id=None,
        trigger_id="trg_action",
        send_as="vera",
        suppression_key="research:tax",
        prompt_version=settings.prompt_version,
    )
    response = client.post(
        "/v1/reply",
        json={
            "conversation_id": conversation_id,
            "merchant_id": "m_action",
            "customer_id": None,
            "from_role": "merchant",
            "message": "Can you help with GST filing?",
            "received_at": utc_now_iso(),
            "turn_number": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "send"
    assert response.json()["cta"] == "open_ended"
    assert response.json()["body"]  # LLM generates the redirect body — just verify it's non-empty


def test_reply_busy_message_returns_wait() -> None:
    _seed_action_mode_contexts()
    conversation_id = "conv_busy"
    store.create_conversation(
        conversation_id=conversation_id,
        merchant_id="m_action",
        customer_id=None,
        trigger_id="trg_action",
        send_as="vera",
        suppression_key="research:busy",
        prompt_version=settings.prompt_version,
    )
    response = client.post(
        "/v1/reply",
        json={
            "conversation_id": conversation_id,
            "merchant_id": "m_action",
            "customer_id": None,
            "from_role": "merchant",
            "message": "I am busy right now, ping me later.",
            "received_at": utc_now_iso(),
            "turn_number": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "wait"
    assert response.json()["wait_seconds"] == settings.default_busy_wait_seconds
    assert response.json()["rationale"] == "busy_wait"


def test_reply_accountant_question_does_not_use_generic_question_fallback() -> None:
    _seed_action_mode_contexts()
    conversation_id = "conv_accountant"
    store.create_conversation(
        conversation_id=conversation_id,
        merchant_id="m_action",
        customer_id=None,
        trigger_id="trg_action",
        send_as="vera",
        suppression_key="research:accountant",
        prompt_version=settings.prompt_version,
    )

    response = client.post(
        "/v1/reply",
        json={
            "conversation_id": conversation_id,
            "merchant_id": "m_action",
            "customer_id": None,
            "from_role": "merchant",
            "message": "Can you recommend a good accountant?",
            "received_at": utc_now_iso(),
            "turn_number": 3,
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "send"
    assert response.json()["rationale"] != "question_fallback"
    assert "Good question" not in (response.json()["body"] or "")


def test_reply_repairs_generic_placeholder_after_commit(monkeypatch) -> None:
    _seed_action_mode_contexts()
    conversation_id = "conv_commit_repair"
    store.create_conversation(
        conversation_id=conversation_id,
        merchant_id="m_action",
        customer_id=None,
        trigger_id="trg_action",
        send_as="vera",
        suppression_key="research:commit_repair",
        prompt_version=settings.prompt_version,
    )

    def fake_classify_and_reply(*args, **kwargs):
        return {
            "action": "send",
            "body": "Let me look into that — give me a moment.",
            "rationale": "clarification_request",
            "wait_seconds": None,
        }

    monkeypatch.setattr("app.main.wording_service.classify_and_reply", fake_classify_and_reply)

    response = client.post(
        "/v1/reply",
        json={
            "conversation_id": conversation_id,
            "merchant_id": "m_action",
            "customer_id": None,
            "from_role": "merchant",
            "message": "Ok lets do it. Whats next?",
            "received_at": utc_now_iso(),
            "turn_number": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "send"
    body_lower = (response.json()["body"] or "").lower()
    assert "let me look into that" not in body_lower
    assert any(word in body_lower for word in ["draft", "next", "proceed", "confirm", "sending", "here"])


def test_compose_gbp_unverified_humanizes_account_message() -> None:
    _seed_gbp_contexts()
    resolved = resolver.resolve_trigger_id("trg_gbp")

    assert resolved is not None
    composed = compose_service.compose_resolved(resolved)

    assert composed.send_as == "vera"
    body_lower = composed.body.lower()
    assert "not verified" in body_lower or "verify nahi hua" in body_lower
    assert "postcard or phone call" in body_lower or ("postcard" in body_lower and "phone call" in body_lower)
    assert "30%" in composed.body
    assert "False" not in composed.body


def test_compose_customer_sparse_uses_safe_deterministic_reminder() -> None:
    _seed_customer_sparse_contexts()
    resolved = resolver.resolve_trigger_id("trg_sparse")

    assert resolved is not None
    composed = compose_service.compose_resolved(resolved)

    assert composed.send_as == "merchant_on_behalf"
    assert "appointment tomorrow" in composed.body
    assert "confirm or help with timing" in composed.body
    assert "balayage" not in composed.body.lower()
    assert "keratin" not in composed.body.lower()


def test_validator_allows_humanized_date_from_iso_fact() -> None:
    validator = MessageValidator()
    plan = MessagePlan(
        trigger_family="research",
        audience="merchant",
        send_as="vera",
        primary_goal="share one research update",
        cta_type="open_ended",
        template_name="vera_research_v1",
        evidence_facts=[
            EvidenceFact("digest_item_date", "2026-05-02T19:00:00+05:30", "trigger.digest"),
            EvidenceFact("digest_item_title", "IDA Delhi: Digital impressions", "trigger.digest"),
        ],
    )
    resolved = ResolvedContext(
        category={"voice": {"vocab_taboo": []}},
        merchant={"offers": []},
        trigger={"kind": "research_digest", "payload": {}},
        customer=None,
        flags={"active_offer_titles": []},
    )
    composed = ComposedMessage(
        body="Dr. Meera, IDA Delhi is hosting this on May 2, 2026 at 7pm.",
        cta="open_ended",
        send_as="vera",
        suppression_key="research:test",
        rationale="",
        template_name="vera_research_v1",
        template_params=[],
    )

    issues = validator.validate(composed, plan, resolved)

    assert not any(issue.startswith("unsupported_numbers:") for issue in issues)

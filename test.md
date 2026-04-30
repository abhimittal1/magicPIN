# Postman / curl Test Reference

**Base URL:** `http://localhost:8081`  
**Required header for all POST requests:** `Content-Type: application/json`  
**Server startup:** `python -m uvicorn app.main:app --host 0.0.0.0 --port 8081`

> **WARNING — always call `POST /v1/teardown` (Step 0) before pushing any contexts.**
> The server is in-memory. If it was warm from a previous judge run, `dataset/categories/dentists.json`
> is already loaded with its full payload (8 offers, 4 digest items). Pushing the trimmed test.md
> payload at the same `version: 1` gives a `409 same_version_conflict`. Teardown resets the store completely.

---

## Recommended test order

```
0. Teardown     → clears in-memory state, start fresh
1. Healthz      → confirm zero contexts loaded
2. Push context × 4  → category, merchant, customer, trigger
3. Healthz      → confirm contexts_loaded == {category:1, merchant:1, customer:1, trigger:1}
4. Tick         → get a TickAction back
5. Reply ×3     → merchant reply, customer reply, hostile opt-out
6. Conflict     → push same context at version 1 with a changed payload → expect 409
```

---

## 0. Reset state

**Teardown** — clears the in-memory store. Call this before each test run so you start from a clean slate.

```
POST /v1/teardown
```

No body required.

**Expected response `200`:**
```json
{
  "cleared": true,
  "cleared_at": "2026-05-01T10:00:00Z"
}
```

> Requires `ENABLE_TEARDOWN=true` in your `.env`. Returns `404` if disabled.

---

## 1. Health check

```
GET /v1/healthz
```

No body required.

**Expected response `200` (before any context pushes):**
```json
{
  "status": "ok",
  "uptime_seconds": 12,
  "contexts_loaded": {
    "category": 0,
    "merchant": 0,
    "customer": 0,
    "trigger": 0
  }
}
```

---

## 2. Metadata

```
GET /v1/metadata
```

No body required.

**Expected response `200`:**
```json
{
  "team_name": "Your Team",
  "team_members": ["Alice", "Bob"],
  "model": "gpt-4.1-mini",
  "approach": "...",
  "contact_email": "team@example.com",
  "version": "0.1.0",
  "submitted_at": "2026-04-29T00:00:00Z"
}
```

---

## 3. Push contexts

Push all four context types in this order: **category → merchant → customer → trigger**.

### 3a. Category context — Dentists

```
POST /v1/context
```

```json
{
  "scope": "category",
  "context_id": "dentists",
  "version": 1,
  "delivered_at": "2026-05-01T04:30:00Z",
  "payload": {
    "slug": "dentists",
    "display_name": "Dentists",
    "voice": {
      "tone": "peer_clinical",
      "register": "respectful_collegial",
      "code_mix": "hindi_english_natural",
      "vocab_allowed": ["fluoride varnish", "scaling", "caries", "occlusion", "bruxism", "endodontic", "periodontal", "implant", "aligner", "veneer", "OPG", "IOPA", "RCT", "CAD/CAM", "zirconia", "PFM"],
      "vocab_taboo": ["guaranteed", "100% safe", "completely cure", "miracle", "best in city", "doctor approved"],
      "salutation_examples": ["Dr. {first_name}", "Doc"]
    },
    "offer_catalog": [
      { "id": "den_001", "title": "Dental Cleaning @ ₹299", "value": "299", "audience": "new_user", "type": "service_at_price" },
      { "id": "den_002", "title": "Free Consultation", "value": "0", "audience": "new_user", "type": "free_service" },
      { "id": "den_003", "title": "Teeth Whitening @ ₹1,499", "value": "1499", "audience": "new_user", "type": "service_at_price" },
      { "id": "den_007", "title": "Pediatric Dental Checkup @ ₹199", "value": "199", "audience": "new_user", "type": "service_at_price" },
      { "id": "den_008", "title": "Annual Family Dental Plan @ ₹4,999", "value": "4999", "audience": "repeat_user", "type": "membership" }
    ],
    "peer_stats": {
      "scope": "metro_solo_practices_2026",
      "avg_rating": 4.4,
      "avg_review_count": 62,
      "avg_views_30d": 1820,
      "avg_calls_30d": 12,
      "avg_directions_30d": 38,
      "avg_ctr": 0.030,
      "avg_post_freq_days": 14,
      "retention_6mo_pct": 0.42
    },
    "digest": [
      {
        "id": "d_2026W17_jida_fluoride",
        "kind": "research",
        "title": "3-month fluoride varnish recall outperforms 6-month for high-risk adult caries",
        "source": "JIDA Oct 2026, p.14",
        "trial_n": 2100,
        "patient_segment": "high_risk_adults",
        "summary": "Multi-center Indian trial shows 38% lower caries recurrence with 3-month vs 6-month recall in adults with active decay history.",
        "actionable": "Reassess recall interval for adults flagged high-risk in your charting"
      },
      {
        "id": "d_2026W17_dci_radiograph",
        "kind": "compliance",
        "title": "DCI revised radiograph dose limits effective 2026-12-15",
        "source": "Dental Council of India circular 2026-11-04",
        "summary": "Maximum dose per IOPA exposure drops from 1.5 mSv to 1.0 mSv. E-speed film passes; D-speed does not. Digital RVG sensors unaffected.",
        "actionable": "Audit your X-ray setup before Dec 15"
      }
    ]
  }
}
```

**Expected response `200`:**
```json
{
  "accepted": true,
  "ack_id": "ack_...",
  "stored_at": "2026-05-01T...",
  "reason": null,
  "current_version": null,
  "details": null
}
```

---

### 3b. Merchant context — Dr. Meera (dentist, Delhi)

```
POST /v1/context
```

```json
{
  "scope": "merchant",
  "context_id": "m_001_drmeera_dentist_delhi",
  "version": 1,
  "delivered_at": "2026-05-01T04:30:00Z",
  "payload": {
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "category_slug": "dentists",
    "identity": {
      "name": "Dr. Meera's Dental Clinic",
      "city": "Delhi",
      "locality": "Lajpat Nagar",
      "place_id": "ChIJ_LAJPATNAGAR_DENTIST_001",
      "verified": true,
      "languages": ["en", "hi"],
      "owner_first_name": "Meera",
      "established_year": 2018
    },
    "subscription": {
      "status": "active",
      "plan": "Pro",
      "days_remaining": 82,
      "renewed_at": "2026-02-04"
    },
    "performance": {
      "window_days": 30,
      "views": 2410,
      "calls": 18,
      "directions": 45,
      "ctr": 0.021,
      "leads": 9,
      "delta_7d": { "views_pct": 0.18, "calls_pct": -0.05, "ctr_pct": 0.02 }
    },
    "offers": [
      { "id": "o_meera_001", "title": "Dental Cleaning @ ₹299", "status": "active", "started": "2026-03-01" },
      { "id": "o_meera_002", "title": "Deep Cleaning @ ₹499", "status": "expired", "ended": "2026-02-28" }
    ],
    "conversation_history": [
      { "ts": "2026-04-24T10:12:00Z", "from": "vera", "body": "Profile audit done — your photos are 8/10, description complete, but Google posts are stale (last post 22 days ago). Want me to draft 3 posts you can review?", "engagement": "merchant_replied" },
      { "ts": "2026-04-24T10:18:00Z", "from": "merchant", "body": "Yes please, focus on whitening and aligners", "engagement": "intent_action" }
    ],
    "customer_aggregate": {
      "total_unique_ytd": 540,
      "lapsed_180d_plus": 78,
      "retention_6mo_pct": 0.38,
      "high_risk_adult_count": 124
    },
    "signals": ["stale_posts:22d", "ctr_below_peer_median", "high_risk_adult_cohort", "engaged_in_last_48h"],
    "review_themes": [
      { "theme": "wait_time", "sentiment": "neg", "occurrences_30d": 3, "common_quote": "had to wait 30 min on Sunday afternoon" },
      { "theme": "doctor_manner", "sentiment": "pos", "occurrences_30d": 5, "common_quote": "Dr. Meera explains everything patiently" }
    ]
  }
}
```

**Expected response `200`:**
```json
{ "accepted": true, "ack_id": "ack_...", "stored_at": "...", "reason": null, "current_version": null, "details": null }
```

---

### 3c. Customer context — Priya (lapsed patient of Dr. Meera)

```
POST /v1/context
```

```json
{
  "scope": "customer",
  "context_id": "c_001_priya_for_m001",
  "version": 1,
  "delivered_at": "2026-05-01T04:30:00Z",
  "payload": {
    "customer_id": "c_001_priya_for_m001",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "identity": {
      "name": "Priya",
      "phone_redacted": "<phone>",
      "language_pref": "hi-en mix",
      "age_band": "25-35"
    },
    "relationship": {
      "first_visit": "2025-11-04",
      "last_visit": "2026-05-12",
      "visits_total": 4,
      "services_received": ["cleaning", "cleaning", "whitening", "cleaning"],
      "lifetime_value": 1696
    },
    "state": "lapsed_soft",
    "preferences": {
      "preferred_slots": "weekday_evening",
      "channel": "whatsapp",
      "reminder_opt_in": true
    },
    "consent": {
      "opted_in_at": "2025-11-04",
      "scope": ["recall_reminders", "appointment_reminders"]
    }
  }
}
```

**Expected response `200`:**
```json
{ "accepted": true, "ack_id": "ack_...", "stored_at": "...", "reason": null, "current_version": null, "details": null }
```

---

### 3d. Trigger context — Research digest for Dr. Meera

```
POST /v1/context
```

```json
{
  "scope": "trigger",
  "context_id": "trg_001_research_digest_dentists",
  "version": 1,
  "delivered_at": "2026-05-01T04:30:00Z",
  "payload": {
    "id": "trg_001_research_digest_dentists",
    "scope": "merchant",
    "kind": "research_digest",
    "source": "external",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": null,
    "payload": {
      "category": "dentists",
      "top_item_id": "d_2026W17_jida_fluoride"
    },
    "urgency": 2,
    "suppression_key": "research:dentists:2026-W17",
    "expires_at": "2026-05-03T00:00:00Z"
  }
}
```

**Expected response `200`:**
```json
{ "accepted": true, "ack_id": "ack_...", "stored_at": "...", "reason": null, "current_version": null, "details": null }
```

---

### 3e. Trigger context — Recall due for Priya (customer outreach trigger)

```
POST /v1/context
```

```json
{
  "scope": "trigger",
  "context_id": "trg_003_recall_due_priya",
  "version": 1,
  "delivered_at": "2026-05-01T04:30:00Z",
  "payload": {
    "id": "trg_003_recall_due_priya",
    "scope": "customer",
    "kind": "recall_due",
    "source": "internal",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": "c_001_priya_for_m001",
    "payload": {
      "service_due": "6_month_cleaning",
      "last_service_date": "2026-05-12",
      "due_date": "2026-11-12",
      "available_slots": [
        { "iso": "2026-11-05T18:00:00+05:30", "label": "Wed 5 Nov, 6pm" },
        { "iso": "2026-11-06T17:00:00+05:30", "label": "Thu 6 Nov, 5pm" }
      ]
    },
    "urgency": 3,
    "suppression_key": "recall:c_001_priya_for_m001:6mo",
    "expires_at": "2026-11-30T00:00:00Z"
  }
}
```

**Expected response `200`:**
```json
{ "accepted": true, "ack_id": "ack_...", "stored_at": "...", "reason": null, "current_version": null, "details": null }
```

---

### 3f. Health check after pushes (verify contexts loaded)

```
GET /v1/healthz
```

**Expected response `200`:**
```json
{
  "status": "ok",
  "uptime_seconds": 45,
  "contexts_loaded": {
    "category": 1,
    "merchant": 1,
    "customer": 1,
    "trigger": 2
  }
}
```

---

## 4. Tick — generate outbound messages

```
POST /v1/tick
```

```json
{
  "now": "2026-05-01T10:00:00+05:30",
  "available_triggers": [
    "trg_001_research_digest_dentists",
    "trg_003_recall_due_priya"
  ]
}
```

**Expected response `200`:**
```json
{
  "actions": [
    {
      "conversation_id": "conv_...",
      "merchant_id": "m_001_drmeera_dentist_delhi",
      "customer_id": null,
      "send_as": "vera",
      "trigger_id": "trg_001_research_digest_dentists",
      "template_name": "research_digest_v1",
      "template_params": ["Dr. Meera", "..."],
      "body": "Dr. Meera, interesting finding from JIDA ...",
      "cta": "Want me to update your recall protocol?",
      "suppression_key": "research:dentists:2026-W17",
      "rationale": "..."
    }
  ]
}
```

> **Note:** Copy the `conversation_id` from this response — you will need it for the `/v1/reply` calls below.

---

## 5. Reply — respond to an outbound message

> **Prerequisite:** Run step 4 first. Use the `conversation_id` from the tick response.

### 5a. Merchant replies positively (vera flow)

```
POST /v1/reply
```

```json
{
  "conversation_id": "conv_PASTE_FROM_TICK_RESPONSE",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Interesting! Yes, let's update the recall interval.",
  "received_at": "2026-05-01T10:05:00+05:30",
  "turn_number": 1
}
```

**Expected response `200`:**
```json
{
  "action": "send",
  "body": "...",
  "cta": "...",
  "wait_seconds": null,
  "rationale": "..."
}
```

---

### 5b. Merchant asks a question

```
POST /v1/reply
```

```json
{
  "conversation_id": "conv_PASTE_FROM_TICK_RESPONSE",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Which patients specifically should I target first?",
  "received_at": "2026-05-01T10:10:00+05:30",
  "turn_number": 2
}
```

**Expected response `200`:**
```json
{
  "action": "send",
  "body": "...",
  "cta": "...",
  "wait_seconds": null,
  "rationale": "..."
}
```

---

### 5c. Merchant goes off-topic

```
POST /v1/reply
```

```json
{
  "conversation_id": "conv_PASTE_FROM_TICK_RESPONSE",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Can you recommend a good accountant?",
  "received_at": "2026-05-01T10:15:00+05:30",
  "turn_number": 3
}
```

**Expected response `200`:**
```json
{
  "action": "send",
  "body": "That's outside my lane right now, but let's keep moving on what we have.",
  "cta": null,
  "wait_seconds": null,
  "rationale": "off_topic"
}
```

---

### 5d. Customer replies — Hinglish (merchant_on_behalf flow)

First trigger a customer tick or push the recall trigger, then use the customer `conversation_id`.

```
POST /v1/reply
```

```json
{
  "conversation_id": "conv_PASTE_FROM_CUSTOMER_TICK_RESPONSE",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": "c_001_priya_for_m001",
  "from_role": "customer",
  "message": "Haan, weekday evening theek rahega",
  "received_at": "2026-05-01T10:20:00+05:30",
  "turn_number": 1
}
```

**Expected response `200`:**
```json
{
  "action": "send",
  "body": "...",
  "cta": "...",
  "wait_seconds": null,
  "rationale": "..."
}
```

---

### 5e. Customer hostile / opt-out

```
POST /v1/reply
```

```json
{
  "conversation_id": "conv_PASTE_FROM_CUSTOMER_TICK_RESPONSE",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": "c_001_priya_for_m001",
  "from_role": "customer",
  "message": "Mujhe koi message mat bhejo, opt out karna hai",
  "received_at": "2026-05-01T10:25:00+05:30",
  "turn_number": 2
}
```

**Expected response `200`:**
```json
{
  "action": "end",
  "body": null,
  "cta": null,
  "wait_seconds": null,
  "rationale": "opt_out"
}
```

---

## 6. Conflict test — push same context with a changed payload

This verifies that the server correctly rejects a same-version conflict.

```
POST /v1/context
```

```json
{
  "scope": "merchant",
  "context_id": "m_001_drmeera_dentist_delhi",
  "version": 1,
  "delivered_at": "2026-05-01T11:00:00Z",
  "payload": {
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "category_slug": "dentists",
    "identity": {
      "name": "CHANGED NAME - should be rejected",
      "city": "Delhi",
      "locality": "Different Locality",
      "verified": true,
      "languages": ["en"],
      "owner_first_name": "Meera"
    }
  }
}
```

**Expected response `409`:**
```json
{
  "accepted": false,
  "ack_id": null,
  "stored_at": null,
  "reason": "same_version_conflict",
  "current_version": 1,
  "details": "version 1 already stored with a different payload"
}
```

---

## 7. Idempotency test — push exact same context again

This verifies that identical replays are accepted (judge runs the same warmup twice).

```
POST /v1/context
```

Use the exact same body as **step 3b** (same version, same payload).

**Expected response `200`:**
```json
{ "accepted": true, "ack_id": "ack_...", "stored_at": "...", "reason": null, "current_version": null, "details": null }
```

---

## Field reference

### `POST /v1/context` — request fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `scope` | `"category" \| "merchant" \| "customer" \| "trigger"` | yes | Determines how payload is indexed |
| `context_id` | string | yes | Unique ID for this context item |
| `version` | integer ≥ 1 | yes | Used for conflict detection |
| `payload` | object | yes | Free-form; shape depends on scope |
| `delivered_at` | ISO 8601 string | yes | e.g. `"2026-05-01T04:30:00Z"` |

### `POST /v1/tick` — request fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `now` | ISO 8601 string | yes | Current time, used for trigger expiry checks |
| `available_triggers` | string[] | yes | List of trigger `context_id`s the judge wants evaluated |

### `POST /v1/reply` — request fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `conversation_id` | string | yes | From a prior `/v1/tick` response |
| `merchant_id` | string \| null | yes* | Required when `from_role` is `"merchant"` |
| `customer_id` | string \| null | yes* | Required when `from_role` is `"customer"` |
| `from_role` | `"merchant" \| "customer"` | yes | Determines routing and tone |
| `message` | string | yes | The text the user sent |
| `received_at` | ISO 8601 string | yes | When the message was received |
| `turn_number` | integer | yes | 1-based turn counter for this conversation |

### `/v1/reply` — `action` values

| `action` | Meaning |
|---|---|
| `"send"` | Bot has a reply ready; use `body` + `cta` |
| `"wait"` | Bot is processing; retry after `wait_seconds` |
| `"end"` | Conversation over (opt-out or natural close) |

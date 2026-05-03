# magicpin Judge-Focused Test Playbook

This file is built to catch exactly the score leaks you reported:
- low Engagement Compulsion
- partial trigger coverage
- customer reply routing errors
- replay-flow regressions

Base URL: `http://localhost:8081`  
Required header: `Content-Type: application/json`  
Start server: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8081`

## A. Fast run order (recommended)

1. Teardown and health baseline
2. Context contract checks (idempotency/conflict/stale)
3. Trigger coverage sweep from expanded data (all kinds)
4. Core 6-family hit check
5. /v1/reply replay checks (auto-reply, commit, hostile, busy)
6. /v1/reply Engagement Compulsion checks with real prompts
7. Customer reply checks (merchant_on_behalf voice)

---

## B. Reset and baseline

Always start from clean in-memory state.

### B1. Teardown

`POST /v1/teardown`

Expected `200`:

```json
{
  "cleared": true,
  "cleared_at": "2026-05-03T10:00:00Z"
}
```

If teardown is disabled you should get `404` with `teardown disabled`.

### B2. Health

`GET /v1/healthz`

Expected `200` with empty counts:

```json
{
  "status": "ok",
  "contexts_loaded": {
    "category": 0,
    "merchant": 0,
    "customer": 0,
    "trigger": 0
  }
}
```

---

## C. Contract checks that affect judge stability

Use these before scoring checks so infra errors do not hide quality errors.

### C1. Same payload replay is idempotent

Push same `(scope, context_id, version, payload)` twice.

Expected:
- first push: `200 accepted=true`
- second identical push: `200 accepted=true`

### C2. Same version + changed payload conflicts

Push version `1`, then push version `1` again with changed payload.

Expected `409`:
- `accepted=false`
- `reason=same_version_conflict`

### C3. Older version after newer is stale

Push version `1`, then `2`, then `1` again.

Expected `409`:
- `accepted=false`
- `reason=stale_version`

---

## D. Full trigger coverage sweep (expanded folder)

You asked to cover all expanded cases. This section validates exactly that.

### D1. Canonical expanded coverage target

Source of truth:
- `expanded/test_pairs.json`
- `expanded/triggers/*.json`

Current canonical set:
- total pairs: `30`
- distinct trigger kinds in test pairs: `18`
- distinct trigger kinds present in expanded/triggers inventory: `26`

### D2. Trigger kind matrix (test_pairs coverage: all 18 must hit)

Each kind below appears in `expanded/test_pairs.json` and should produce at least one non-empty outbound message in expanded sweep output.

| Kind | Family | Example trigger_id from expanded set | Expected send_as |
|---|---|---|---|
| active_planning_intent | planning | trg_013_corporate_thali_planning | vera |
| customer_lapsed_soft | customer_followup | trg_071_customer_lapsed_soft_m_014_dr_asha_dentis | merchant_on_behalf |
| customer_lapsed_hard | customer_followup | trg_015_winback_rashmi | merchant_on_behalf |
| curious_ask_due | curiosity | trg_008_curious_ask_studio11 | vera |
| regulation_change | research | trg_002_compliance_dci_radiograph | vera |
| cde_opportunity | research | trg_022_cde_webinar_dentists | vera |
| research_digest | research | trg_001_research_digest_dentists | vera |
| festival_upcoming | event | trg_006_festival_diwali | vera |
| ipl_match_today | event | trg_010_ipl_match_delhi | vera |
| competitor_opened | event | trg_023_competitor_opened_dentist | vera |
| category_seasonal | event | trg_020_summer_demand_shift | vera |
| perf_dip | performance | trg_004_perf_dip_bharat | vera |
| perf_spike | performance | trg_024_perf_spike_zen | vera |
| milestone_reached | performance | trg_012_milestone_mylari | vera |
| gbp_unverified | account | trg_021_unverified_gbp_sunrise | vera |
| dormant_with_vera | account | trg_025_dormancy_glamour | vera |
| recall_due | customer_followup | trg_003_recall_due_priya | merchant_on_behalf |
| appointment_tomorrow | customer_followup or customer_sparse | trg_076_appointment_tomorrow_m_019_karim_salon_lu | merchant_on_behalf |
| chronic_refill_due | customer_followup | trg_019_chronic_refill_grandfather | merchant_on_behalf |

Kinds in expanded inventory but not currently in test_pairs (optional extra checks):
- supply_alert (`trg_018_supply_atorvastatin_recall`)
- renewal_due (`trg_005_renewal_due_bharat`)
- review_theme_emerged (`trg_011_review_theme_late_delivery`)
- seasonal_perf_dip (`trg_014_seasonal_acquisition_dip_powerhouse`)
- trial_followup (`trg_017_kids_yoga_trial_followup_karthik`)
- wedding_package_followup (`trg_007_bridal_followup_kavya`)
- winback_eligible (`trg_009_winback_glamour`)

### D3. One-command expanded generation check

Run:

```powershell
.\.venv\Scripts\python.exe scripts\generate_submission.py
```

Expected: `Wrote 30 lines to submission.jsonl`

### D4. Validate all kinds are hitting with non-empty message

Run this check (PowerShell multiline string supported):

```powershell
.\.venv\Scripts\python.exe -c "
import json
from pathlib import Path
from collections import defaultdict

pairs = json.loads(Path('expanded/test_pairs.json').read_text(encoding='utf-8'))['pairs']
rows = [json.loads(l) for l in Path('submission.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]

triggers = {}
for p in Path('expanded/triggers').glob('*.json'):
    t = json.loads(p.read_text(encoding='utf-8'))
    triggers[t.get('id') or p.stem] = t

row_by_test = {r['test_id']: r for r in rows}
stats = defaultdict(lambda: {'total': 0, 'hit': 0, 'empty': 0})

for pair in pairs:
    tid = pair['test_id']
    trig = triggers.get(pair['trigger_id'], {})
    kind = trig.get('kind', 'UNKNOWN')
    stats[kind]['total'] += 1
    row = row_by_test.get(tid)
    if row is None:
        continue
    body = (row.get('body') or '').strip()
    if body:
        stats[kind]['hit'] += 1
    else:
        stats[kind]['empty'] += 1

print('KIND COVERAGE')
for kind in sorted(stats):
    s = stats[kind]
    print(f'{kind:24} {s["hit"]}/{s["total"]} hit, empty={s["empty"]}')

missing = [k for k, s in stats.items() if s['hit'] == 0]
print('\nMISSING KINDS:', missing if missing else 'NONE')
"
```

Pass condition:
- `MISSING KINDS: NONE`
- no kind with `0/x hit`

---

## E. Core 6-family hit check (what judges often summarize)

Core proactive families:
- planning
- curiosity
- research
- event
- performance
- account

From expanded run, you should see at least one non-empty output tied to each family above.

Additional customer families to verify separately:
- customer_followup
- customer_sparse

---

## F. /v1/tick hit-vs-not-hit rules

For each trigger tested through `/v1/tick`, classify result using these rules:

Hit:
- action exists in `actions[]`
- `body` is non-empty
- `send_as` is correct for scope
- `trigger_id` matches requested trigger

Soft miss:
- action exists but body generic/no hook (quality leak)

Hard miss:
- trigger available but no action generated and no valid reason

Valid no-hit cases:
- trigger expired
- suppression key already suppressed
- trigger id not found
- trigger mismatched/filtered safely

---

## G. /v1/reply replay checks (flow correctness)

Use a real conversation_id produced by `/v1/tick`.

### G1. Auto-reply should end

Input message:
- `Thank you for contacting us. Our team will respond shortly.`

Expected:
- `action=end`
- `body=null` is expected for this deterministic end path

### G2. Commit should switch to action mode immediately

Input message:
- `Ok lets do it. Whats next?`

Expected:
- `action=send`
- body contains action language like `draft`, `next`, `proceed`, `confirm`, `sending`, or `here`
- body should not be generic stalling text like `let me look into that`

### G3. Off-topic should redirect

Input message:
- `Can you recommend a good accountant?`

Expected:
- `action=send`
- concise redirect back to in-scope growth/profile/outreach thread

### G4. Busy should wait

Input message:
- `I am busy right now, ping me later.`

Expected:
- `action=wait`
- `body=null` is expected for wait
- `wait_seconds` set
- `rationale=busy_wait`

Note:
- Treat busy and auto-reply as separate test branches. If you send a busy message first and get `action=wait`, do not continue that same branch with auto-reply text. Start a fresh branch or new conversation for auto-reply detection.

### G5. Hostile should end

Input message:
- `Stop messaging me. This is useless spam.`

Expected:
- `action=end`

---

## H. /v1/reply Engagement Compulsion suite (score-critical)

This section is the direct check for your low score dimension.

### H1. Pass/fail rubric for compulsion in reply body

For a reply to pass Engagement Compulsion, it should satisfy all:

1. Starts with a why-now hook in first sentence
2. Contains one concrete next action
3. Uses at least one specific anchor (number, date window, offer title, peer benchmark, named cohort)
4. Has a clear CTA or instruction
5. Avoids generic placeholders

Reject as weak if body is mostly:
- `Want me to draft ...?` with no factual hook
- vague hype with no concrete step
- generic support tone not tied to trigger context

### H2. Real-case prompt checks

Use these inbound messages after you have run tick on matching triggers.

Case A (performance dip thread):
- Merchant message: `Numbers look weak. What should I do this week?`
- Expected strong signals in reply: benchmark reference, specific fix in next 48h, concrete artifact offered

Case B (ipl event thread):
- Merchant message: `Should I push tonight offer for IPL?`
- Expected strong signals: counter-intuitive/impact framing, offer-linked advice, effort cap (`5 min`, `10 min`)

Case C (festival thread):
- Merchant message: `Diwali coming, whats best next step?`
- Expected strong signals: urgency window, competitor/loss framing, one actionable push

Case D (milestone thread):
- Merchant message: `We crossed target. What next?`
- Expected strong signals: immediate exploitation step, concrete channel action (post/broadcast), short effort cap

### H3. Quick quality score per reply (0-5)

Score one point for each criterion in H1 met.

- `0-2`: weak compulsion (likely score drop)
- `3`: acceptable
- `4-5`: strong compulsion

---

## I. Customer-facing reply checks (/v1/reply)

Use customer conversation_id from a customer-scope trigger such as `recall_due`.

### I1. Customer confirmation message

Request:

```json
{
  "conversation_id": "conv_from_customer_tick",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": "c_001_priya_for_m001",
  "from_role": "customer",
  "message": "Yes please book me for Wed 5 Nov, 6pm",
  "received_at": "2026-05-03T10:20:00+05:30",
  "turn_number": 1
}
```

Expected:
- `action=send`
- warm customer confirmation tone
- references slot/day/time if present
- no merchant analytics jargon (no ctr/views/calls)
- no Vera self-introduction

### I2. Customer opt-out

Input:
- `Mujhe koi message mat bhejo, opt out karna hai`

Expected:
- `action=end`

---

## J. Minimal API payload examples

### J1. Tick request

```json
{
  "now": "2026-05-03T10:00:00+05:30",
  "available_triggers": [
    "trg_001_research_digest_dentists",
    "trg_003_recall_due_priya"
  ]
}
```

### J2. Reply request fields

| Field | Type | Required |
|---|---|---|
| conversation_id | string | yes |
| merchant_id | string or null | yes |
| customer_id | string or null | yes |
| from_role | merchant or customer | yes |
| message | string | yes |
| received_at | ISO datetime | yes |
| turn_number | integer | yes |

### J3. Reply action meanings

| action | Meaning |
|---|---|
| send | reply body is provided |
| wait | bot asks system to wait and retry later |
| end | conversation should stop |

---

## K. Failure triage map (fast diagnosis)

If this fails, check this first:

- Missing trigger hits by kind: Section D3 and D4
- Core 6 families not all represented: Section E
- Replay behavior odd (`end/end/end` or no action mode switch): Section G
- Customer replies sound merchant-facing or generic: Section I
- Engagement Compulsion still low: Section H
- Unstable context pushes (409 surprises): Section C

This gives you one repeatable pre-submit runbook for both correctness and score quality.

---

## L. Direct Postman JSON Pack (Copy-Paste)

Use these exactly in order.

### L1. Reset

Method: `POST`  
Endpoint: `/v1/teardown`  
Body:

```json
{}
```

### L2. Health

Method: `GET`  
Endpoint: `/v1/healthz`

### L3. Push category context

Method: `POST`  
Endpoint: `/v1/context`  
Body:

```json
{
  "scope": "category",
  "context_id": "dentists",
  "version": 1,
  "delivered_at": "2026-05-03T10:00:00Z",
  "payload": {
    "slug": "dentists",
    "voice": {
      "tone": "peer_clinical",
      "register": "respectful_collegial",
      "vocab_taboo": ["guaranteed"]
    },
    "peer_stats": {
      "avg_ctr": 0.03
    },
    "digest": [
      {
        "id": "d_2026W17_jida_fluoride",
        "title": "3-month fluoride recall improves outcomes",
        "source": "JIDA Oct 2026, p.14",
        "summary": "Useful for high-risk adults."
      }
    ]
  }
}
```

### L4. Push merchant context

Method: `POST`  
Endpoint: `/v1/context`  
Body:

```json
{
  "scope": "merchant",
  "context_id": "m_001_drmeera_dentist_delhi",
  "version": 1,
  "delivered_at": "2026-05-03T10:00:10Z",
  "payload": {
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "category_slug": "dentists",
    "identity": {
      "name": "Dr. Meera's Dental Clinic",
      "owner_first_name": "Meera",
      "locality": "Lajpat Nagar",
      "languages": ["en", "hi"]
    },
    "subscription": {
      "status": "active",
      "days_remaining": 82
    },
    "performance": {
      "views": 2410,
      "calls": 18,
      "ctr": 0.021
    },
    "offers": [
      {
        "id": "o_meera_001",
        "title": "Dental Cleaning @ 299",
        "status": "active"
      }
    ],
    "signals": ["high_risk_adult_cohort"],
    "conversation_history": [],
    "customer_aggregate": {
      "high_risk_adult_count": 124
    }
  }
}
```

### L5. Push customer context

Method: `POST`  
Endpoint: `/v1/context`  
Body:

```json
{
  "scope": "customer",
  "context_id": "c_001_priya_for_m001",
  "version": 1,
  "delivered_at": "2026-05-03T10:00:20Z",
  "payload": {
    "customer_id": "c_001_priya_for_m001",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "identity": {
      "name": "Priya",
      "language_pref": "hi-en mix"
    },
    "relationship": {
      "last_visit": "2026-05-12",
      "visits_total": 4
    },
    "state": "active",
    "preferences": {
      "reminder_opt_in": true,
      "preferred_slots": ["weekday_evening"]
    }
  }
}
```

### L6. Push planning trigger

Method: `POST`  
Endpoint: `/v1/context`  
Body:

```json
{
  "scope": "trigger",
  "context_id": "trg_l_plan_m001",
  "version": 1,
  "delivered_at": "2026-05-03T10:00:30Z",
  "payload": {
    "id": "trg_l_plan_m001",
    "scope": "merchant",
    "kind": "active_planning_intent",
    "source": "internal",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": null,
    "payload": {
      "intent_topic": "recall_campaign_q2",
      "merchant_last_message": "What should I run this week?"
    },
    "urgency": 4,
    "suppression_key": "planning:m_001:recall_campaign_q2",
    "expires_at": "2026-12-31T00:00:00Z"
  }
}
```

### L7. Push curiosity trigger

Method: `POST`  
Endpoint: `/v1/context`  
Body:

```json
{
  "scope": "trigger",
  "context_id": "trg_l_curious_m001",
  "version": 1,
  "delivered_at": "2026-05-03T10:00:40Z",
  "payload": {
    "id": "trg_l_curious_m001",
    "scope": "merchant",
    "kind": "curious_ask_due",
    "source": "internal",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": null,
    "payload": {
      "ask_template": "what_service_in_demand_this_week",
      "last_ask_at": null
    },
    "urgency": 1,
    "suppression_key": "curious_ask:m_001:2026-W18",
    "expires_at": "2026-12-31T00:00:00Z"
  }
}
```

### L8. Push research trigger

Method: `POST`  
Endpoint: `/v1/context`  
Body:

```json
{
  "scope": "trigger",
  "context_id": "trg_l_research_m001",
  "version": 1,
  "delivered_at": "2026-05-03T10:00:50Z",
  "payload": {
    "id": "trg_l_research_m001",
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
    "suppression_key": "research:dentists:2026-W18",
    "expires_at": "2026-12-31T00:00:00Z"
  }
}
```

### L9. Push event trigger

Method: `POST`  
Endpoint: `/v1/context`  
Body:

```json
{
  "scope": "trigger",
  "context_id": "trg_l_event_m001",
  "version": 1,
  "delivered_at": "2026-05-03T10:01:00Z",
  "payload": {
    "id": "trg_l_event_m001",
    "scope": "merchant",
    "kind": "festival_upcoming",
    "source": "external",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": null,
    "payload": {
      "festival": "Diwali",
      "date": "2026-10-31",
      "days_until": 120
    },
    "urgency": 2,
    "suppression_key": "festival:m_001:diwali",
    "expires_at": "2026-12-31T00:00:00Z"
  }
}
```

### L10. Push performance trigger

Method: `POST`  
Endpoint: `/v1/context`  
Body:

```json
{
  "scope": "trigger",
  "context_id": "trg_l_perf_m001",
  "version": 1,
  "delivered_at": "2026-05-03T10:01:10Z",
  "payload": {
    "id": "trg_l_perf_m001",
    "scope": "merchant",
    "kind": "perf_dip",
    "source": "internal",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": null,
    "payload": {
      "metric": "calls",
      "delta_pct": -0.5,
      "window": "7d",
      "vs_baseline": 12
    },
    "urgency": 4,
    "suppression_key": "perf_dip:m_001:calls:2026-W18",
    "expires_at": "2026-12-31T00:00:00Z"
  }
}
```

### L11. Push account trigger

Method: `POST`  
Endpoint: `/v1/context`  
Body:

```json
{
  "scope": "trigger",
  "context_id": "trg_l_account_m001",
  "version": 1,
  "delivered_at": "2026-05-03T10:01:20Z",
  "payload": {
    "id": "trg_l_account_m001",
    "scope": "merchant",
    "kind": "gbp_unverified",
    "source": "internal",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": null,
    "payload": {
      "verified": false,
      "verification_path": "postcard_or_phone_call",
      "estimated_uplift_pct": 0.3
    },
    "urgency": 3,
    "suppression_key": "unverified:m_001:l",
    "expires_at": "2026-12-31T00:00:00Z"
  }
}
```

### L12. Push customer recall trigger

Method: `POST`  
Endpoint: `/v1/context`  
Body:

```json
{
  "scope": "trigger",
  "context_id": "trg_l_recall_c001",
  "version": 1,
  "delivered_at": "2026-05-03T10:01:30Z",
  "payload": {
    "id": "trg_l_recall_c001",
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
        {
          "iso": "2026-11-05T18:00:00+05:30",
          "label": "Wed 5 Nov, 6pm"
        },
        {
          "iso": "2026-11-06T17:00:00+05:30",
          "label": "Thu 6 Nov, 5pm"
        }
      ]
    },
    "urgency": 3,
    "suppression_key": "recall:c_001_priya_for_m001:6mo:l",
    "expires_at": "2026-12-31T00:00:00Z"
  }
}
```

### L13. Tick for 6 families

Method: `POST`  
Endpoint: `/v1/tick`  
Body:

```json
{
  "now": "2026-05-03T10:02:00Z",
  "available_triggers": [
    "trg_l_plan_m001",
    "trg_l_curious_m001",
    "trg_l_research_m001",
    "trg_l_event_m001",
    "trg_l_perf_m001",
    "trg_l_account_m001"
  ]
}
```

### L14. Tick for customer recall

Method: `POST`  
Endpoint: `/v1/tick`  
Body:

```json
{
  "now": "2026-05-03T10:03:00Z",
  "available_triggers": [
    "trg_l_recall_c001"
  ]
}
```

Use the `conversation_id` values from L13 and L14 outputs.

Important branch rule:
- Use one conversation for `L15` to `L17` (normal + busy path).
- Use a different fresh conversation (or rerun L13 to get a new `conversation_id`) for `L18` auto-reply.
- This prevents mixing wait-flow and auto-reply-flow in the same branch.

### L15. Reply: commitment (Engagement Compulsion check)

Method: `POST`  
Endpoint: `/v1/reply`  
Body:

```json
{
  "conversation_id": "PUT_CONV_ID_FROM_L13",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Ok lets do it. Whats next?",
  "received_at": "2026-05-03T10:04:00Z",
  "turn_number": 2
}
```

### L16. Reply: off-topic

Method: `POST`  
Endpoint: `/v1/reply`  
Body:

```json
{
  "conversation_id": "PUT_CONV_ID_FROM_L13",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Can you suggest a CA for tax filing?",
  "received_at": "2026-05-03T10:04:30Z",
  "turn_number": 3
}
```

### L17. Reply: busy

Method: `POST`  
Endpoint: `/v1/reply`  
Body:

```json
{
  "conversation_id": "PUT_CONV_ID_FROM_L13",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "I am in clinic right now, ping later.",
  "received_at": "2026-05-03T10:05:00Z",
  "turn_number": 4
}
```

Expected response pattern:

```json
{
  "action": "wait",
  "body": null,
  "cta": null,
  "wait_seconds": 1800,
  "rationale": "busy_wait"
}
```

### L18. Reply: auto-reply

Use a fresh conversation id here, not the busy branch id.

Method: `POST`  
Endpoint: `/v1/reply`  
Body:

```json
{
  "conversation_id": "PUT_FRESH_CONV_ID_FOR_AUTOREPLY",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Thank you for contacting us. Our team will respond shortly.",
  "received_at": "2026-05-03T10:05:30Z",
  "turn_number": 5
}
```

Expected response pattern:

```json
{
  "action": "end",
  "body": null,
  "cta": null,
  "wait_seconds": null,
  "rationale": "An auto-reply was detected, so the conversation is being closed immediately rather than wasting further turns."
}
```

### L19. Reply: customer booking confirm

Method: `POST`  
Endpoint: `/v1/reply`  
Body:

```json
{
  "conversation_id": "PUT_CONV_ID_FROM_L14",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": "c_001_priya_for_m001",
  "from_role": "customer",
  "message": "Yes please book me for Wed 5 Nov, 6pm.",
  "received_at": "2026-05-03T10:06:00Z",
  "turn_number": 1
}
```

### L20. Reply: customer opt-out

Method: `POST`  
Endpoint: `/v1/reply`  
Body:

```json
{
  "conversation_id": "PUT_CONV_ID_FROM_L14",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": "c_001_priya_for_m001",
  "from_role": "customer",
  "message": "Please stop messages, opt me out.",
  "received_at": "2026-05-03T10:06:30Z",
  "turn_number": 2
}
```

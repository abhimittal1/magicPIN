# Code Flow — magicPIN Vera Bot

> **How to read these diagrams**: Each box is a file/module. Arrows show which file calls which. Read top-to-bottom for the main flow, left-to-right for file dependencies.
> These diagrams use **Mermaid** syntax — GitHub, Notion, Obsidian, and VS Code (with the Markdown Preview Mermaid Support extension) all render them automatically.

---

## Diagram 1 — Full Compose Pipeline
> What happens from the moment the judge pushes a trigger to the moment a message is returned.

```mermaid
flowchart TD
    JUDGE([Judge / HTTP Client])

    JUDGE -->|"POST /v1/context\n{scope, version, payload}"| CTX

    subgraph STEP1 ["1 · Store Context"]
        CTX["main.py\npush_context"]
        CTX --> VER{"version\ncheck"}
        VER -->|lower version| REJ["❌ 409 — stale_version"]
        VER -->|same version + same payload| ACC["✅ silent accept\nidempotent replay"]
        VER -->|higher version| STORE["store.py\nContext saved in memory\nkeyed by (scope, id)"]
    end

    JUDGE -->|"POST /v1/tick\n{available_triggers: [ids]}"| TICK

    subgraph STEP2 ["2 · Assemble Context"]
        TICK["main.py\ntick endpoint"]
        TICK --> RES["resolver.py\nresolve_trigger_id()"]
        RES --> FETCH["store.py\nget_context() x4\ntrigger → merchant\n→ category → customer"]
        FETCH --> FLAGS["ResolvedContext + flags\nplaceholder_payload?\ncategory_mismatch?\nhas_active_offer?\ncustomer_opted_in?"]
    end

    subgraph STEP3 ["3 · Rank Priority"]
        FLAGS --> RANK["ranker.py  score()\nurgency + evidence_bonus\n+ scope_bonus - risk_penalty"]
        RANK --> SORT["Triggers sorted\nhighest score first"]
    end

    subgraph STEP4 ["4 · Plan Strategy"]
        SORT --> PLAN["planner.py  build()\nWhich family?\nresearch / event / performance\n/ account / customer_followup\n/ planning / curiosity / fallback"]
        PLAN --> PLANOUT["MessagePlan\nsend_as  cta_type  primary_goal\ntemplate_name  risk_flags"]
    end

    subgraph STEP5 ["5 · Pick Facts"]
        PLANOUT --> EVI["evidence.py  select()\nMax 12 facts\ntrigger → merchant → customer → category\n0.021 humanized → 2.1%"]
        EVI --> FACTS["EvidenceFact list\nOnly these allowed in message"]
    end

    subgraph STEP6 ["6 · Set Tone"]
        FACTS --> VOI["voices.py\nSalutation: Dr. Meera vs Hi Salon!\nLanguage: hi-en mix → Hinglish\nTone: clinical-peer / warm / etc."]
    end

    subgraph STEP7 ["7 · Write with GPT"]
        VOI --> LLM["llm_client.py  draft()\nLangChain + OpenAI\nSystem prompt: be Vera, WhatsApp-native\nUse ONLY approved facts\nFirst sentence = WHY now\nOne CTA at end\nReturns: body + rationale"]
    end

    subgraph STEP8 ["8 · Validate"]
        LLM --> VAL["validator.py  validate()\n✗ empty body\n✗ wrong send_as\n✗ taboo words\n✗ exact repeat of prev message\n✗ numbers NOT in any context = hallucination!"]
        VAL --> ISSUES{"issues\nfound?"}
        ISSUES -->|Yes| FALL["llm_client.py  _fallback()\nDeterministic template\nno GPT — always safe"]
        ISSUES -->|No| COMP
        FALL --> COMP["ComposedMessage\nbody · cta · send_as\nsuppression_key · rationale"]
    end

    subgraph STEP9 ["9 · Save + Respond"]
        COMP --> CONV["store.py\ncreate_conversation()\nSave turn history + suppression key"]
        CONV --> RESP["✅ JSON Response\n{body, cta, send_as,\nsuppression_key, rationale}"]
    end

    style JUDGE fill:#e8eaf6,stroke:#5c6bc0
    style REJ fill:#ffebee,stroke:#e53935
    style FALL fill:#fff8e1,stroke:#fb8c00
    style RESP fill:#e8f5e9,stroke:#43a047
```

---

## Diagram 2 — Reply Flow
> What happens when a merchant (or customer) replies to a Vera message.

```mermaid
flowchart TD
    JUDGE([Merchant sends a reply])
    JUDGE -->|"POST /v1/reply\n{conversation_id, message, from_role}"| RPL

    subgraph S1 ["1 · Load State"]
        RPL["main.py  reply endpoint"]
        RPL --> GETCONV["store.py\nget_conversation()"]
        GETCONV --> GETMERCH["resolver.py\nresolve_merchant_id()\nload merchant + category"]
        GETMERCH --> ADDTURN["store.py  add_turn()\nRecord inbound message"]
    end

    subgraph S2 ["2 · Fast Heuristic Check  (no LLM!)"]
        ADDTURN --> CLF["reply_classifier.py  classify()\nRegex patterns only — microseconds\nNo API call needed"]
        CLF --> KIND{"What kind\nof reply?"}
    end

    subgraph S3 ["3 · Route by Classification"]
        KIND -->|"auto_reply\n'Thank you for contacting...'"| AUTO["Send ONE polite follow-up\nthen end\n(max 1 retry with a bot)"]
        KIND -->|"explicit_no_or_stop\n'nahi chahiye', 'stop'"| STOP["action = end\nStore suppression key\nNever message again"]
        KIND -->|"busy_wait\n'baad mein', 'ping me later'"| BUSY["action = wait\nSchedule retry — no reply now"]
        KIND -->|"abusive\n'spam', 'idiot'"| ABUSE["action = end  immediately"]
        KIND -->|"ambiguous\n(everything else)"| LLM2["llm_client.py\nclassify_and_reply()\nREPLY_DECISION_SYSTEM_PROMPT\nAnalyze in conversation context\nReturn action + body"]
    end

    subgraph S4 ["4 · Validate reply (if sending)"]
        LLM2 --> VDEC{"action\n= send?"}
        VDEC -->|Yes| VALR["validator.py  validate_reply()\nnot empty · not repeat"]
        VDEC -->|wait or end| SAVE
        VALR --> ISS2{"issues?"}
        ISS2 -->|Yes| FALLR["llm_client.py\n_reply_decision_fallback()\nSafe deterministic reply"]
        ISS2 -->|No| SAVE
        FALLR --> SAVE
    end

    subgraph S5 ["5 · Save + Respond"]
        AUTO --> SAVE["store.py  add_turn()\nupdate conversation state"]
        STOP --> SAVE
        BUSY --> SAVE
        ABUSE --> SAVE
        SAVE --> RESP2["✅ JSON Response\n{action: send / wait / end\nbody  (if send)\nwait_seconds  (if wait)}"]
    end

    style JUDGE fill:#e8eaf6,stroke:#5c6bc0
    style STOP fill:#ffebee,stroke:#e53935
    style ABUSE fill:#ffebee,stroke:#e53935
    style BUSY fill:#fff8e1,stroke:#fb8c00
    style AUTO fill:#fff8e1,stroke:#fb8c00
    style RESP2 fill:#e8f5e9,stroke:#43a047
```

---

## Diagram 3 — File Dependency Map
> Which file imports from which. Follow the arrows to see who calls who.

```mermaid
flowchart LR
    subgraph ENTRY ["Entry Points"]
        BOT["bot.py"]
        MAIN["main.py"]
    end

    subgraph PIPELINE ["Core Pipeline"]
        COMP["composer.py\nOrchestrator"]
        PLAN["planner.py\nStrategy"]
        EVI["evidence.py\nFact picker"]
        LLM["llm_client.py\nGPT writer"]
        VAL["validator.py\nQuality guard"]
    end

    subgraph SUPPORT ["Support"]
        RES["resolver.py"]
        RANK["ranker.py"]
        VOI["voices.py"]
        RPM["reply_manager.py"]
        RPC["reply_classifier.py"]
    end

    subgraph INFRA ["Infrastructure"]
        STORE["store.py"]
        CFG["config.py"]
        SCH["schemas.py"]
    end

    BOT --> COMP
    BOT --> CFG

    MAIN --> COMP
    MAIN --> STORE
    MAIN --> RES
    MAIN --> RANK
    MAIN --> RPM
    MAIN --> SCH

    COMP --> PLAN
    COMP --> EVI
    COMP --> LLM
    COMP --> VAL
    COMP --> SCH

    PLAN --> VOI
    PLAN --> SCH

    EVI --> VOI
    EVI --> SCH

    LLM --> VOI
    LLM --> SCH
    LLM --> CFG

    VAL --> EVI
    VAL --> SCH

    RES --> STORE
    RES --> SCH

    RANK --> SCH

    RPM --> STORE
    RPM --> RES
    RPM --> RPC
    RPM --> LLM
    RPM --> VAL
    RPM --> CFG

    style BOT fill:#e3f2fd,stroke:#1565c0
    style MAIN fill:#e3f2fd,stroke:#1565c0
    style COMP fill:#fff3e0,stroke:#e65100
    style LLM fill:#fce4ec,stroke:#c62828
    style STORE fill:#e8f5e9,stroke:#2e7d32
    style SCH fill:#f3e5f5,stroke:#6a1b9a
    style CFG fill:#f3e5f5,stroke:#6a1b9a
```

---

## Diagram 4 — bot.py vs the Live API
> Same core engine, two different entry points.

```mermaid
flowchart TD
    subgraph OFFLINE ["Offline — generate submission.jsonl"]
        GEN["scripts/generate_submission.py"]
        GEN --> BOT["bot.py  compose()"]
        BOT --> CFROM["composer.py\ncompose_from_contexts()"]
        CFROM --> TEMP["Fresh RuntimeStore\ncreated per call"]
    end

    subgraph ONLINE ["Online — live judge server"]
        JUDGE["Judge HTTP Client"]
        JUDGE --> API["main.py  FastAPI server"]
        API --> PERM["Persistent RuntimeStore\nlives for server lifetime"]
        API --> COMP2["composer.py\ncompose_resolved()"]
    end

    CFROM -. "same core engine" .-> COMP2

    style OFFLINE fill:#f5f5f5,stroke:#757575
    style ONLINE fill:#e3f2fd,stroke:#1565c0
    style CFROM fill:#fff3e0,stroke:#e65100
    style COMP2 fill:#fff3e0,stroke:#e65100
```

---

## Diagram 5 — The 4-Context Assembly
> How resolver.py builds one ResolvedContext from 4 separate store lookups.

```mermaid
flowchart LR
    TID(["trigger_id\n'trg_001_research_dentists'"])

    TID --> T["store.py\nget_context('trigger', trigger_id)\n→ {kind, merchant_id, payload, urgency...}"]
    T --> M["store.py\nget_context('merchant', merchant_id)\n→ {identity, performance, offers...}"]
    M --> C["store.py\nget_context('category', category_slug)\n→ {voice, peer_stats, digest...}"]
    M --> CU["store.py\nget_context('customer', customer_id)\n→ {identity, state, consent...}\n(optional — only if trigger has customer_id)"]

    T --> RC
    M --> RC
    C --> RC
    CU --> RC

    RC["ResolvedContext\n──────────────\ntrigger: {...}\nmerchant: {...}\ncategory: {...}\ncustomer: {...} or None\nflags: {\n  placeholder_payload: bool\n  category_mismatch: bool\n  has_active_offer: bool\n  customer_opted_in: bool\n  needs_sparse_fallback: bool\n}"]

    style TID fill:#e8eaf6,stroke:#5c6bc0
    style RC fill:#fff3e0,stroke:#e65100
```

---

## Quick Reference — File Roles

| File | Its one job |
|------|------------|
| `main.py` | Front door — HTTP endpoints, wires all modules together |
| `bot.py` | One-function shortcut for offline compose |
| `store.py` | In-memory filing cabinet — all contexts + conversation history |
| `resolver.py` | Given a trigger ID → assembles all 4 related contexts |
| `ranker.py` | Scores triggers: urgency + evidence − risk |
| `planner.py` | Decides strategy **before** GPT writes anything |
| `evidence.py` | Picks ≤12 verified facts GPT is allowed to use |
| `voices.py` | Salutation, language hint (Hinglish?), tone profile |
| `llm_client.py` | Calls GPT via LangChain; has safe deterministic fallback |
| `validator.py` | Blocks taboo words, hallucinated numbers, and exact repeats |
| `reply_classifier.py` | Fast regex: auto-reply? stop? busy? ambiguous? |
| `reply_manager.py` | Multi-turn conversation orchestrator |
| `composer.py` | Conductor: plan → evidence → draft → validate → return |
| `schemas.py` | Shared data types (ResolvedContext, MessagePlan, etc.) |
| `config.py` | Loads `.env` once and caches it (`@lru_cache`) |

---

## The Golden Path — In One Line

```
Judge pushes context → store.py saves it
Judge fires tick    → resolver assembles 4 contexts
                    → ranker scores priority
                    → planner decides strategy
                    → evidence picks ≤12 facts
                    → voices sets tone + language
                    → llm_client writes with GPT
                    → validator checks for hallucinations/taboo
                    → composer returns ComposedMessage
                    → main.py sends JSON response
```

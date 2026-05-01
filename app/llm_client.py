from __future__ import annotations

import json

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.config import Settings
from app.evidence import humanize_scalar
from app.schemas import ComposedMessage, LLMDraft, LLMReplyDecision, MessagePlan, ResolvedContext
from app.voices import customer_salutation, language_hint, merchant_salutation


SYSTEM_PROMPT = """You are Vera, magicpin's merchant success manager, writing one WhatsApp message — to a merchant or to a customer on the merchant's behalf.

--- OUTPUT CONTRACT ---
Return valid JSON with exactly two keys: body (the WhatsApp message text), rationale (one short sentence explaining the core strategic choice you made).
- body: WhatsApp-native, typically 2–4 sentences. Concise but complete.
- rationale: factual, not promotional. "Used JIDA 3-mo recall stat to anchor urgency for high-risk adult segment" is good. "Created a compelling message" is not.

--- WHAT THE JUDGE SCORES ---
1. SPECIFICITY — anchor on one concrete, verifiable fact: a number, a date, a source citation, a peer benchmark, a named segment. "Haircut @ ₹99" beats "10% off". "2,100-patient JIDA trial" beats "studies show". Never say grow your business, boost sales, improve visibility, or increase revenue without a specific number attached.
2. CATEGORY FIT — voice, vocabulary, and offer format must match the vertical:
   • dentists/doctors: clinical-peer tone, technical terms OK ("fluoride recall", "caries"), NEVER retail-promo, NEVER "AMAZING DEAL"
   • salons/spas: warm-aspirational, service+price preferred ("Haircut @ ₹99")
   • restaurants: appetite-driven, location-specific, occasion-aware
   • gyms/fitness: motivation + results, slot urgency OK
   • pharmacies: compliance-first, empathetic, never prescribes
3. MERCHANT FIT — personalized to THIS merchant: use their CTR, their patient counts, their offers, their locality, their conversation history. Match the language preference exactly (hi-en mix → Hinglish, English → English, Hindi → Hindi).
4. TRIGGER RELEVANCE — the first sentence must make it obvious WHY this message is being sent RIGHT NOW. Use the trigger kind to frame:
   • research_digest → "New [journal] item landed / relevant to your [segment]"
   • perf_spike → "Your [metric] jumped [X]% this week"
   • perf_dip → "[Metric] dropped [X]% — here's the likely fix"
   • recall_due → "[Customer name]'s [interval] recall window just opened"
   • dormant_with_vera → re-engage without re-introducing yourself (they know who you are)
   • festival_upcoming → tie to the merchant's specific category + offer
   • milestone_reached → congratulate + immediate next step
   • competitor_opened → local loss-aversion framing
   • review_theme_emerged → specific theme + quote from context
   • scheduled_recurring → curiosity or knowledge-driven; never reminder-only
5. ENGAGEMENT COMPULSION — use exactly ONE of these levers (pick the strongest given the context):
   • Loss aversion: "you're missing X" / "before this window closes" / "competitor just opened nearby"
   • Social proof: "3 dentists in your locality did Y this month" (only if peer data supports it)
   • Effort externalization: "I've drafted it — just say go" / "5-minute setup"
   • Curiosity: "want to see who?" / "want the full list?" / "here's the one thing that stands out"
   • Specificity hook: the concrete fact IS the hook (lead with the number)
   • Single binary commitment: end with "Reply YES to proceed" or "Want me to send it?" — not multi-choice

--- VOICE RULES ---
- WhatsApp-native: warm, direct, no corporate stiffness
- 2–4 sentences typical; one CTA at the end
- Natural Hinglish (Roman script) when language hints say hi-en mix or code-mix is Hindi-English
- Avoid: "Hope this finds you well", "From our side", "Kindly note", "Please be informed", "We are pleased to"
- Avoid re-introducing Vera by name unless this is the very first message in the thread (dormant re-engagement allowed)
- Merchant-facing: peer/colleague tone — you're helping them run their business, not selling to them
- Customer-facing: warm and helpful on behalf of the merchant — simpler, no jargon

--- NON-NEGOTIABLE RULES ---
- Use only the supplied approved facts. Never invent numbers, dates, prices, citations, competitor names, or patient names.
- When an approved fact includes service-and-price (e.g., "Dental Cleaning @ ₹299"), use that exact phrasing — do NOT convert to a percentage discount.
- Start with the strongest why-now signal from the trigger or evidence. Make the first sentence earn its place.
- One primary CTA only. Binary YES/STOP for action triggers. Open-ended or no CTA for pure information triggers.
- If the trigger payload or evidence is sparse, stay conservative: anchor on the clearest available single fact and one concrete next step. Do not pad with filler.
- Never qualify the merchant's own decision after they have already expressed intent. If they said yes, move to action mode.
"""


REPLY_SYSTEM_PROMPT = """You are Vera, magicpin's merchant success assistant, mid-conversation on WhatsApp.

If asked who you are or what you do: say you are Vera, magicpin's merchant success assistant — you help with profile visibility, patient/customer outreach, and growth insights. One sentence, warm and natural.

Your job: reply directly and specifically to the latest message. Use the merchant facts provided.

Rules:
- WhatsApp-native tone: warm, direct, 2-3 sentences max.
- Match the language of the latest message exactly. If they wrote in English, reply in English. If they mixed Hindi and English (Hinglish in Roman script), reply in Hinglish. The merchant language profile is context only — never override the language the person actually used.
- Answer the actual question with specific facts from the context. Never say generic lines like "I will keep this grounded in context" — just answer.
- If the merchant said yes or wants to move forward, give the one immediate concrete next step.
- Never invent numbers, dates, offers, or names not in the provided context.
- Return valid JSON: { "body": "...", "rationale": "..." }
"""

REPLY_HUMAN_TEMPLATE = """Merchant: {merchant_name} | Category: {category} | Location: {locality}
Languages: {languages}
Message language: {message_language}
Active signals: {signals}
Key facts:
{key_facts}

Conversation so far:
{history}

Latest message from {from_role}: "{message}"

Reply as Vera. Be specific to these facts. Be brief."""


REPLY_DECISION_SYSTEM_PROMPT = """You are Vera, magicpin's merchant success assistant, mid-conversation on WhatsApp.

Your job: decide how to handle the latest inbound message and produce the exact reply in one step.

--- VERA'S SCOPE ---
IN SCOPE — you CAN and SHOULD answer these:
- Patient or customer targeting: who to reach first, which segment to prioritise, lapsed/high-risk patient prioritisation
- Recall intervals, treatment follow-ups, reactivation strategies
- Profile performance metrics: views, CTR, calls, directions, peer comparisons — use the numbers from Key facts
- Active offers, pricing, how to promote them on magicpin
- Post ideas, Google Business Profile improvements, review management
- Research digests or compliance updates provided in the context
- Appointment slots and customer outreach messaging
- Any question about running or growing the merchant's clinic/business on magicpin

OUT OF SCOPE — you CANNOT help with these:
- Accounting, GST, tax filing, income tax returns, bookkeeping
- Legal advice, contracts, or finding a lawyer
- Payroll software, HR tools, or hiring non-medical staff
- Anything completely unrelated to the merchant's business on magicpin
--- END SCOPE ---

Decision rules:
- action=send: use for all in-scope questions, out-of-scope redirects, identity questions, commits, and clarification asks.
- action=wait: use ONLY when the person explicitly says they are busy right now or asks you to come back later (e.g. "I'm busy", "ping me later", "message me tomorrow", "not now"). This means NO reply is sent — the system will schedule a follow-up automatically. Do NOT use action=send with a body saying "I'll message you later" — use action=wait instead.
- action=end: use ONLY if the message clearly ends the conversation or asks you to stop entirely.

Response rules:
- Mirror the language of the latest message exactly. English in, English out. Hinglish in, Hinglish out.
- Keep the reply warm, direct, and WhatsApp-native. Usually 1-3 sentences.
- Sound like a sharp category-aware operator, not a generic customer-support bot.
- For IN SCOPE questions: answer directly and specifically using the Key facts provided. Do not hedge or ask for clarification if the facts are sufficient.
- For OUT OF SCOPE questions: briefly acknowledge it falls outside what you handle, then redirect to one relevant thing you CAN help with from the current thread.
- If the person wants to move forward on something: give one concrete, specific next step.
- If the latest message is a COMMITMENT such as "ok lets do it", "go ahead", "what's next", "haan theek hai", or "next kya hoga", you MUST switch to ACTION MODE immediately. Do not re-qualify. Do not ask exploratory questions. Give a next step using action words like draft, next, proceed, here, confirm, or sending.
- Use the most recent bot turn and conversation trigger to stay on-topic. If the thread started from a research or performance nudge, the next step should stay tied to that thread instead of drifting generic.
- If the message is genuinely unclear: ask one focused clarification question.
- Never invent facts, offers, numbers, names, dates, or capabilities not present in the provided context.

Challenge-specific examples:
1. Merchant: "Ok lets do it. Whats next?"
    Good: action=send, rationale=commit_action, body like "Great. I'll draft the next step now and keep it specific to your high-risk adult recall plan."
    Bad: asking another qualification question or saying a vague line like "give me a moment".
2. Merchant: "Which patients specifically should I target first?"
    Good: action=send, rationale=in_scope_answer, body uses the provided patient segments such as high-risk adults or lapsed patients.
3. Merchant: "Can you recommend a good accountant?"
    Good: action=send, rationale=out_of_scope_redirect, body briefly redirects to profile visibility, offers, outreach, or the current thread.
4. Merchant: "I am busy right now, ping me later."
    Good: action=wait, rationale=busy_wait, wait_seconds set.

Return valid JSON with keys: action, body, rationale, wait_seconds.
- body is required for action=send.
- body is optional for action=end.
- wait_seconds should only be set for action=wait.
- rationale must be one of: in_scope_answer, out_of_scope_redirect, commit_action, busy_wait, identity_question, clarification_request.
"""

REPLY_DECISION_HUMAN_TEMPLATE = """Merchant: {merchant_name} | Category: {category} | Location: {locality}
Languages: {languages}
Message language: {message_language}
Active signals: {signals}
Trigger kind: {trigger_kind}
Trigger summary: {trigger_summary}
Latest bot turn: {latest_bot_turn}
Key facts:
{key_facts}

Conversation so far:
{history}

Latest message from {from_role}: "{message}"

Decide the action and write Vera's reply."""


class WordingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._structured_chain = None
        self._reply_chain = None
        self._reply_decision_chain = None
        if settings.llm_enabled:
            llm = ChatOpenAI(
                api_key=settings.openai_api_key,
                model=settings.openai_model,
                temperature=settings.openai_temperature,
                timeout=settings.openai_timeout_seconds,
            )
            reply_prompt = ChatPromptTemplate.from_messages([
                ("system", REPLY_SYSTEM_PROMPT),
                ("human", REPLY_HUMAN_TEMPLATE),
            ])
            self._reply_chain = reply_prompt | llm.with_structured_output(LLMDraft)
            reply_decision_prompt = ChatPromptTemplate.from_messages([
                ("system", REPLY_DECISION_SYSTEM_PROMPT),
                ("human", REPLY_DECISION_HUMAN_TEMPLATE),
            ])
            self._reply_decision_chain = reply_decision_prompt | llm.with_structured_output(LLMReplyDecision)
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", SYSTEM_PROMPT),
                    (
                        "human",
                        """Prompt version: {prompt_version}
Category: {category_slug} | Trigger kind: {trigger_kind} | Trigger family: {trigger_family}
Audience: {audience} | Primary goal: {primary_goal} | CTA type: {cta_type} | Send as: {send_as}
Merchant: {merchant_name} | Locality: {merchant_locality}
Language: primary={primary_language_hint}, hints={language_hints}, code-mix={code_mix}
Allowed vocabulary: {allowed_vocabulary}
Active offers: {merchant_active_offers}
Category voice examples: {voice_examples}
Tone profile: {tone_profile}
Risk flags: {risk_flags}
Seasonal/trend signals: {seasonal_signals}
Peer benchmarks: {peer_benchmarks}

Approved facts (use these verbatim — do not invent):
{approved_facts}

Task:
1. Pick the single strongest why-now hook from the approved facts + trigger kind.
2. Choose ONE compulsion lever from: loss_aversion | social_proof | effort_externalization | curiosity | specificity_hook | single_binary_commitment.
3. Write the WhatsApp body. Lead with why-now. End with the CTA.
4. Write a rationale naming the hook + lever you used (e.g. "JIDA 3-mo recall stat + loss_aversion for high-risk adult segment").

Language rule: if primary_language_hint is hi-en mix, write in natural Hinglish (Roman script). If English, write in English.
""",
                    ),
                ]
            )
            self._structured_chain = prompt | llm.with_structured_output(LLMDraft)

    def draft(self, plan: MessagePlan, resolved: ResolvedContext) -> tuple[str, str]:
        if plan.trigger_family == "customer_sparse":
            return self._fallback(plan, resolved)
        if self._structured_chain is None:
            return self._fallback(plan, resolved)
        try:
            merchant = resolved.merchant
            customer = resolved.customer or {}
            merchant_identity = merchant.get("identity", {})
            customer_identity = customer.get("identity", {}) if isinstance(customer, dict) else {}
            merchant_languages = merchant_identity.get("languages", [])
            active_offer_titles = [
                offer.get("title", "")
                for offer in merchant.get("offers", [])
                if offer.get("status") == "active" and offer.get("title")
            ]
            primary_language_hint = language_hint(merchant, resolved.customer)
            language_hints = {
                "merchant_languages": merchant_languages[:3],
                "customer_language_pref": customer_identity.get("language_pref"),
                "offer_language_preference": "service_at_price"
                if any("@" in title for title in active_offer_titles)
                else "exact_offer_titles"
                if active_offer_titles
                else "none",
            }
            voice = resolved.category.get("voice", {})
            voice_examples = {
                "salutation_examples": voice.get("salutation_examples", []),
                "tone_examples": voice.get("tone_examples", []),
            }
            merchant_locality = ", ".join(
                part for part in [merchant_identity.get("locality"), merchant_identity.get("city")] if part
            )
            approved_facts = "\n".join(f"- {fact.label}: {fact.text} ({fact.source})" for fact in plan.evidence_facts)
            # Seasonal beats and trend signals for why-now framing
            seasonal_beats = resolved.category.get("seasonal_beats", [])
            trend_signals = resolved.category.get("trend_signals", [])
            seasonal_parts: list[str] = []
            for beat in seasonal_beats[:2]:
                seasonal_parts.append(f"{beat.get('month','')}: {beat.get('note','')}")
            for sig in trend_signals[:2]:
                seasonal_parts.append(f"trend: {sig.get('signal', str(sig))[:100]}")
            seasonal_signals = "; ".join(seasonal_parts) if seasonal_parts else "none"
            # Peer benchmarks for social proof and loss aversion
            peer_stats = resolved.category.get("peer_stats", {}) or {}
            peer_parts: list[str] = []
            if peer_stats.get("avg_ctr"):
                peer_parts.append(f"peer avg CTR: {peer_stats['avg_ctr']}")
            if peer_stats.get("avg_views_30d"):
                peer_parts.append(f"peer avg views (30d): {peer_stats['avg_views_30d']}")
            if peer_stats.get("avg_rating"):
                peer_parts.append(f"peer avg rating: {peer_stats['avg_rating']}")
            if peer_stats.get("avg_reviews"):
                peer_parts.append(f"peer avg reviews: {peer_stats['avg_reviews']}")
            peer_benchmarks = "; ".join(peer_parts) if peer_parts else "none"
            result = self._structured_chain.invoke(
                {
                    "prompt_version": self.settings.prompt_version,
                    "category_slug": resolved.category.get("slug", "unknown"),
                    "trigger_family": plan.trigger_family,
                    "trigger_kind": resolved.trigger.get("kind", "generic"),
                    "audience": plan.audience,
                    "primary_goal": plan.primary_goal,
                    "cta_type": plan.cta_type,
                    "send_as": plan.send_as,
                    "merchant_name": merchant_identity.get("name", "merchant"),
                    "merchant_locality": merchant_locality,
                    "primary_language_hint": primary_language_hint,
                    "language_hints": json.dumps(language_hints, ensure_ascii=False),
                    "code_mix": str(voice.get("code_mix", "")),
                    "allowed_vocabulary": ", ".join(str(item) for item in voice.get("vocab_allowed", [])[:6]),
                    "merchant_active_offers": "; ".join(active_offer_titles[:3]),
                    "voice_examples": json.dumps(voice_examples, ensure_ascii=False),
                    "tone_profile": json.dumps(plan.tone_profile, ensure_ascii=False),
                    "risk_flags": json.dumps(plan.risk_flags, ensure_ascii=False),
                    "seasonal_signals": seasonal_signals,
                    "peer_benchmarks": peer_benchmarks,
                    "approved_facts": approved_facts,
                }
            )
            body = result.body.strip()
            rationale = result.rationale.strip()
            if not body:
                return self._fallback(plan, resolved)
            return body, rationale or plan.rationale_seed
        except Exception:
            return self._fallback(plan, resolved)

    def chat_reply(
        self,
        message: str,
        from_role: str,
        turns: list,
        resolved: ResolvedContext | None,
    ) -> tuple[str, str]:
        """Generate a contextual conversational reply using the LLM."""
        if self._reply_chain is None:
            return self._chat_fallback(message, from_role, resolved)
        try:
            merchant = (resolved.merchant if resolved else {}) or {}
            identity = merchant.get("identity", {})
            merchant_name = identity.get("name", "the merchant")
            category_slug = resolved.category.get("slug", "") if resolved else ""
            locality = ", ".join(p for p in [identity.get("locality"), identity.get("city")] if p)
            languages = ", ".join(identity.get("languages", []))
            signals = ", ".join(merchant.get("signals", [])[:4])

            facts_parts: list[str] = []
            perf = merchant.get("performance", {})
            if perf.get("views"):
                peer_avg = (resolved.category.get("peer_stats", {}) or {}).get("avg_views_30d", "?") if resolved else "?"
                facts_parts.append(f"- Views (30d): {perf['views']} (peer avg: {peer_avg})")
            if perf.get("calls"):
                facts_parts.append(f"- Calls (30d): {perf['calls']}")
            if perf.get("ctr"):
                facts_parts.append(f"- CTR: {perf['ctr']}")
            cust_agg = merchant.get("customer_aggregate", {})
            if cust_agg.get("high_risk_adult_count"):
                facts_parts.append(f"- High-risk adult patients: {cust_agg['high_risk_adult_count']}")
            if cust_agg.get("lapsed_180d_plus"):
                facts_parts.append(f"- Lapsed patients (180d+): {cust_agg['lapsed_180d_plus']}")
            for rt in merchant.get("review_themes", [])[:2]:
                quote = rt.get("common_quote", "")
                facts_parts.append(f"- Reviews ({rt.get('sentiment','')}): {rt.get('theme','')} — \"{quote}\"")
            if resolved:
                for item in resolved.category.get("digest", [])[:2]:
                    facts_parts.append(f"- {item.get('title','')}: {item.get('summary','')[:120]} ({item.get('source','')})")
            key_facts = "\n".join(facts_parts) if facts_parts else "(no additional facts available)"

            history_lines: list[str] = []
            for turn in (turns or [])[-6:]:
                role = turn.from_role if hasattr(turn, "from_role") else turn.get("from_role", "?")
                msg = turn.message if hasattr(turn, "message") else turn.get("message", "")
                history_lines.append(f"{role}: {msg}")
            history = "\n".join(history_lines) if history_lines else "(no prior turns)"

            result = self._reply_chain.invoke({
                "merchant_name": merchant_name,
                "category": category_slug,
                "locality": locality,
                "languages": languages,
                "signals": signals,
                # Escape braces so Python's .format() inside LangChain doesn't raise
                # KeyError on any { } that may appear in stored message bodies or quotes.
                "key_facts": key_facts.replace("{", "{{").replace("}", "}}"),
                "history": history.replace("{", "{{").replace("}", "}}"),
                "from_role": from_role,
                "message_language": self._detect_message_language(message),
                "message": message.replace("{", "{{").replace("}", "}}"),
            })
            body = result.body.strip()
            rationale = result.rationale.strip()
            if not body:
                return self._chat_fallback(message, from_role, resolved)
            return body, rationale
        except Exception:
            return self._chat_fallback(message, from_role, resolved)

    def classify_and_reply(
        self,
        message: str,
        from_role: str,
        turns: list,
        resolved: ResolvedContext | None,
    ) -> dict:
        if self._reply_decision_chain is None:
            return self._reply_decision_fallback(message, from_role, resolved)
        try:
            context = self._reply_context(message, turns, resolved)
            result = self._reply_decision_chain.invoke({
                "merchant_name": context["merchant_name"],
                "category": context["category_slug"],
                "locality": context["locality"],
                "languages": context["languages"],
                "message_language": context["message_language"],
                "signals": context["signals"],
                "trigger_kind": context["trigger_kind"],
                "trigger_summary": context["trigger_summary"].replace("{", "{{").replace("}", "}}"),
                "latest_bot_turn": context["latest_bot_turn"].replace("{", "{{").replace("}", "}}"),
                "key_facts": context["key_facts"].replace("{", "{{").replace("}", "}}"),
                "history": context["history"].replace("{", "{{").replace("}", "}}"),
                "from_role": from_role,
                "message": message.replace("{", "{{").replace("}", "}}"),
            })
            if result.action == "send" and not (result.body or "").strip():
                return self._reply_decision_fallback(message, from_role, resolved)
            return {
                "action": result.action,
                "body": result.body.strip() if result.body else None,
                "rationale": result.rationale.strip() or "reply_decision",
                "wait_seconds": result.wait_seconds,
            }
        except Exception:
            return self._reply_decision_fallback(message, from_role, resolved)

    def _reply_context(self, message: str, turns: list, resolved: ResolvedContext | None) -> dict:
        merchant = (resolved.merchant if resolved else {}) or {}
        identity = merchant.get("identity", {})
        merchant_name = identity.get("name", "the merchant")
        category_slug = resolved.category.get("slug", "") if resolved else ""
        locality = ", ".join(p for p in [identity.get("locality"), identity.get("city")] if p)
        languages = ", ".join(identity.get("languages", []))
        signals = ", ".join(merchant.get("signals", [])[:6])
        trigger_kind = (resolved.trigger if resolved else {}).get("kind", "no_trigger")

        facts_parts: list[str] = []

        # Performance metrics
        perf = merchant.get("performance", {})
        if perf.get("views"):
            peer_avg = (resolved.category.get("peer_stats", {}) or {}).get("avg_views_30d", "?") if resolved else "?"
            facts_parts.append(f"- Views (30d): {perf['views']} (peer avg: {peer_avg})")
        if perf.get("calls"):
            facts_parts.append(f"- Calls (30d): {perf['calls']}")
        if perf.get("ctr"):
            peer_ctr = (resolved.category.get("peer_stats", {}) or {}).get("avg_ctr", "?") if resolved else "?"
            facts_parts.append(f"- CTR: {perf['ctr']} (peer avg: {peer_ctr})")
        if perf.get("directions"):
            facts_parts.append(f"- Directions (30d): {perf['directions']}")
        if perf.get("leads"):
            facts_parts.append(f"- Leads (30d): {perf['leads']}")

        # Customer segments — key for targeting questions
        cust_agg = merchant.get("customer_aggregate", {})
        if cust_agg.get("total_unique_ytd"):
            facts_parts.append(f"- Total unique customers (YTD): {cust_agg['total_unique_ytd']}")
        if cust_agg.get("retention_6mo_pct") is not None:
            facts_parts.append(f"- 6-month retention: {round(cust_agg['retention_6mo_pct'] * 100)}%")
        if cust_agg.get("high_risk_adult_count"):
            facts_parts.append(f"- High-risk adult patients (prime recall candidates): {cust_agg['high_risk_adult_count']}")
        if cust_agg.get("lapsed_180d_plus"):
            facts_parts.append(f"- Lapsed patients (180d+, reactivation targets): {cust_agg['lapsed_180d_plus']}")

        # Active merchant offers
        active_offers = [o.get("title", "") for o in merchant.get("offers", []) if o.get("status") == "active" and o.get("title")]
        if active_offers:
            facts_parts.append(f"- Active offers: {'; '.join(active_offers[:3])}")

        # Category offer catalog
        if resolved:
            cat_offers = resolved.category.get("offer_catalog", [])
            if cat_offers:
                cat_offer_titles = [f"{o.get('title','')} (audience: {o.get('audience','')})" for o in cat_offers[:3]]
                facts_parts.append(f"- Category offers available: {'; '.join(cat_offer_titles)}")

        # Review themes
        for rt in merchant.get("review_themes", [])[:3]:
            quote = rt.get("common_quote", "")
            facts_parts.append(f"- Reviews ({rt.get('sentiment','')}): {rt.get('theme','')} — \"{quote}\" ({rt.get('occurrences_30d', 0)} mentions in 30d)")

        # Category research/compliance digest
        if resolved:
            for item in resolved.category.get("digest", [])[:2]:
                actionable = item.get("actionable", "")
                facts_parts.append(f"- Digest [{item.get('id','')}]: {item.get('title','')}: {item.get('summary','')[:140]} — Action: {actionable} ({item.get('source','')})")

        # Trigger context — what prompted this conversation
        trigger_summary = "(no trigger context available)"
        if resolved and resolved.trigger:
            t = resolved.trigger
            tpayload = t.get("payload", {}) or {}
            facts_parts.append(f"- Conversation trigger: {t.get('kind','')} | {json.dumps(tpayload, ensure_ascii=False)[:200]}")
            trigger_summary = f"{t.get('kind','')} | source={t.get('source', 'unknown')} | urgency={t.get('urgency', 'unknown')} | payload={json.dumps(tpayload, ensure_ascii=False)[:220]}"

        key_facts = "\n".join(facts_parts) if facts_parts else "(no additional facts available)"

        history_lines: list[str] = []
        latest_bot_turn = "(no prior bot turn)"
        for turn in (turns or [])[-6:]:
            role = turn.from_role if hasattr(turn, "from_role") else turn.get("from_role", "?")
            msg = turn.message if hasattr(turn, "message") else turn.get("message", "")
            history_lines.append(f"{role}: {msg}")
            if role == "bot":
                latest_bot_turn = msg
        history = "\n".join(history_lines) if history_lines else "(no prior turns)"
        return {
            "merchant_name": merchant_name,
            "category_slug": category_slug,
            "locality": locality,
            "languages": languages,
            "signals": signals,
            "trigger_kind": trigger_kind,
            "trigger_summary": trigger_summary,
            "latest_bot_turn": latest_bot_turn,
            "key_facts": key_facts,
            "history": history,
            "message_language": self._detect_message_language(message),
        }

    def _detect_message_language(self, message: str) -> str:
        """Return 'english', 'hi-en mix', or 'hindi' based on the message content."""
        # Devanagari Unicode block 0900–097F means native Hindi script
        if any('\u0900' <= c <= '\u097f' for c in message):
            return 'hindi'
        # Common Hindi words written in Roman script → Hinglish
        hi_roman = {
            'kya', 'hai', 'hoon', 'aur', 'nahi', 'nahin', 'mujhe', 'tumhe', 'aap',
            'main', 'hum', 'yeh', 'woh', 'bhi', 'toh', 'lekin', 'ab', 'karo',
            'karti', 'karta', 'chahiye', 'bol', 'bata', 'batao', 'samajh',
            'kaun', 'kaise', 'kyun', 'kab', 'kitna', 'kaunsa', 'kahan',
            'mat', 'ruk', 'theek', 'accha', 'achha', 'haan', 'naa', 'badhte',
        }
        words = set(message.lower().split())
        if words & hi_roman:
            return 'hi-en mix'
        return 'english'

    def _chat_fallback(
        self,
        message: str,
        from_role: str,
        resolved: ResolvedContext | None,
    ) -> tuple[str, str]:
        """Absolute last-resort fallback — only reached when the LLM chain is unavailable or errors."""
        text = message.strip().lower()
        lang = self._detect_message_language(message)
        is_english = lang == "english"
        merchant_name = ((resolved.merchant if resolved else {}) or {}).get("identity", {}).get("name", "")

        if self._looks_like_identity_question(text):
            if is_english:
                body = "I'm Vera, magicpin's merchant success assistant. I help with profile visibility, customer outreach, and practical growth next steps."
            else:
                body = "Main Vera hoon, magicpin ki merchant success assistant. Main profile visibility, customer outreach, aur practical growth next steps mein help karti hoon."
            return body, "identity_question"

        if self._looks_like_commit(text):
            if is_english:
                next_step = f" for {merchant_name}" if merchant_name else ""
                body = f"Great. I'll draft the next concrete step{next_step} now so we can proceed without reworking the basics."
            else:
                next_step = f" {merchant_name} ke liye" if merchant_name else ""
                body = f"Theek hai. Main abhi next concrete step{next_step} draft karti hoon taaki hum seedha proceed kar sakein."
            return body, "commit_action"

        if self._looks_like_busy(text):
            return "", "busy_wait"

        if self._looks_like_out_of_scope(text):
            if is_english:
                body = "That part is outside what I handle here, but I can help with profile visibility, patient outreach, offers, or the next business step on this thread."
            else:
                body = "Woh part main yahan handle nahi karti, lekin profile visibility, patient outreach, offers, ya iss thread ke next business step mein help kar sakti hoon."
            return body, "out_of_scope_redirect"

        if is_english:
            body = "I can keep this practical. Tell me whether you want the next step, a recommendation, or a quick summary from what I already have."
        else:
            body = "Main isse practical rakh sakti hoon. Bata do aapko next step chahiye, recommendation chahiye, ya jo context hai uska quick summary chahiye."
        return body, "clarification_request"

    def _reply_decision_fallback(
        self,
        message: str,
        from_role: str,
        resolved: ResolvedContext | None,
    ) -> dict:
        """Absolute last-resort fallback — only reached when the LLM chain is completely unavailable."""
        body, rationale = self._chat_fallback(message, from_role, resolved)
        if rationale == "busy_wait":
            return {
                "action": "wait",
                "body": None,
                "rationale": rationale,
                "wait_seconds": self.settings.default_busy_wait_seconds,
            }
        return {
            "action": "send",
            "body": body,
            "rationale": rationale,
            "wait_seconds": None,
        }

    def _looks_like_identity_question(self, text: str) -> bool:
        identity_words = [
            "who are you",
            "what are you",
            "your name",
            "what do you do",
            "kaun ho",
            "aap kaun",
            "naam kya",
            "kya naam",
            "apna naam",
        ]
        return any(word in text for word in identity_words)

    def _looks_like_commit(self, text: str) -> bool:
        commit_words = [
            "yes",
            "go ahead",
            "let's do it",
            "lets do it",
            "do it",
            "proceed",
            "send it",
            "share it",
            "what's next",
            "whats next",
            "next kya",
            "haan",
            "theek hai",
            "kar do",
            "chalo karte hain",
        ]
        return any(word in text for word in commit_words)

    def _looks_like_busy(self, text: str) -> bool:
        busy_words = [
            "busy",
            "ping me later",
            "message me later",
            "call me later",
            "follow up later",
            "follow-up later",
            "not now",
            "baad mein",
            "abhi nahi",
            "message me tomorrow",
            "talk later",
        ]
        return any(word in text for word in busy_words)

    def _looks_like_out_of_scope(self, text: str) -> bool:
        off_topic_words = [
            "gst",
            "tax",
            "accountant",
            "bookkeeping",
            "payroll",
            "income tax",
            "legal",
            "lawyer",
            "contract",
        ]
        return any(word in text for word in off_topic_words)

    def _clean_text(self, value: str) -> str:
        return value.replace("_", " ").strip()

    def _payload_text(self, payload: dict, key: str) -> str:
        value = payload.get(key)
        if value is None or value == "":
            return ""
        if isinstance(value, list):
            return "; ".join(self._clean_text(str(item)) for item in value[:4])
        if isinstance(value, (str, int, float, bool)):
            return self._clean_text(humanize_scalar(key, value))
        return self._clean_text(str(value))

    def _fact_text(self, plan: MessagePlan, *labels: str) -> str:
        for label in labels:
            for fact in plan.evidence_facts:
                if fact.label == label and fact.text:
                    return fact.text
        return ""

    def _interesting_fact_texts(self, plan: MessagePlan) -> list[str]:
        skipped_labels = {
            "merchant_salutation",
            "merchant_name",
            "merchant_locality",
            "customer_name",
            "customer_language",
            "customer_state",
        }
        return [fact.text for fact in plan.evidence_facts if fact.text and fact.label not in skipped_labels][:6]

    def _metric_name(self, metric: str) -> str:
        metric_map = {
            "review_count": "reviews",
            "reviews": "reviews",
            "ctr": "CTR",
        }
        return metric_map.get(metric, self._clean_text(metric))

    def _metric_verb(self, metric: str) -> str:
        return "are" if metric.lower() in {"calls", "directions", "reviews", "views"} else "is"

    def _merchant_name(self, merchant: dict) -> str:
        return merchant.get("identity", {}).get("name", "the merchant")

    def _customer_intro(self, customer_name: str, merchant_name: str) -> str:
        return f"Hi {customer_name}, {merchant_name} here."

    def _prefers_hinglish(self, merchant: dict, customer: dict | None) -> bool:
        hint = language_hint(merchant, customer).lower()
        return "hi" in hint

    def _pick_copy(self, prefers_hinglish: bool, english: str, hinglish: str) -> str:
        return hinglish if prefers_hinglish else english

    def _fallback_event(
        self,
        plan: MessagePlan,
        resolved: ResolvedContext,
        lead: str,
        payload: dict,
        prefers_hinglish: bool,
    ) -> tuple[str, str]:
        trigger_kind = resolved.trigger.get("kind", "")
        if trigger_kind == "competitor_opened":
            if resolved.flags.get("placeholder_payload"):
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{lead}, quick heads-up: a nearby competitor move is worth noticing. Want me to draft one concrete response for this week?",
                    f"{lead}, quick heads-up: aas-paas competitor activity dikhi hai. Chaho toh main is week ke liye ek concrete response draft kar doon?",
                )
                return body, plan.rationale_seed
            competitor = self._payload_text(payload, "competitor_name") or "a nearby competitor"
            distance = self._payload_text(payload, "distance_km")
            their_offer = self._payload_text(payload, "their_offer")
            detail = f"{competitor} has opened nearby"
            if distance:
                detail = f"{competitor} has opened about {distance} km away"
            if their_offer:
                detail = f"{detail} with {their_offer}"
            body = self._pick_copy(
                prefers_hinglish,
                f"{lead}, quick heads-up: {detail}. Want me to draft one concrete response for this week?",
                f"{lead}, quick heads-up: {detail}. Chaho toh main is week ke liye ek concrete response draft kar doon?",
            )
            return body, plan.rationale_seed

        if trigger_kind == "festival_upcoming":
            if resolved.flags.get("placeholder_payload"):
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{lead}, an upcoming festival window is worth planning for. Want me to draft one timely offer or reminder?",
                    f"{lead}, upcoming festival window aa rahi hai. Chaho toh main ek timely offer ya reminder draft kar doon?",
                )
                return body, plan.rationale_seed
            festival = self._payload_text(payload, "festival") or "the upcoming festival period"
            date = self._payload_text(payload, "date")
            date_clause = f" on {date}" if date else ""
            body = self._pick_copy(
                prefers_hinglish,
                f"{lead}, {festival} is coming up{date_clause}. Want me to draft one timely offer or reminder?",
                f"{lead}, {festival} aa raha hai{date_clause}. Chaho toh main ek timely offer ya reminder draft kar doon?",
            )
            return body, plan.rationale_seed

        if trigger_kind == "category_seasonal":
            if resolved.flags.get("placeholder_payload"):
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{lead}, demand patterns are shifting in your category. Want me to draft one stock or display action for this week?",
                    f"{lead}, aapki category mein demand pattern shift ho raha hai. Chaho toh main is week ke liye ek stock ya display action draft kar doon?",
                )
                return body, plan.rationale_seed
            season = self._payload_text(payload, "season") or "the current season"
            body = self._pick_copy(
                prefers_hinglish,
                f"{lead}, demand patterns are shifting for {season}. Want me to draft one stock or display action for this week?",
                f"{lead}, {season} ke liye demand pattern shift ho raha hai. Chaho toh main is week ke liye ek stock ya display action draft kar doon?",
            )
            return body, plan.rationale_seed

        if trigger_kind == "ipl_match_today":
            match = self._payload_text(payload, "match") or "today's match"
            venue = self._payload_text(payload, "venue")
            venue_clause = f" near {venue}" if venue else ""
            body = self._pick_copy(
                prefers_hinglish,
                f"{lead}, {match} is on today{venue_clause}. Want me to draft a match-time offer or broadcast?",
                f"{lead}, {match} aaj hai{venue_clause}. Chaho toh main match-time offer ya broadcast draft kar doon?",
            )
            return body, plan.rationale_seed

        summary = ", ".join(self._interesting_fact_texts(plan)[:2]) or "there is a timely update affecting your business"
        return self._pick_copy(
            prefers_hinglish,
            f"{lead}, quick heads-up: {summary}. Want me to turn this into a concrete action plan?",
            f"{lead}, quick heads-up: {summary}. Chaho toh main isse ek concrete action plan mein turn kar doon?",
        ), plan.rationale_seed

    def _fallback_performance(
        self,
        plan: MessagePlan,
        resolved: ResolvedContext,
        lead: str,
        payload: dict,
        prefers_hinglish: bool,
    ) -> tuple[str, str]:
        trigger_kind = resolved.trigger.get("kind", "")
        if trigger_kind in {"perf_dip", "seasonal_perf_dip"}:
            if resolved.flags.get("placeholder_payload"):
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{lead}, one key metric looks softer than usual right now. Want me to draft one focused recovery step for this week?",
                    f"{lead}, ek key metric abhi thoda soft lag raha hai. Chaho toh main is week ke liye ek focused recovery step draft kar doon?",
                )
                return body, plan.rationale_seed
            metric = self._metric_name(str(payload.get("metric", "performance")))
            delta = self._payload_text(payload, "delta_pct")
            window = self._payload_text(payload, "window")
            verb = self._metric_verb(metric)
            detail = f"{metric} {verb} down {delta}" if delta else f"{metric} {verb} softer than usual"
            if window:
                detail = f"{detail} over the last {window}"
            body = self._pick_copy(
                prefers_hinglish,
                f"{lead}, quick read: {detail}. Want me to draft one focused fix for this week?",
                f"{lead}, quick read: {detail}. Chaho toh main is week ke liye ek focused fix draft kar doon?",
            )
            return body, plan.rationale_seed

        if trigger_kind == "perf_spike":
            if resolved.flags.get("placeholder_payload"):
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{lead}, one key metric looks stronger than usual right now. Want me to draft one way to keep the momentum going?",
                    f"{lead}, ek key metric abhi stronger dikh raha hai. Chaho toh main momentum banaye rakhne ka ek step draft kar doon?",
                )
                return body, plan.rationale_seed
            metric = self._metric_name(str(payload.get("metric", "performance")))
            delta = self._payload_text(payload, "delta_pct")
            window = self._payload_text(payload, "window")
            verb = self._metric_verb(metric)
            detail = f"{metric} {verb} up {delta}" if delta else f"{metric} {verb} stronger than usual"
            if window:
                detail = f"{detail} over the last {window}"
            body = self._pick_copy(
                prefers_hinglish,
                f"{lead}, quick read: {detail}. Want me to draft one way to keep the momentum going?",
                f"{lead}, quick read: {detail}. Chaho toh main momentum ko hold karne ka ek step draft kar doon?",
            )
            return body, plan.rationale_seed

        if trigger_kind == "milestone_reached":
            if resolved.flags.get("placeholder_payload"):
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{lead}, a useful milestone is within reach. Want me to draft a short push to build on it?",
                    f"{lead}, ek useful milestone bilkul paas hai. Chaho toh main isko build karne ke liye ek short push draft kar doon?",
                )
                return body, plan.rationale_seed
            metric = self._metric_name(str(payload.get("metric", "progress")))
            milestone_value = self._payload_text(payload, "milestone_value")
            value_now = self._payload_text(payload, "value_now")
            imminent = bool(payload.get("is_imminent"))
            if imminent and milestone_value:
                detail = f"you are close to {milestone_value} {metric}"
            elif milestone_value:
                detail = f"you have reached {milestone_value} {metric}"
            elif value_now:
                detail = f"{metric} is now at {value_now}"
            else:
                detail = "a useful milestone is within reach"
            body = self._pick_copy(
                prefers_hinglish,
                f"{lead}, quick read: {detail}. Want me to draft a short push to build on it?",
                f"{lead}, quick read: {detail}. Chaho toh main isko build karne ke liye ek short push draft kar doon?",
            )
            return body, plan.rationale_seed

        summary = ", ".join(self._interesting_fact_texts(plan)[:2]) or "your recent performance shifted"
        return self._pick_copy(
            prefers_hinglish,
            f"{lead}, quick read: {summary}. Want me to draft one focused fix for this week?",
            f"{lead}, quick read: {summary}. Chaho toh main is week ke liye ek focused fix draft kar doon?",
        ), plan.rationale_seed

    def _fallback_account(
        self,
        plan: MessagePlan,
        resolved: ResolvedContext,
        lead: str,
        payload: dict,
        prefers_hinglish: bool,
    ) -> tuple[str, str]:
        trigger_kind = resolved.trigger.get("kind", "")
        if trigger_kind == "gbp_unverified":
            if resolved.flags.get("placeholder_payload"):
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{lead}, one account item needs attention in your profile setup. Want me to map the next steps clearly?",
                    f"{lead}, profile setup mein ek account item attention maang raha hai. Chaho toh main next steps clearly map kar doon?",
                )
                return body, plan.rationale_seed
            verification_path = self._payload_text(payload, "verification_path")
            uplift = self._payload_text(payload, "estimated_uplift_pct")
            if prefers_hinglish:
                body = f"{lead}, aapka Google Business Profile abhi tak not verified hai."
                if verification_path:
                    body = f"{body} Current path {verification_path} hai."
                if uplift:
                    body = f"{body} Ye ho jaye toh discovery about {uplift} improve ho sakti hai."
                body = f"{body} Chaho toh main quickest next step map kar doon?"
                return body, plan.rationale_seed
            body = f"{lead}, your Google Business Profile is still not verified."
            if verification_path:
                body = f"{body} The current path is {verification_path}."
            if uplift:
                body = f"{body} Getting this done can improve discovery by about {uplift}."
            body = f"{body} Want me to map the quickest next step?"
            return body, plan.rationale_seed

        if trigger_kind == "dormant_with_vera":
            if resolved.flags.get("placeholder_payload"):
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{lead}, this thread has gone quiet for a while. Want me to draft a simple re-engagement message?",
                    f"{lead}, ye thread kaafi time se quiet hai. Chaho toh main ek simple re-engagement message draft kar doon?",
                )
                return body, plan.rationale_seed
            days = self._payload_text(payload, "days_since_last_merchant_message")
            last_topic = self._payload_text(payload, "last_topic")
            if days:
                body = f"{lead}, it has been {days} days since the last merchant note"
            else:
                body = f"{lead}, it has been a while since the last merchant note"
            if last_topic:
                body = f"{body} about {last_topic}"
            if prefers_hinglish:
                body = f"{body}. Chaho toh main ek simple re-engagement message draft kar doon?"
            else:
                body = f"{body}. Want me to draft a simple re-engagement message?"
            return body, plan.rationale_seed

        summary = ", ".join(self._interesting_fact_texts(plan)[:2]) or "there is one account item worth fixing"
        return self._pick_copy(
            prefers_hinglish,
            f"{lead}, one account update: {summary}. Want me to map the next step clearly?",
            f"{lead}, ek account update hai: {summary}. Chaho toh main next step clearly map kar doon?",
        ), plan.rationale_seed

    def _fallback_customer_followup(
        self,
        plan: MessagePlan,
        resolved: ResolvedContext,
        customer_name: str,
        merchant_name: str,
        active_offer: str,
        payload: dict,
        prefers_hinglish: bool,
    ) -> tuple[str, str]:
        trigger_kind = resolved.trigger.get("kind", "")
        intro = self._customer_intro(customer_name, merchant_name)
        slot_text = self._fact_text(plan, "available_slots")

        if trigger_kind == "recall_due":
            service_due = self._payload_text(payload, "service_due") or "your next check-in"
            body = self._pick_copy(
                prefers_hinglish,
                f"{intro} It is time for {service_due}.",
                f"{intro} {service_due} ka time ho gaya hai.",
            )
            if slot_text:
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{body} Available options: {slot_text}.",
                    f"{body} Available options: {slot_text}.",
                )
            if active_offer:
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{body} Current offer: {active_offer}.",
                    f"{body} Current offer: {active_offer}.",
                )
            body = self._pick_copy(
                prefers_hinglish,
                f"{body} Reply with a time that works and we will keep it easy.",
                f"{body} Jo time suit kare woh reply kar do, baaki hum easy rakhenge.",
            )
            return body, plan.rationale_seed

        if trigger_kind == "appointment_tomorrow":
            body = self._pick_copy(
                prefers_hinglish,
                f"{intro} Quick reminder about your appointment tomorrow. Reply here if you want us to confirm or help with timing.",
                f"{intro} Quick reminder: kal aapka appointment hai. Reply here if you want us to confirm or help with timing.",
            )
            return body, plan.rationale_seed

        if trigger_kind == "chronic_refill_due":
            body = self._pick_copy(
                prefers_hinglish,
                f"{intro} Your refill may be due soon.",
                f"{intro} Aapka refill jaldi due ho sakta hai.",
            )
            if active_offer:
                body = f"{body} Current offer: {active_offer}."
            body = self._pick_copy(
                prefers_hinglish,
                f"{body} Reply here if you want help with the next step.",
                f"{body} Next step mein help chahiye ho toh yahin reply kar do.",
            )
            return body, plan.rationale_seed

        if trigger_kind in {"customer_lapsed_soft", "customer_lapsed_hard"}:
            body = self._pick_copy(
                prefers_hinglish,
                f"{intro} Just checking in in case you still need us.",
                f"{intro} Bas check kar rahe hain in case aapko abhi bhi hamari zarurat ho.",
            )
            if active_offer:
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{body} We currently have {active_offer}.",
                    f"{body} Abhi {active_offer} available hai.",
                )
            if trigger_kind == "customer_lapsed_hard":
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{body} If you want to restart, we can keep it simple.",
                    f"{body} Restart karna ho toh hum simple rakhenge.",
                )
            else:
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{body} Reply here if you want the details.",
                    f"{body} Details chahiye ho toh yahin reply kar do.",
                )
            return body, plan.rationale_seed

        state = self._fact_text(plan, "customer_state")
        if slot_text:
            body = self._pick_copy(
                prefers_hinglish,
                f"{intro} Quick follow-up for your {state or 'next step'}. Available options: {slot_text}.",
                f"{intro} Quick follow-up for your {state or 'next step'}. Available options: {slot_text}.",
            )
        else:
            body = self._pick_copy(
                prefers_hinglish,
                f"{intro} Quick follow-up based on your recent history with us.",
                f"{intro} Aapki recent history ke basis par ek quick follow-up bhej rahe hain.",
            )
        if active_offer:
            body = f"{body} Current offer: {active_offer}."
        body = self._pick_copy(
            prefers_hinglish,
            f"{body} Reply with a time that works or message us if you want details.",
            f"{body} Jo time suit kare woh reply kar do, ya details chahiye ho toh message kar do.",
        )
        return body, plan.rationale_seed

    def _fallback_customer_sparse(
        self,
        plan: MessagePlan,
        resolved: ResolvedContext,
        customer_name: str,
        merchant_name: str,
        active_offer: str,
        prefers_hinglish: bool,
    ) -> tuple[str, str]:
        trigger_kind = resolved.trigger.get("kind", "")
        intro = self._customer_intro(customer_name, merchant_name)

        if trigger_kind == "appointment_tomorrow":
            return self._pick_copy(
                prefers_hinglish,
                f"{intro} Quick reminder about your appointment tomorrow. Reply here if you want us to confirm or help with timing.",
                f"{intro} Quick reminder: kal aapka appointment hai. Reply here if you want us to confirm or help with timing.",
            ), plan.rationale_seed

        if trigger_kind == "chronic_refill_due":
            return self._pick_copy(
                prefers_hinglish,
                f"{intro} Your refill may be due soon. Reply here if you want help with the next step.",
                f"{intro} Aapka refill jaldi due ho sakta hai. Next step mein help chahiye ho toh yahin reply kar do.",
            ), plan.rationale_seed

        if trigger_kind == "recall_due":
            return self._pick_copy(
                prefers_hinglish,
                f"{intro} It is time for your next check-in. Reply here if you want help booking it.",
                f"{intro} Aapke next check-in ka time ho gaya hai. Booking help chahiye ho toh yahin reply kar do.",
            ), plan.rationale_seed

        if trigger_kind in {"customer_lapsed_soft", "customer_lapsed_hard"}:
            body = self._pick_copy(
                prefers_hinglish,
                f"{intro} Just checking in in case you still need us.",
                f"{intro} Bas check kar rahe hain in case aapko abhi bhi hamari zarurat ho.",
            )
            if active_offer:
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{body} We currently have {active_offer}.",
                    f"{body} Abhi {active_offer} available hai.",
                )
            if trigger_kind == "customer_lapsed_hard":
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{body} Reply here if you want help restarting.",
                    f"{body} Restart karne mein help chahiye ho toh yahin reply kar do.",
                )
            else:
                body = self._pick_copy(
                    prefers_hinglish,
                    f"{body} Reply here if you want the details.",
                    f"{body} Details chahiye ho toh yahin reply kar do.",
                )
            return body, plan.rationale_seed

        if active_offer:
            return self._pick_copy(
                prefers_hinglish,
                f"{intro} Quick check-in from us. If you are still considering a visit, we currently have {active_offer}. Reply if you want the details.",
                f"{intro} Quick check-in from us. Agar aap abhi bhi visit plan kar rahe ho, toh abhi {active_offer} available hai. Details chahiye ho toh reply kar do.",
            ), plan.rationale_seed
        return self._pick_copy(
            prefers_hinglish,
            f"{intro} Quick check-in from us. If you want help with the next step, reply here and we will keep it simple.",
            f"{intro} Quick check-in from us. Next step mein help chahiye ho toh yahin reply kar do, hum simple rakhenge.",
        ), plan.rationale_seed

    def _fallback(self, plan: MessagePlan, resolved: ResolvedContext) -> tuple[str, str]:
        merchant = resolved.merchant
        customer = resolved.customer
        trigger = resolved.trigger
        payload = trigger.get("payload", {}) or {}
        lead = merchant_salutation(resolved.category, merchant)
        customer_name = customer_salutation(customer)
        merchant_name = self._merchant_name(merchant)
        active_offer = resolved.flags.get("active_offer_titles", [""])[0] if resolved.flags.get("active_offer_titles") else ""
        fact_texts = self._interesting_fact_texts(plan)
        prefers_hinglish = self._prefers_hinglish(merchant, customer)

        if plan.trigger_family == "research":
            headline = fact_texts[0] if fact_texts else "this week's update"
            source = next((fact.text for fact in plan.evidence_facts if "source" in fact.label), "")
            action = next(
                (fact.text for fact in plan.evidence_facts if fact.label.endswith("actionable")),
                self._pick_copy(prefers_hinglish, "Want me to draft the next step?", "Chaho toh main next step draft kar doon?"),
            )
            body = self._pick_copy(
                prefers_hinglish,
                f"{lead}, worth a look: {headline}. {action}",
                f"{lead}, worth a look: {headline}. {action}",
            )
            if source:
                body = f"{body} - {source}"
            return body, plan.rationale_seed

        if plan.trigger_family == "event":
            return self._fallback_event(plan, resolved, lead, payload, prefers_hinglish)

        if plan.trigger_family == "performance":
            return self._fallback_performance(plan, resolved, lead, payload, prefers_hinglish)

        if plan.trigger_family == "account":
            return self._fallback_account(plan, resolved, lead, payload, prefers_hinglish)

        if plan.trigger_family == "curiosity":
            return self._pick_copy(
                prefers_hinglish,
                f"{lead}, quick question: what has been the most asked-for service this week? I can turn that into a Google post and a short WhatsApp reply you can use.",
                f"{lead}, quick question: is week sabse zyada kaunsi service poochi gayi? Main usko ek Google post aur short WhatsApp reply mein turn kar sakti hoon.",
            ), plan.rationale_seed

        if plan.trigger_family == "planning":
            topic = payload.get("intent_topic") or "this idea"
            history_hint = next((fact.text for fact in plan.evidence_facts if fact.label == "last_conversation_turn"), "")
            if history_hint:
                return self._pick_copy(
                    prefers_hinglish,
                    f"{lead}, switching to draft mode for {topic}. Based on your latest note - {history_hint} - I can turn this into a first clean version next. Want the short draft or the fuller one?",
                    f"{lead}, switching to draft mode for {topic}. Aapki latest note - {history_hint} - ke basis par main iska first clean version bana sakti hoon. Short draft chahiye ya fuller one?",
                ), plan.rationale_seed
            return self._pick_copy(
                prefers_hinglish,
                f"{lead}, switching straight into draft mode for {topic}. I will keep the first version concise and editable. Want the short draft first?",
                f"{lead}, switching straight into draft mode for {topic}. Main first version concise aur editable rakhungi. Short draft pehle chahiye?",
            ), plan.rationale_seed

        if plan.trigger_family == "customer_followup":
            return self._fallback_customer_followup(plan, resolved, customer_name, merchant_name, active_offer, payload, prefers_hinglish)

        if plan.trigger_family == "customer_sparse":
            return self._fallback_customer_sparse(plan, resolved, customer_name, merchant_name, active_offer, prefers_hinglish)

        fallback_summary = ", ".join(fact_texts[:2]) if fact_texts else "there is one useful update"
        return self._pick_copy(
            prefers_hinglish,
            f"{lead}, quick update: {fallback_summary}. Want me to draft the next step?",
            f"{lead}, quick update: {fallback_summary}. Chaho toh main next step draft kar doon?",
        ), plan.rationale_seed


def build_template_params(plan: MessagePlan, composed: ComposedMessage) -> list[str]:
    sentences = [part.strip() for part in composed.body.split(".") if part.strip()]
    if not sentences:
        return plan.template_params_seed
    params = list(plan.template_params_seed)
    params.append(sentences[0])
    if len(sentences) > 1:
        params.append(sentences[-1])
    return params[:5]
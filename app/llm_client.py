from __future__ import annotations

import json

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.config import Settings
from app.evidence import humanize_scalar
from app.schemas import ComposedMessage, LLMDraft, MessagePlan, ResolvedContext
from app.voices import customer_salutation, language_hint, merchant_salutation


SYSTEM_PROMPT = """You are Vera, a friendly merchant success manager at magicpin.
You are writing one WhatsApp message for a merchant, or for a customer on the merchant's behalf.

Your message should feel human, sharp, and easy to reply to.

Your output is judged on:
- specificity: use verifiable facts from the approved evidence, not vague claims
- category fit: match the category voice and allowed vocabulary
- merchant fit: sound grounded in this merchant's actual business, offers, locality, or performance when supported by facts
- trigger relevance: make it obvious why this message is being sent now
- engagement compulsion: use one low-friction CTA that makes a reply easy

Voice rules:
- Keep it short and WhatsApp-native. Usually 2-3 sentences is enough.
- Sound warm, capable, and natural. Never sound robotic, template-like, or spammy.
- Prefer natural Hinglish in Roman script when the language hints say hi-en mix or the code-mix hint points that way.
- End with one easy next step, helpful question, or simple CTA. Do not sound pushy.
- Avoid stiff phrases like from our side, kindly note, please be informed, reminder again, or hope you are doing well.

Non-negotiable rules:
- Use only the supplied facts. Never invent numbers, dates, prices, slots, names, competitors, or citations.
- Start from the single strongest approved fact or trigger signal. Make the first sentence explain why this message is happening now whenever possible.
- Use one core hook and no more than two supporting details. Do not overstuff lists unless the CTA genuinely needs multiple options or slots.
- Never use generic fluff like grow your business, boost sales, improve visibility, or game-changing unless a fact makes the claim concrete.
- Match the requested tone profile exactly.
- Use one primary CTA.
- Match any supplied locality, language hint, code-mix guidance, allowed vocabulary, and exact offer wording naturally.
- If the trigger is sparse, stay conservative, but still anchor on the clearest available fact and one concrete next step.
- For merchant-facing messages, sound like a sharp category-aware assistant speaking to the merchant, not an ad.
- For customer-facing messages, sound like helpful merchant staff speaking on behalf of the business, warmer and simpler than merchant-facing copy.
- When an approved fact includes a concrete service-and-price offer, prefer that exact phrasing over generic discount language.
- If a citation or source is provided and it materially helps credibility, you may mention it briefly.
- Return valid JSON with keys: body, rationale.
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


class WordingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._structured_chain = None
        self._reply_chain = None
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
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", SYSTEM_PROMPT),
                    (
                        "human",
                        """
Prompt version: {prompt_version}
Category slug: {category_slug}
Trigger family: {trigger_family}
Trigger kind: {trigger_kind}
Audience: {audience}
Primary goal: {primary_goal}
CTA type: {cta_type}
Send as: {send_as}
Merchant name: {merchant_name}
Merchant locality: {merchant_locality}
Primary language hint: {primary_language_hint}
Language hints: {language_hints}
Code mix hint: {code_mix}
Allowed vocabulary: {allowed_vocabulary}
Merchant active offers: {merchant_active_offers}
Category voice examples: {voice_examples}
Tone profile: {tone_profile}
Risk flags: {risk_flags}
Approved facts:\n{approved_facts}

Writing style reminders:
- Prefer Hinglish when the language hint says hi-en mix or the code-mix hint suggests Hindi-English.
- Keep the body natural and concise. Usually 2-3 sentences.
- Make the CTA feel easy and helpful, not salesy.
- Do not repeat facts mechanically or sound like a template.

Choose one strongest hook from the approved facts, lead with why-now when possible, and write one WhatsApp message body plus one short rationale.
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
        merchant_name = resolved.merchant.get("identity", {}).get("name", "") if resolved else ""
        lang = self._detect_message_language(message)
        is_english = (lang == 'english')
        name_hi = f"{merchant_name} ke liye" if merchant_name else "aapke liye"
        name_en = f"for {merchant_name}" if merchant_name else "for you"
        text = message.lower()
        identity_words = ["who are you", "what are you", "kaun ho", "naam kya", "kya naam", "apna naam", "your name", "aap kaun"]
        if any(w in text for w in identity_words):
            if is_english:
                body = f"I'm Vera — magicpin's merchant success assistant. I help {name_en} with profile visibility, customer outreach, and growth insights."
            else:
                body = f"Main Vera hoon — magicpin ki merchant success assistant. {name_hi} profile visibility, customer outreach, aur growth insights mein help karti hoon."
            return body, "identity_question"
        # Check commit intent BEFORE question detection — "Yes! Whats next?" is a commit,
        # not a question. The ? would otherwise send it down the wrong branch.
        commit_words = ["yes", "go ahead", "lets do it", "let's do it", "send it",
                        "proceed", "share it", "whats next", "what's next"]
        if any(w in text for w in commit_words):
            if is_english:
                body = f"Got it, let's move ahead! Drafting the next concrete step {name_en} now."
            else:
                body = f"Got it, aage badhte hain! {name_hi} next concrete step draft karti hoon — ek second."
            return body, "commit_action"
        if "?" in text or any(text.startswith(w) for w in ("why", "who", "what", "how", "when", "can", "kya", "kaun", "kaise", "kyun")):
            if is_english:
                body = f"Good question — let me answer based on what I have {name_en}. More detail from your side would help me be more precise."
            else:
                body = f"Achha sawaal — {name_hi} jo context available hai ussi ke basis pe jawab deti hoon. Thoda aur detail milega toh aur precise ho sakti hoon."
            return body, "question_fallback"
        if is_english:
            body = "Got it — shall we move ahead? I can draft the next step right now."
        else:
            body = "Got it — aage badhein? Main next step abhi draft kar sakti hoon."
        return body, "ambiguous_fallback"

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
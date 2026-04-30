from __future__ import annotations

from typing import Any


def _voice_text(value: Any) -> str:
    return str(value).replace("_", " ").strip()


def _voice_list(items: list[Any], limit: int) -> str:
    cleaned = [_voice_text(item) for item in items if str(item).strip()]
    return ", ".join(cleaned[:limit])


def _dentist_salutation(name: str, owner: str | None) -> str:
    if owner:
        return owner if owner.startswith("Dr.") else f"Dr. {owner}"
    if name.startswith("Dr."):
        trimmed = name.split("'", 1)[0].strip()
        if trimmed:
            return trimmed
        parts = name.split()
        if len(parts) >= 2:
            return " ".join(parts[:2])
    return name


def merchant_salutation(category: dict[str, Any], merchant: dict[str, Any]) -> str:
    identity = merchant.get("identity", {})
    name = identity.get("name", "there")
    owner = identity.get("owner_first_name")
    if category.get("slug") == "dentists":
        return _dentist_salutation(name, owner)
    return owner or name


def customer_salutation(customer: dict[str, Any] | None) -> str:
    if customer is None:
        return "there"
    return customer.get("identity", {}).get("name", "there")


def language_hint(merchant: dict[str, Any], customer: dict[str, Any] | None) -> str:
    if customer is not None:
        pref = customer.get("identity", {}).get("language_pref")
        if pref:
            return str(pref)
    languages = merchant.get("identity", {}).get("languages", [])
    if "hi" in languages and "en" in languages:
        return "hi-en mix"
    if languages:
        return languages[0]
    return "en"


def build_tone_profile(category: dict[str, Any], merchant: dict[str, Any], customer: dict[str, Any] | None) -> list[str]:
    voice = category.get("voice", {})
    profile = [
        f"Tone: {voice.get('tone', 'clear_helpful')}",
        f"Register: {voice.get('register', 'peer')}",
        f"Language hint: {language_hint(merchant, customer)}",
    ]
    code_mix = voice.get("code_mix")
    if code_mix:
        profile.append(f"Code mix: {_voice_text(code_mix)}")
    if customer is not None:
        profile.append(
            "Customer-facing: stay warm, direct, and operational. Sound like helpful staff from the business, and do not make medical or legal overclaims."
        )
    else:
        profile.append("Merchant-facing: sound like a competent operator and category peer, not a marketer.")
    vocab_allowed = voice.get("vocab_allowed", [])
    if vocab_allowed:
        profile.append("Prefer vocabulary like: " + _voice_list(vocab_allowed, 6))
    tone_examples = voice.get("tone_examples", [])
    if tone_examples:
        profile.append("Style cues: " + " | ".join(_voice_text(example) for example in tone_examples[:2]))
    taboo = voice.get("vocab_taboo", [])
    if taboo:
        profile.append("Avoid: " + _voice_list(taboo, 5))
    return profile
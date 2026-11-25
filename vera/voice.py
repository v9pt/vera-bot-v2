"""Salutation, language, taboo filter, CTA formatting and per-category tone."""
from __future__ import annotations

import re

from .facts import Ctx, clean_person_name


def salutation(ctx: Ctx) -> str:
    ident = (ctx.merchant or {}).get("identity") or {}
    first = (ident.get("owner_first_name") or "").strip()
    if first:
        if ctx.slug == "dentists" and not first.lower().startswith("dr"):
            return f"Dr. {first}"
        return first
    return (ident.get("name") or "there").strip()


def wants_hinglish(merchant: dict) -> bool:
    """Hinglish when Hindi is one of the merchant's primary (first two) languages."""
    langs = [str(x).lower() for x in ((merchant or {}).get("identity") or {}).get("languages") or []]
    return "hi" in langs[:2]


def hinglish_for(ctx: Ctx) -> bool:
    """Merchant language, unless the category voice is English-primary (e.g. gyms)."""
    code_mix = str(((ctx.category or {}).get("voice") or {}).get("code_mix") or "")
    if code_mix.startswith("english_primary"):
        return False
    return wants_hinglish(ctx.merchant)


def customer_wants_hinglish(customer: dict | None) -> bool:
    pref = str(((customer or {}).get("identity") or {}).get("language_pref") or "").lower()
    return bool(re.search(r"\bhi\b|hindi|hinglish", pref))


def cta_choice(a: str, b: str, hinglish: bool) -> str:
    if hinglish:
        return f"Reply 1 — {a}, ya 2 — {b}."
    return f"Reply 1 to {a}, or 2 to {b}."


def _taboo_phrases(taboo: list[str]) -> list[str]:
    out = []
    for t in taboo or []:
        phrase = re.split(r"\s*\(", str(t), maxsplit=1)[0].strip()
        if phrase:
            out.append(phrase.lower())
    return out


def find_taboo(text: str, taboo: list[str]) -> list[str]:
    low = (text or "").lower()
    return [p for p in _taboo_phrases(taboo) if re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", low)]


def clean_taboo(text: str, taboo: list[str]) -> str:
    hits = find_taboo(text, taboo)
    if hits:
        raise ValueError(f"taboo words: {hits}")
    return text


def taboo_of(ctx: Ctx) -> list[str]:
    return list(((ctx.category or {}).get("voice") or {}).get("vocab_taboo") or [])


# Per-category tone: short hooks that set the register for each message mood.
TONE = {
    "dentists": {"news": "worth a look", "alert": "clinical heads-up", "opp": "one for the practice",
                 "news_hi": "ek kaam ki update", "alert_hi": "clinical heads-up", "opp_hi": "practice ke liye ek opportunity"},
    "salons": {"news": "quick one", "alert": "heads-up", "opp": "nice opening for the salon",
               "news_hi": "quick update", "alert_hi": "ek heads-up", "opp_hi": "salon ke liye achha mauka"},
    "restaurants": {"news": "quick one, operator to operator", "alert": "heads-up for the kitchen", "opp": "a covers opportunity",
                    "news_hi": "quick baat", "alert_hi": "kitchen ke liye heads-up", "opp_hi": "covers badhane ka mauka"},
    "gyms": {"news": "coach's note", "alert": "heads-up", "opp": "momentum check",
             "news_hi": "coach's note", "alert_hi": "ek heads-up", "opp_hi": "momentum check"},
    "pharmacies": {"news": "precise update", "alert": "important — please check", "opp": "one for the counter",
                   "news_hi": "ek zaroori update", "alert_hi": "zaroori — please check karein", "opp_hi": "counter ke liye ek idea"},
}


def tone(ctx: Ctx, mood: str, hinglish: bool) -> str:
    t = TONE.get(ctx.slug) or TONE["salons"]
    return t.get(f"{mood}_hi" if hinglish else mood) or t[mood]


def customer_name(ctx: Ctx) -> str | None:
    name, _ = clean_person_name(((ctx.customer or {}).get("identity") or {}).get("name"))
    return name


def customer_parent(ctx: Ctx) -> str | None:
    _, parent = clean_person_name(((ctx.customer or {}).get("identity") or {}).get("name"))
    return parent

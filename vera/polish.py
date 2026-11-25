"""Optional LLM polish. The rule draft always wins unless the rewrite passes the validator.

Enabled only with LLM_POLISH=1 and a GEMINI_API_KEY or GROQ_API_KEY. Gemini first, then
Groq, both at temperature 0 via plain REST. Any error, timeout or failed check returns
the original body.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, wait

import requests

from .grounding import ungrounded
from .voice import customer_wants_hinglish, find_taboo, hinglish_for, taboo_of

log = logging.getLogger("vera.polish")

TIMEOUT_S = 6
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
_cache: dict[str, str] = {}
_cache_lock = threading.Lock()


def polish_enabled() -> bool:
    return os.getenv("LLM_POLISH") == "1" and bool(os.getenv("GEMINI_API_KEY") or os.getenv("GROQ_API_KEY"))


def _prompt(body: str, hinglish: bool) -> str:
    lang = ("Keep the natural Hinglish (Roman-script Hindi-English) code-mix." if hinglish
            else "Write in clear, natural English.")
    return (
        "Rewrite this WhatsApp message so it reads naturally and warmly, like a sharp human account manager. "
        "Rules: keep EVERY number, price, percentage, date, time, name and quoted text exactly as written; "
        "add no new facts, numbers or claims; keep the final 'Reply 1 ... 2 ...' sentence exactly as written; "
        "do not lengthen it much; no emojis; no greetings beyond the existing one. " + lang +
        " Return only the rewritten message.\n\nMESSAGE:\n" + body
    )


def _gemini(prompt: str) -> str | None:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0, "maxOutputTokens": 400, "thinkingConfig": {"thinkingBudget": 0}}},
        timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts).strip() or None


def _groq(prompt: str) -> str | None:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": GROQ_MODEL, "temperature": 0, "max_tokens": 800,
              **({"reasoning_effort": "low"} if GROQ_MODEL.startswith("openai/gpt-oss") else {}),
              "messages": [{"role": "user", "content": prompt}]},
        timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    return (r.json()["choices"][0]["message"]["content"] or "").strip() or None


def _cta_sentence(body: str) -> str:
    m = re.search(r"Reply\b.*$", body, re.S)
    return m.group(0).strip() if m else ""


def validate(original: str, candidate: str | None, facts: dict[str, str], taboo: list[str]) -> bool:
    if not candidate:
        return False
    c = candidate.strip().strip('"').strip()
    if ungrounded(c, facts):
        return False
    if find_taboo(c, taboo):
        return False
    if len(c) > 1.4 * len(original):
        return False
    if len(re.findall(r"\bReply\b", c)) > 1:
        return False
    cta = _cta_sentence(original)
    if cta and cta not in c:
        return False
    if not cta and original.rstrip().endswith("?") and not c.rstrip().endswith("?"):
        return False
    for word in ("vera", "magicpin"):
        if re.search(rf"\b{word}\b", c, re.I) and not re.search(rf"\b{word}\b", original, re.I):
            return False
    head = original.split(",", 1)[0]
    if head and len(head) < 60 and not c.startswith(head):
        return False
    return True


def polish(body: str, facts: dict[str, str], taboo: list[str], hinglish: bool, cache_key: str) -> str:
    if not polish_enabled():
        return body
    with _cache_lock:
        if cache_key in _cache:
            return _cache[cache_key]
    prompt = _prompt(body, hinglish)
    result = body
    for provider in (_gemini, _groq):
        try:
            cand = provider(prompt)
        except Exception as e:  # noqa: BLE001 - any provider failure falls through
            log.info("polish provider %s failed: %s", provider.__name__, type(e).__name__)
            continue
        if validate(body, cand, facts, taboo):
            result = cand.strip().strip('"').strip()
            break
        log.info("polish provider %s output rejected by validator", provider.__name__)
    with _cache_lock:
        _cache[cache_key] = result
    return result


def polish_all(actions: list[dict], ctxs: dict, deadline_s: float) -> list[dict]:
    if not actions:
        return actions
    pool = ThreadPoolExecutor(max_workers=8)
    futures = {}
    for i, a in enumerate(actions):
        ctx = ctxs.get(a.get("trigger_id"))
        if ctx is None:
            continue
        hinglish = customer_wants_hinglish(ctx.customer) if a.get("send_as") == "merchant_on_behalf" else hinglish_for(ctx)
        key = a.get("_cache_key") or f"{a.get('trigger_id')}:{a.get('body')}"
        futures[pool.submit(polish, a["body"], ctx.facts, taboo_of(ctx), hinglish, key)] = i
    done, _ = wait(list(futures), timeout=max(0.0, deadline_s))
    out = [dict(a) for a in actions]
    for fut in done:
        try:
            out[futures[fut]]["body"] = fut.result()
        except Exception:  # noqa: BLE001
            pass
    pool.shutdown(wait=False, cancel_futures=True)
    return out

"""compose(): kind dispatch, validation and a generic fallback that never raises."""
from __future__ import annotations

import logging
import re

from .compose_customer import CUSTOMER_COMPOSERS, greeting
from .compose_merchant import MERCHANT_COMPOSERS, Draft, L, commas, join
from .facts import Ctx, human
from .grounding import ungrounded
from .voice import cta_choice, customer_wants_hinglish, find_taboo, hinglish_for, salutation, taboo_of

log = logging.getLogger("vera.compose")

_SKIP_KEY = re.compile(r"(^|_)(id|ids|iso|ts|at|url|template)$")


def _payload_bits(ctx: Ctx, limit: int = 2) -> list[str]:
    bits = []
    for k, v in ctx.payload.items():
        if len(bits) >= limit:
            break
        if isinstance(v, bool) or v is None or isinstance(v, (dict, list)) or _SKIP_KEY.search(k):
            continue
        val = ctx.facts.get(f"p_{k}")
        if not val or len(val) > 80:
            continue
        val = human(val) if isinstance(v, str) and "_" in val and " " not in val else val
        bits.append(f"{human(k)} {val}" if isinstance(v, (int, float)) else f"{human(k)}: {val}")
    return bits


def _metric_line(ctx: Ctx, h: bool) -> str:
    f = ctx.facts
    if f.get("views_30d") and f.get("ctr") and f.get("peer_ctr"):
        return L(h, f"For context, your profile had {commas(f['views_30d'])} views last month at a {f['ctr']} CTR (peer average {f['peer_ctr']}).",
                 f"Context ke liye: pichhle mahine {commas(f['views_30d'])} profile views, CTR {f['ctr']} (peer average {f['peer_ctr']}).")
    if f.get("views_30d"):
        return L(h, f"Your profile had {commas(f['views_30d'])} views last month.", f"Pichhle mahine profile pe {commas(f['views_30d'])} views aaye.")
    if f.get("active_offer"):
        return L(h, f"Your live offer is \"{f['active_offer']}\".", f"Aapka live offer \"{f['active_offer']}\" hai.")
    return ""


def generic_draft(ctx: Ctx) -> Draft:
    bits = _payload_bits(ctx)
    topic = human(ctx.kind) if ctx.kind else "your listing"
    if ctx.trigger.get("scope") == "customer":
        h = customer_wants_hinglish(ctx.customer)
        reason = "; ".join(bits)
        body = join(
            greeting(ctx),
            L(h, f"A quick note about your {topic}" + (f" — {reason}." if reason else "."),
              f"Aapke {topic} ke baare mein ek quick note" + (f" — {reason}." if reason else ".")),
            L(h, "Reply 1 to book a visit, or 2 to skip for now.", "Reply 1 — visit book karein, ya 2 — abhi nahi."),
        )
        return Draft(body, "binary", f"Generic customer note for kind '{ctx.kind}' from payload facts.")
    h = hinglish_for(ctx)
    s = salutation(ctx)
    detail = "; ".join(bits)
    body = join(
        L(h, f"{s}, a quick update on {topic}" + (f" — {detail}." if detail else "."),
          f"{s}, {topic} pe ek quick update" + (f" — {detail}." if detail else ".")),
        _metric_line(ctx, h),
        cta_choice(L(h, "get a short action plan for this", "iska short action plan"), "skip", h),
    )
    return Draft(body, "binary", f"Generic composer for kind '{ctx.kind}' using payload and merchant facts.")


def _valid(draft: Draft | None, ctx: Ctx) -> bool:
    if not draft or not draft.body or not draft.body.strip():
        return False
    if re.search(r"\b(None|nan)\b|\{\}|\[\]", draft.body):
        return False
    if ungrounded(draft.body, ctx.facts):
        return False
    if find_taboo(draft.body, taboo_of(ctx)):
        return False
    if ctx.trigger.get("scope") == "customer" and re.search(r"\b(vera|magicpin)\b", draft.body, re.I):
        return False
    return True


def _strip_taboo(text: str, taboo: list[str]) -> str:
    for phrase in find_taboo(text, taboo):
        text = re.sub(re.escape(phrase), "", text, flags=re.I)
    return re.sub(r"\s{2,}", " ", text).strip()


def compose_draft(ctx: Ctx) -> Draft:
    scope = ctx.trigger.get("scope")
    table = CUSTOMER_COMPOSERS if scope == "customer" else MERCHANT_COMPOSERS
    fn = table.get(ctx.kind) or MERCHANT_COMPOSERS.get(ctx.kind) or CUSTOMER_COMPOSERS.get(ctx.kind)
    if fn:
        try:
            d = fn(ctx)
            if _valid(d, ctx):
                return d
            if d:
                log.info("composer %s draft failed validation; using generic", ctx.kind)
        except Exception:  # noqa: BLE001 - any composer failure falls back
            log.exception("composer %s raised; using generic", ctx.kind)
    try:
        d = generic_draft(ctx)
    except Exception:  # noqa: BLE001
        log.exception("generic composer raised")
        name = (ctx.facts.get("merchant_name") or "there")
        d = Draft(f"Hi {name}, a quick update is ready for you. Reply 1 to see it, or 2 to skip.", "binary", "Minimal fallback.")
    d.body = _strip_taboo(d.body, taboo_of(ctx))
    return d


def compose(ctx: Ctx) -> dict:
    t = ctx.trigger
    draft = compose_draft(ctx)
    scope = t.get("scope") or ("customer" if t.get("customer_id") else "merchant")
    tid = str(t.get("id") or "")
    return {
        "conversation_id": f"conv_{tid}",
        "merchant_id": t.get("merchant_id") or (ctx.merchant or {}).get("merchant_id"),
        "customer_id": t.get("customer_id"),
        "send_as": "merchant_on_behalf" if scope == "customer" else "vera",
        "trigger_id": tid,
        "template_name": "vera_ai",
        "template_params": [],
        "body": draft.body,
        "cta": draft.cta,
        "suppression_key": t.get("suppression_key") or f"{t.get('kind')}:{tid}",
        "rationale": draft.rationale,
    }

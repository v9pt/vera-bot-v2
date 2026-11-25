"""Resolve a trigger to its contexts and build a flat fact-sheet of display strings.

The fact-sheet is the only source of numbers, dates and names a composer may use.
Missing source fields produce no key, never "None".
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .grounding import iso_to_display


@dataclass
class Ctx:
    category: dict
    merchant: dict
    trigger: dict
    customer: dict | None
    digest_item: dict | None
    facts: dict[str, str] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return str(self.trigger.get("kind") or "")

    @property
    def payload(self) -> dict:
        p = self.trigger.get("payload")
        return p if isinstance(p, dict) else {}

    @property
    def slug(self) -> str:
        return str(self.category.get("slug") or self.merchant.get("category_slug") or "")


DIGEST_KEYS = ("top_item_id", "digest_item_id", "alert_id", "item_id")


# ---------- formatting ----------

def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not (isinstance(v, float) and math.isnan(v))


def fmt_num(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int):
        return str(v)
    return ("%.2f" % v).rstrip("0").rstrip(".")


def fmt_pct(x: float, signed: bool = False) -> str:
    """0.38 -> '38%', 0.185 -> '18.5%'; signed adds '+' for positives."""
    p = round(x * 100, 1)
    s = ("%.1f" % p)
    if s.endswith(".0"):
        s = s[:-2]
    if signed and p > 0:
        s = "+" + s
    return s + "%"


def fmt_rate(x: float) -> str:
    """CTR-style rates always keep one decimal: 0.03 -> '3.0%'."""
    return "%.1f%%" % round(x * 100, 1)


def human(value) -> str:
    """'6_month_cleaning' -> '6-month cleaning'; 'delivery_late' -> 'delivery late'."""
    s = str(value)
    s = re.sub(r"(\d)_(?=[a-z])", r"\1-", s)
    return s.replace("_", " ").strip()


def clean_person_name(raw: str | None) -> tuple[str | None, str | None]:
    """'Karthik (parent: Sumitra)' -> ('Karthik', 'Sumitra'); '(walk-in, no profile)' -> (None, None)."""
    if not raw:
        return None, None
    raw = str(raw).strip()
    parent = None
    m = re.search(r"\(\s*parent:\s*([^)]+)\)", raw, re.I)
    if m:
        parent = m.group(1).strip()
    name = re.sub(r"\([^)]*\)", "", raw).strip()
    return (name or None), parent


def _good(v) -> bool:
    if v is None or isinstance(v, bool):
        return False
    if isinstance(v, float) and math.isnan(v):
        return False
    if isinstance(v, (dict, list)):
        return False
    return str(v).strip() not in ("", "None", "nan", "null", "{}", "[]")


def _put(facts: dict, key: str, value) -> None:
    if _good(value):
        facts[key] = str(value)


def _payload_value(key: str, v) -> str:
    if _is_num(v):
        if key.endswith("_pct") and abs(v) <= 5:
            return fmt_pct(v, signed=("delta" in key or v < 0))
        return fmt_num(v)
    return str(v)


def _flatten_payload(facts: dict, prefix: str, obj) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten_payload(facts, f"{prefix}_{k}", v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _flatten_payload(facts, f"{prefix}_{i}", v)
    elif _good(obj):
        key = prefix
        facts[key] = _payload_value(key.split("_", 1)[-1], obj)
        if isinstance(obj, str):
            d, t = iso_to_display(obj)
            if d and re.match(r"^\d{4}-\d{2}-\d{2}", obj):
                facts[key + "_date"] = d
                if t:
                    facts[key + "_time"] = t


# ---------- resolve ----------

def find_digest_item(category: dict, payload: dict) -> dict | None:
    items = category.get("digest") or []
    for k in DIGEST_KEYS:
        want = payload.get(k)
        if want:
            for it in items:
                if isinstance(it, dict) and it.get("id") == want:
                    return it
    return None


def resolve(store, trigger: dict) -> Ctx | None:
    if not isinstance(trigger, dict):
        return None
    payload = trigger.get("payload") if isinstance(trigger.get("payload"), dict) else {}
    merchant_id = trigger.get("merchant_id") or payload.get("merchant_id")
    merchant = store.get("merchant", merchant_id) if merchant_id else None
    if not merchant:
        return None
    slug = merchant.get("category_slug") or payload.get("category")
    category = store.get("category", slug) if slug else None
    if not category:
        return None
    customer = store.get("customer", trigger.get("customer_id")) if trigger.get("customer_id") else None
    digest = find_digest_item(category, payload)
    facts = build_facts(category, merchant, trigger, customer, digest)
    return Ctx(category, merchant, trigger, customer, digest, facts)


# ---------- facts ----------

AGG_ALIASES = {
    "lapsed_180d_plus": "lapsed_180d",
    "lapsed_90d_plus": "lapsed_90d",
    "high_risk_adult_count": "high_risk_adults",
    "total_unique_ytd": "customers_ytd",
    "total_active_members": "active_members",
    "chronic_rx_count": "chronic_rx",
}


def build_facts(category: dict, merchant: dict, trigger: dict, customer: dict | None,
                digest_item: dict | None) -> dict[str, str]:
    f: dict[str, str] = {}
    category = category or {}
    merchant = merchant or {}
    trigger = trigger or {}

    # merchant identity
    ident = merchant.get("identity") or {}
    _put(f, "merchant_name", ident.get("name"))
    _put(f, "owner_first_name", ident.get("owner_first_name"))
    _put(f, "city", ident.get("city"))
    _put(f, "locality", ident.get("locality"))
    if _is_num(ident.get("established_year")):
        f["established_year"] = fmt_num(ident["established_year"])

    sub = merchant.get("subscription") or {}
    _put(f, "plan", sub.get("plan"))
    _put(f, "subscription_status", sub.get("status"))
    if _is_num(sub.get("days_remaining")):
        f["sub_days_remaining"] = fmt_num(sub["days_remaining"])

    perf = merchant.get("performance") or {}
    for key in ("views", "calls", "directions", "leads"):
        if _is_num(perf.get(key)):
            f[f"{key}_30d"] = fmt_num(perf[key])
    if _is_num(perf.get("window_days")):
        f["perf_window_days"] = fmt_num(perf["window_days"])
    if _is_num(perf.get("ctr")):
        f["ctr"] = fmt_rate(perf["ctr"])
    for k, v in (perf.get("delta_7d") or {}).items():
        if _is_num(v):
            f[f"{k.replace('_pct', '')}_delta_7d"] = fmt_pct(v, signed=True)

    agg = merchant.get("customer_aggregate") or {}
    for k, v in agg.items():
        if not _is_num(v):
            continue
        val = fmt_pct(v) if k.endswith("_pct") else fmt_num(v)
        f[f"agg_{k}"] = val
        if k in AGG_ALIASES:
            f[AGG_ALIASES[k]] = val

    offers = [o for o in (merchant.get("offers") or []) if isinstance(o, dict) and o.get("status") == "active" and o.get("title")]
    if offers:
        f["active_offer"] = offers[0]["title"]
    if len(offers) > 1:
        f["active_offer_2"] = offers[1]["title"]

    themes = [t for t in (merchant.get("review_themes") or []) if isinstance(t, dict)]
    neg = sorted([t for t in themes if t.get("sentiment") == "neg"], key=lambda t: -(t.get("occurrences_30d") or 0))
    pos = sorted([t for t in themes if t.get("sentiment") == "pos"], key=lambda t: -(t.get("occurrences_30d") or 0))
    if neg:
        _put(f, "review_neg_theme", human(neg[0].get("theme", "")))
        _put(f, "review_neg_quote", neg[0].get("common_quote"))
        if _is_num(neg[0].get("occurrences_30d")):
            f["review_neg_count"] = fmt_num(neg[0]["occurrences_30d"])
    if pos:
        _put(f, "review_pos_theme", human(pos[0].get("theme", "")))
        _put(f, "review_pos_quote", pos[0].get("common_quote"))

    for s in merchant.get("signals") or []:
        m = re.match(r"stale_posts:(\d+)d", str(s))
        if m:
            f["stale_posts_days"] = m.group(1)

    history = [h for h in (merchant.get("conversation_history") or []) if isinstance(h, dict)]
    last_m = [h for h in history if h.get("from") == "merchant" and h.get("body")]
    if last_m:
        f["last_merchant_message"] = str(last_m[-1]["body"])

    # category
    _put(f, "category_name", category.get("display_name"))
    peer = category.get("peer_stats") or {}
    if _is_num(peer.get("avg_ctr")):
        f["peer_ctr"] = fmt_rate(peer["avg_ctr"])
    for k, name in (("avg_views_30d", "peer_views_30d"), ("avg_calls_30d", "peer_calls_30d"),
                    ("avg_rating", "peer_rating"), ("avg_review_count", "peer_review_count"),
                    ("avg_post_freq_days", "peer_post_freq_days")):
        if _is_num(peer.get(k)):
            f[name] = fmt_num(peer[k])
    for k in ("retention_6mo_pct", "retention_3mo_pct"):
        if _is_num(peer.get(k)):
            f[f"peer_{k.replace('_pct', '')}"] = fmt_pct(peer[k])

    # digest item
    if digest_item:
        _put(f, "digest_title", digest_item.get("title"))
        _put(f, "digest_source", digest_item.get("source"))
        _put(f, "digest_summary", digest_item.get("summary"))
        _put(f, "digest_actionable", digest_item.get("actionable"))
        _put(f, "digest_kind", digest_item.get("kind"))
        if _is_num(digest_item.get("trial_n")):
            f["digest_trial_n"] = fmt_num(digest_item["trial_n"])
        if _is_num(digest_item.get("credits")):
            f["digest_credits"] = fmt_num(digest_item["credits"])
        if digest_item.get("patient_segment"):
            f["digest_segment"] = human(digest_item["patient_segment"])
        if digest_item.get("date"):
            d, t = iso_to_display(str(digest_item["date"]))
            if d:
                f["digest_date"] = d
            if t:
                f["digest_time"] = t

    # customer
    if customer:
        cid = customer.get("identity") or {}
        name, parent = clean_person_name(cid.get("name"))
        _put(f, "customer_name", name)
        _put(f, "customer_parent", parent)
        _put(f, "customer_language", cid.get("language_pref"))
        rel = customer.get("relationship") or {}
        if rel.get("last_visit"):
            d, _ = iso_to_display(str(rel["last_visit"]))
            if d:
                f["customer_last_visit"] = d
        if _is_num(rel.get("visits_total")):
            f["customer_visits"] = fmt_num(rel["visits_total"])

    # trigger payload, every scalar as p_<key>, lists/dicts flattened
    payload = trigger.get("payload") if isinstance(trigger.get("payload"), dict) else {}
    for k, v in payload.items():
        _flatten_payload(f, f"p_{k}", v)

    # derived, explicitly computed so composers never do arithmetic in templates
    vn, mv = payload.get("value_now"), payload.get("milestone_value")
    if _is_num(vn) and _is_num(mv) and mv > vn:
        f["milestone_gap"] = fmt_num(mv - vn)

    return {k: v for k, v in f.items() if _good(v)}

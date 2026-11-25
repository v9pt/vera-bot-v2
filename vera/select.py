"""Rank triggers, apply expiry and suppression. Pure functions."""
from __future__ import annotations

from datetime import datetime, timezone

_ORDER = [
    "supply_alert", "regulation_change", "renewal_due", "perf_dip", "active_planning_intent",
    "recall_due", "chronic_refill_due", "winback_eligible", "competitor_opened",
    "review_theme_emerged", "research_digest", "perf_spike", "festival_upcoming",
    "ipl_match_today", "seasonal_perf_dip", "category_seasonal", "gbp_unverified",
    "cde_opportunity", "milestone_reached", "dormant_with_vera", "curious_ask_due",
]
KIND_PRIORITY: dict[str, int] = {k: len(_ORDER) - i for i, k in enumerate(_ORDER)}

MAX_ACTIONS = 20


def _parse(ts: str | None) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_expired(trigger: dict, now_iso: str | None) -> bool:
    """Only ever compares against the caller's `now`; never the server clock."""
    if now_iso is None:
        return False
    now, exp = _parse(now_iso), _parse(trigger.get("expires_at"))
    if now is None or exp is None:
        return False
    return exp < now


def _urgency(t: dict) -> int:
    try:
        return int(t.get("urgency") or 0)
    except (TypeError, ValueError):
        return 0


def _rank(t: dict) -> tuple:
    # higher urgency, then higher kind priority, then lower id wins
    return (-_urgency(t), -KIND_PRIORITY.get(str(t.get("kind")), 0), str(t.get("id")))


def sent_key(t: dict) -> str | None:
    """Suppression is per (merchant, customer, key): category-wide keys must not block other merchants."""
    key = t.get("suppression_key")
    if not key:
        return None
    return f"{t.get('merchant_id') or ''}|{t.get('customer_id') or ''}|{key}"


def choose(triggers: list[dict], sent_keys: set[str], now_iso: str | None) -> list[dict]:
    live = []
    for t in triggers:
        if not isinstance(t, dict):
            continue
        if is_expired(t, now_iso):
            continue
        key = sent_key(t)
        if key and key in sent_keys:
            continue
        live.append(t)

    best_merchant: dict[str, dict] = {}
    customer: dict[tuple, dict] = {}
    for t in sorted(live, key=_rank):
        if t.get("scope") == "customer":
            k = (t.get("merchant_id"), t.get("customer_id"), t.get("kind"))
            customer.setdefault(k, t)
        else:
            best_merchant.setdefault(str(t.get("merchant_id")), t)

    out = list(best_merchant.values()) + list(customer.values())
    out.sort(key=lambda t: (-_urgency(t), str(t.get("id"))))
    return out[:MAX_ACTIONS]

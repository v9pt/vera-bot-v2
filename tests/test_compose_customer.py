import json
import pathlib
import re

import pytest

from vera.compose_customer import CUSTOMER_COMPOSERS
from vera.facts import resolve
from vera.grounding import ungrounded

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
TRIGGERS = [t for t in json.loads((DATA / "triggers_seed.json").read_text())["triggers"] if t["scope"] == "customer"]


@pytest.fixture(params=TRIGGERS, ids=[t["id"] for t in TRIGGERS])
def cctx(request, loaded_store):
    ctx = resolve(loaded_store, request.param)
    d = CUSTOMER_COMPOSERS[ctx.kind](ctx)
    assert d is not None
    return ctx, d


def test_opens_with_merchant_intro(cctx):
    ctx, d = cctx
    assert re.match(rf"Hi [^,]+, (?:(?:Dr\. )?\w+ from )?{re.escape(ctx.facts['merchant_name'])} here\.", d.body)


def test_owner_named_unless_in_shop_name(cctx):
    ctx, d = cctx
    owner, shop = ctx.facts.get("owner_first_name"), ctx.facts["merchant_name"]
    if owner and owner.lower() not in shop.lower():
        assert f"{owner} from {shop} here." in d.body
    else:
        assert f" from {shop}" not in d.body


def test_no_vera_or_magicpin(cctx):
    assert not re.search(r"vera|magicpin", cctx[1].body, re.I)


def test_grounded(cctx):
    ctx, d = cctx
    assert ungrounded(d.body, ctx.facts) == []


def test_under_80_words(cctx):
    assert len(cctx[1].body.split()) < 80


def test_slot_labels_from_payload(loaded_store, seed_triggers):
    ctx = resolve(loaded_store, seed_triggers["trg_003_recall_due_priya"])
    body = CUSTOMER_COMPOSERS["recall_due"](ctx).body
    assert "Wed 5 Nov, 6pm" in body and "Thu 6 Nov, 5pm" in body


def test_child_customer_addresses_parent(loaded_store, seed_triggers):
    ctx = resolve(loaded_store, seed_triggers["trg_017_kids_yoga_trial_followup_karthik"])
    body = CUSTOMER_COMPOSERS["trial_followup"](ctx).body
    assert body.startswith("Hi Sumitra,") and "(parent" not in body


def test_price_only_from_active_offer(loaded_store, seed_triggers):
    for t in seed_triggers.values():
        if t["scope"] != "customer":
            continue
        ctx = resolve(loaded_store, t)
        body = CUSTOMER_COMPOSERS[ctx.kind](ctx).body
        for price in re.findall(r"₹[\d,]+", body):
            assert any(price in ctx.facts.get(k, "") for k in ("active_offer", "active_offer_2")), (t["id"], price)


def test_missing_customer_context_still_composes(seed_categories, seed_merchants, seed_triggers):
    from vera.compose import compose
    from vera.store import Store
    s = Store()
    s.put("category", "dentists", 1, seed_categories["dentists"])
    s.put("merchant", "m_001_drmeera_dentist_delhi", 1, seed_merchants["m_001_drmeera_dentist_delhi"])
    ctx = resolve(s, seed_triggers["trg_003_recall_due_priya"])
    a = compose(ctx)
    assert a["body"].startswith("Hi, Dr. Meera's Dental Clinic here.")
    assert a["send_as"] == "merchant_on_behalf"


def test_no_customer_context_uses_merchant_language(loaded_store):
    """The judge pushes no customer contexts; fall back to the merchant's Hinglish rule."""
    t = next(t for t in TRIGGERS if t["id"] == "trg_003_recall_due_priya")
    ctx = resolve(loaded_store, t)
    ctx.customer = None
    body = CUSTOMER_COMPOSERS[ctx.kind](ctx).body
    assert body.startswith("Hi, ")
    assert "Reply 1 — " in body  # Hinglish CTA, merchant speaks en+hi

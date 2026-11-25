import copy

import pytest

from tests.helpers import cta_count, distinct_fact_values
from vera.compose_merchant import MERCHANT_COMPOSERS
from vera.facts import resolve
from vera.grounding import ungrounded
from vera.store import Store
from vera.voice import find_taboo, salutation, taboo_of, cta_choice, wants_hinglish, clean_taboo
import json, pathlib

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
TRIGGERS = [t for t in json.loads((DATA / "triggers_seed.json").read_text())["triggers"] if t["scope"] == "merchant"]


@pytest.fixture(params=TRIGGERS, ids=[t["id"] for t in TRIGGERS])
def mctx(request, loaded_store):
    ctx = resolve(loaded_store, request.param)
    draft = MERCHANT_COMPOSERS[ctx.kind](ctx)
    assert draft is not None
    return ctx, draft


def test_every_seed_merchant_kind_has_composer():
    assert {t["kind"] for t in TRIGGERS} <= set(MERCHANT_COMPOSERS)


def test_body_grounded(mctx):
    ctx, d = mctx
    assert ungrounded(d.body, ctx.facts) == []


def test_single_cta(mctx):
    assert cta_count(mctx[1].body) == 1


def test_no_taboo(mctx):
    ctx, d = mctx
    assert find_taboo(d.body, taboo_of(ctx)) == []


def test_greets_with_salutation(mctx):
    ctx, d = mctx
    assert d.body.startswith(salutation(ctx))


def test_not_generic(mctx):
    ctx, d = mctx
    assert distinct_fact_values(d.body, ctx.facts) >= 2


def test_no_internal_jargon(mctx):
    body = mctx[1].body.lower()
    for word in ("trigger", "payload", "suppression", "magicpin api", "none", "nan"):
        assert word not in body.split()


def test_dentist_salutation(loaded_store, seed_triggers):
    ctx = resolve(loaded_store, seed_triggers["trg_001_research_digest_dentists"])
    assert salutation(ctx) == "Dr. Meera"


def test_cta_choice_format():
    assert cta_choice("a", "b", False) == "Reply 1 to a, or 2 to b."
    assert "ya 2" in cta_choice("a", "b", True)


def test_wants_hinglish(seed_merchants):
    assert wants_hinglish(seed_merchants["m_001_drmeera_dentist_delhi"])
    assert not wants_hinglish(seed_merchants["m_008_zenyoga_gym_chennai"])


def test_clean_taboo_raises_on_parenthetical_entry():
    with pytest.raises(ValueError):
        clean_taboo("This is FDA-approved now", ["FDA-approved (use only when actually applicable)"])
    assert clean_taboo("all fine", ["miracle"]) == "all fine"


@pytest.mark.parametrize("tid", [t["id"] for t in TRIGGERS])
def test_sparse_merchant_no_none_text(tid, seed_categories, seed_merchants, seed_triggers):
    from vera.compose import compose
    t = copy.deepcopy(seed_triggers[tid])
    m = copy.deepcopy(seed_merchants[t["merchant_id"]])
    for k in ("performance", "offers", "signals", "conversation_history", "customer_aggregate", "review_themes"):
        m.pop(k, None)
    s = Store()
    s.put("category", m["category_slug"], 1, seed_categories[m["category_slug"]])
    s.put("merchant", m["merchant_id"], 1, m)
    ctx = resolve(s, t)
    body = compose(ctx)["body"]
    assert ungrounded(body, ctx.facts) == []
    for bad in ("None", "{}", "nan", "[]"):
        assert bad not in body
    assert cta_count(body) == 1

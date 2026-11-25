from vera import compose as compose_mod
from vera.compose import compose
from vera.facts import resolve
from vera.grounding import ungrounded


def test_all_25_seed_triggers_compose(loaded_store, seed_triggers):
    for t in seed_triggers.values():
        ctx = resolve(loaded_store, t)
        a = compose(ctx)
        assert a["body"].strip(), t["id"]
        assert a["send_as"] in ("vera", "merchant_on_behalf")
        assert a["suppression_key"] == t["suppression_key"]
        assert a["conversation_id"] == f"conv_{t['id']}"
        assert ungrounded(a["body"], ctx.facts) == [], (t["id"], a["body"])
        assert "generic" not in a["rationale"].lower(), t["id"]


def _unknown(store):
    return {"id": "trg_x", "scope": "merchant", "kind": "new_kind_x", "merchant_id": "m_001_drmeera_dentist_delhi",
            "payload": {"foo": 7}, "urgency": 2, "suppression_key": "x:1"}


def test_unknown_kind_uses_generic(loaded_store):
    ctx = resolve(loaded_store, _unknown(loaded_store))
    a = compose(ctx)
    assert "7" in a["body"]
    assert ungrounded(a["body"], ctx.facts) == []
    assert a["body"].startswith("Dr. Meera")


def test_unknown_customer_kind_generic(loaded_store):
    t = {"id": "trg_y", "scope": "customer", "kind": "brand_new", "merchant_id": "m_001_drmeera_dentist_delhi",
         "customer_id": "c_002_rohit_for_m001", "payload": {"points": 120, "tier": "gold"}, "suppression_key": "y"}
    ctx = resolve(loaded_store, t)
    a = compose(ctx)
    assert a["body"].startswith("Hi Rohit, Dr. Meera's Dental Clinic here.")
    assert "120" in a["body"] and "vera" not in a["body"].lower()
    assert ungrounded(a["body"], ctx.facts) == []


def test_deterministic(loaded_store, seed_triggers):
    for t in seed_triggers.values():
        assert compose(resolve(loaded_store, t)) == compose(resolve(loaded_store, t))


def test_customer_scope_sends_on_behalf(loaded_store, seed_triggers):
    a = compose(resolve(loaded_store, seed_triggers["trg_003_recall_due_priya"]))
    assert a["send_as"] == "merchant_on_behalf" and a["customer_id"] == "c_001_priya_for_m001"


def test_composer_exception_falls_back(loaded_store, seed_triggers, monkeypatch):
    def boom(ctx):
        raise RuntimeError("x")
    monkeypatch.setitem(compose_mod.MERCHANT_COMPOSERS, "perf_dip", boom)
    ctx = resolve(loaded_store, seed_triggers["trg_004_perf_dip_bharat"])
    a = compose(ctx)
    assert a["body"] and "generic" in a["rationale"].lower()
    assert ungrounded(a["body"], ctx.facts) == []

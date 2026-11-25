from vera.facts import build_facts, clean_person_name, resolve
from vera.grounding import ungrounded


def test_digest_item_resolved_for_trg_001(loaded_store, seed_triggers):
    ctx = resolve(loaded_store, seed_triggers["trg_001_research_digest_dentists"])
    assert "fluoride varnish" in ctx.facts["digest_title"]
    assert ctx.facts["digest_source"] == "JIDA Oct 2026, p.14"
    assert ctx.facts["digest_trial_n"] == "2100"


def test_alert_id_resolves_digest(loaded_store, seed_triggers):
    ctx = resolve(loaded_store, seed_triggers["trg_018_supply_atorvastatin_recall"])
    assert ctx.digest_item and ctx.digest_item["id"] == "d_2026W17_atorvastatin_recall"


def test_facts_formatting(loaded_store, seed_triggers):
    ctx = resolve(loaded_store, seed_triggers["trg_001_research_digest_dentists"])
    assert ctx.facts["ctr"] == "2.1%"
    assert ctx.facts["peer_ctr"] == "3.0%"
    assert ctx.facts["lapsed_180d"] == "78"
    assert ctx.facts["views_delta_7d"] == "+18%"
    assert ctx.facts["high_risk_adults"] == "124"
    assert ctx.facts["active_offer"] == "Dental Cleaning @ ₹299"


def test_payload_flattening(loaded_store, seed_triggers):
    f = resolve(loaded_store, seed_triggers["trg_003_recall_due_priya"]).facts
    assert f["p_available_slots_0_label"] == "Wed 5 Nov, 6pm"
    assert f["customer_name"] == "Priya"
    f4 = resolve(loaded_store, seed_triggers["trg_004_perf_dip_bharat"]).facts
    assert f4["p_delta_pct"] == "-50%"
    f2 = resolve(loaded_store, seed_triggers["trg_002_compliance_dci_radiograph"]).facts
    assert f2["p_deadline_iso_date"] == "15 Dec"
    assert ungrounded("by 15 Dec", f2) == []


def test_missing_merchant_returns_none(loaded_store):
    assert resolve(loaded_store, {"id": "x", "merchant_id": "nope", "kind": "perf_dip", "payload": {}}) is None


def test_missing_category_returns_none(seed_merchants):
    from vera.store import Store
    s = Store()
    mid = "m_001_drmeera_dentist_delhi"
    s.put("merchant", mid, 1, seed_merchants[mid])
    assert resolve(s, {"id": "x", "merchant_id": mid, "kind": "perf_dip", "payload": {}}) is None


def test_no_none_strings_in_facts(loaded_store, seed_triggers):
    for t in seed_triggers.values():
        ctx = resolve(loaded_store, t)
        assert ctx is not None, t["id"]
        for k, v in ctx.facts.items():
            assert v not in ("None", "nan", "{}", "[]", ""), (t["id"], k)


def test_sparse_merchant_facts():
    m = {"merchant_id": "m", "category_slug": "dentists", "identity": {"name": "X"}}
    f = build_facts({}, m, {"payload": {}}, None, None)
    assert f == {"merchant_name": "X"}


def test_clean_person_name():
    assert clean_person_name("Karthik (parent: Sumitra)") == ("Karthik", "Sumitra")
    assert clean_person_name("(walk-in, no profile)") == (None, None)

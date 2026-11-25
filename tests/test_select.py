from vera.select import KIND_PRIORITY, choose, is_expired, sent_key


def test_one_merchant_trigger_per_merchant(seed_triggers):
    out = choose(list(seed_triggers.values()), set(), None)
    ids = [t["id"] for t in out]
    assert "trg_002_compliance_dci_radiograph" in ids
    assert "trg_001_research_digest_dentists" not in ids
    merchant_scope = [t["merchant_id"] for t in out if t["scope"] == "merchant"]
    assert len(merchant_scope) == len(set(merchant_scope))
    assert "trg_003_recall_due_priya" in ids  # customer sends are separate


def test_expiry_ignored_without_now(seed_triggers):
    assert not is_expired(seed_triggers["trg_010_ipl_match_delhi"], None)


def test_expiry_applied_with_now(seed_triggers):
    t = seed_triggers["trg_010_ipl_match_delhi"]
    assert is_expired(t, "2026-11-25T00:00:00Z")
    assert not is_expired(t, "2026-04-26T10:00:00+05:30")


def test_sent_key_suppressed(seed_triggers):
    t = seed_triggers["trg_002_compliance_dci_radiograph"]
    assert choose([t], {sent_key(t)}, None) == []


def test_cap_20():
    ts = [{"id": f"t{i:02d}", "scope": "merchant", "kind": "perf_dip", "merchant_id": f"m{i}",
           "urgency": 1, "suppression_key": f"k{i}"} for i in range(30)]
    assert len(choose(ts, set(), None)) == 20


def test_deterministic_order(seed_triggers):
    a = [t["id"] for t in choose(list(seed_triggers.values()), set(), None)]
    b = [t["id"] for t in choose(list(reversed(list(seed_triggers.values()))), set(), None)]
    assert a == b
    urg = [t["urgency"] for t in choose(list(seed_triggers.values()), set(), None)]
    assert urg == sorted(urg, reverse=True)


def test_priority_covers_seed_merchant_kinds(seed_triggers):
    for t in seed_triggers.values():
        if t["scope"] == "merchant":
            assert t["kind"] in KIND_PRIORITY


def test_shared_key_does_not_block_other_merchant(seed_triggers):
    a = dict(seed_triggers["trg_001_research_digest_dentists"])
    b = dict(a, id="trg_001b", merchant_id="m_002_bharat_dentist_mumbai")
    assert a["suppression_key"] == b["suppression_key"]
    assert [t["id"] for t in choose([a, b], {sent_key(a)}, None)] == ["trg_001b"]

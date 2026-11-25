import json
import time

import pytest
from fastapi.testclient import TestClient

import app as app_module
from vera.store import store


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("LLM_POLISH", raising=False)
    store.clear()
    yield TestClient(app_module.app)
    store.clear()


def push(c, scope, cid, payload, version=1):
    return c.post("/v1/context", json={"scope": scope, "context_id": cid, "version": version, "payload": payload})


def push_seed(c, cats, merchants, triggers, customers=None):
    for slug, cat in cats.items():
        assert push(c, "category", slug, cat).json()["accepted"]
    for mid, m in merchants.items():
        push(c, "merchant", mid, m)
    for cid, cu in (customers or {}).items():
        push(c, "customer", cid, cu)
    for tid, t in triggers.items():
        push(c, "trigger", tid, t)


def test_healthz(client):
    r = client.get("/v1/healthz").json()
    assert r["status"] == "ok" and isinstance(r["uptime_seconds"], int)
    assert set(r["contexts_loaded"]) == {"category", "merchant", "customer", "trigger"}


def test_metadata_fields(client):
    r = client.get("/v1/metadata").json()
    for k in ("team_name", "team_members", "model", "approach", "version"):
        assert r[k]
    assert r["version"] == "2.0"


def test_context_same_version_twice_ok(client):
    assert push(client, "merchant", "m1", {"a": 1}).json()["accepted"]
    assert push(client, "merchant", "m1", {"a": 1}).json()["accepted"]


def test_context_stale_rejected(client):
    push(client, "merchant", "m1", {}, version=3)
    r = push(client, "merchant", "m1", {}, version=2)
    assert r.status_code == 409 and r.json()["current_version"] == 3


def test_context_invalid_scope_400(client):
    assert push(client, "bogus", "x", {}).status_code == 400


def test_context_oversize_413(client):
    r = push(client, "merchant", "big", {"blob": "x" * (600 * 1024)})
    assert r.status_code == 413


def test_tick_returns_actions_for_seed(client, seed_categories, seed_merchants, seed_customers, seed_triggers):
    push_seed(client, seed_categories, seed_merchants, seed_triggers, seed_customers)
    r = client.post("/v1/tick", json={"available_triggers": list(seed_triggers)}).json()
    actions = r["actions"]
    assert 1 <= len(actions) <= 20
    ms = [a["merchant_id"] for a in actions if a["send_as"] == "vera"]
    assert len(ms) == len(set(ms)) == len({t["merchant_id"] for t in seed_triggers.values() if t["scope"] == "merchant"})
    for a in actions:
        assert a["body"] and a["template_name"] == "vera_ai"


def test_tick_with_real_now_still_serves_named_triggers(client, seed_categories, seed_merchants, seed_customers, seed_triggers):
    push_seed(client, seed_categories, seed_merchants, seed_triggers, seed_customers)
    r = client.post("/v1/tick", json={"now": "2026-11-25T10:00:00Z", "available_triggers": list(seed_triggers)}).json()
    assert len(r["actions"]) >= 10


def test_tick_without_ids_applies_expiry(client, seed_categories, seed_merchants, seed_customers, seed_triggers):
    push_seed(client, seed_categories, seed_merchants, seed_triggers, seed_customers)
    r = client.post("/v1/tick", json={"now": "2026-11-25T10:00:00Z"}).json()
    ids = {a["trigger_id"] for a in r["actions"]}
    assert "trg_010_ipl_match_delhi" not in ids
    assert "trg_002_compliance_dci_radiograph" in ids


def test_tick_skips_trigger_without_merchant(client, seed_categories, seed_merchants, seed_triggers):
    push_seed(client, seed_categories, {k: v for k, v in seed_merchants.items() if k != "m_002_bharat_dentist_mumbai"}, seed_triggers)
    r = client.post("/v1/tick", json={"available_triggers": list(seed_triggers)}).json()
    assert r["actions"]
    assert all(a["merchant_id"] != "m_002_bharat_dentist_mumbai" for a in r["actions"])


def test_tick_unknown_ids_ok(client):
    r = client.post("/v1/tick", json={"available_triggers": ["nope"]})
    assert r.status_code == 200 and r.json() == {"actions": []}


def test_tick_merchant_only_payload(client, seed_categories, seed_merchants):
    push(client, "category", "dentists", seed_categories["dentists"])
    push(client, "merchant", "m_001_drmeera_dentist_delhi", seed_merchants["m_001_drmeera_dentist_delhi"])
    r = client.post("/v1/tick", json={"merchant_id": "m_001_drmeera_dentist_delhi"}).json()
    assert len(r["actions"]) == 1 and r["actions"][0]["body"].startswith("Dr. Meera")


def test_tick_suppression(client, seed_categories, seed_merchants, seed_customers, seed_triggers):
    push_seed(client, seed_categories, seed_merchants, seed_triggers, seed_customers)
    ids = ["trg_002_compliance_dci_radiograph", "trg_004_perf_dip_bharat"]
    assert client.post("/v1/tick", json={"available_triggers": ids}).json()["actions"]
    assert client.post("/v1/tick", json={"available_triggers": ids}).json()["actions"] == []


def test_tick_under_2_seconds_rule_only(client, seed_categories, seed_merchants, seed_customers, seed_triggers):
    push_seed(client, seed_categories, seed_merchants, seed_triggers, seed_customers)
    t0 = time.time()
    client.post("/v1/tick", json={"available_triggers": list(seed_triggers)})
    assert time.time() - t0 < 2


def test_judge_phase2_short_shape(client, seed_categories, seed_merchants, seed_triggers):
    """Judge pushes 5 merchants, no customers, then ticks the first 3 triggers."""
    push_seed(client, seed_categories, dict(list(seed_merchants.items())[:5]), {})
    first3 = list(seed_triggers)[:3]
    for tid in first3:
        push(client, "trigger", tid, seed_triggers[tid])
    actions = client.post("/v1/tick", json={"now": "2026-11-25T10:00:00Z", "available_triggers": first3}).json()["actions"]
    assert {a["trigger_id"] for a in actions} == {"trg_002_compliance_dci_radiograph", "trg_003_recall_due_priya"}


@pytest.mark.parametrize("path", ["/v1/debug", "/v1/sample", "/v1/check", "/v1/all_merchants", "/v1/merchant/0", "/v1/simulate/0"])
def test_removed_endpoints_404(client, path):
    assert client.get(path).status_code == 404


def test_teardown_clears(client):
    push(client, "merchant", "m1", {})
    client.post("/v1/teardown")
    assert client.get("/v1/healthz").json()["contexts_loaded"]["merchant"] == 0


def test_shared_suppression_key_across_ticks(client, seed_categories, seed_merchants, seed_triggers):
    push_seed(client, seed_categories, seed_merchants, {})
    a = seed_triggers["trg_001_research_digest_dentists"]
    b = dict(a, id="trg_001b", merchant_id="m_002_bharat_dentist_mumbai")
    push(client, "trigger", a["id"], a)
    push(client, "trigger", b["id"], b)
    assert len(client.post("/v1/tick", json={"available_triggers": [a["id"]]}).json()["actions"]) == 1
    assert len(client.post("/v1/tick", json={"available_triggers": [b["id"]]}).json()["actions"]) == 1


def test_merchant_only_tick_with_real_now_falls_back_to_checkin(client, seed_categories, seed_merchants, seed_triggers):
    push_seed(client, seed_categories, seed_merchants, seed_triggers)
    mid = "m_005_pizzajunction_restaurant_delhi"
    actions = client.post("/v1/tick", json={"now": "2026-11-25T10:00:00Z", "merchant_id": mid}).json()["actions"]
    assert len(actions) == 1 and actions[0]["merchant_id"] == mid


def test_healthz_responsive_during_slow_tick(client, seed_categories, seed_merchants, seed_triggers, monkeypatch):
    import threading
    push_seed(client, seed_categories, seed_merchants, seed_triggers)
    monkeypatch.setattr(app_module, "polish_enabled", lambda: True)
    monkeypatch.setattr(app_module, "polish_all", lambda actions, ctxs, d: (time.sleep(1.5), actions)[1])
    th = threading.Thread(target=lambda: client.post("/v1/tick", json={"available_triggers": list(seed_triggers)}))
    th.start()
    time.sleep(0.3)
    t0 = time.time()
    assert client.get("/v1/healthz").status_code == 200
    assert time.time() - t0 < 1.0
    th.join()

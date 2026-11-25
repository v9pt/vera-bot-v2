from vera.store import Store


def test_same_version_is_idempotent():
    s = Store()
    assert s.put("merchant", "m1", 1, {"a": 1})["accepted"]
    assert s.put("merchant", "m1", 1, {"a": 1})["accepted"]


def test_lower_version_rejected_with_current_version():
    s = Store()
    s.put("merchant", "m1", 3, {})
    r = s.put("merchant", "m1", 2, {})
    assert r == {"accepted": False, "reason": "stale_version", "current_version": 3}


def test_higher_version_replaces():
    s = Store()
    s.put("merchant", "m1", 1, {"a": 1})
    assert s.put("merchant", "m1", 2, {"a": 2})["accepted"]
    assert s.get("merchant", "m1") == {"a": 2}


def test_invalid_scope():
    r = Store().put("bogus", "x", 1, {})
    assert r["accepted"] is False and r["reason"] == "invalid_scope"


def test_versions_are_per_scope_and_id():
    s = Store()
    s.put("merchant", "a", 5, {})
    assert s.put("trigger", "a", 1, {})["accepted"]


def test_get_returns_copy_not_alias():
    s = Store()
    s.put("category", "c", 1, {"x": {"y": 1}})
    got = s.get("category", "c")
    got["x"]["y"] = 99
    assert s.get("category", "c") == {"x": {"y": 1}}


def test_ack_fields_and_clear():
    s = Store()
    r = s.put("merchant", "m1", 1, {})
    assert r["ack_id"] and r["stored_at"]
    s.sent_keys.add("k")
    s.clear()
    assert s.get("merchant", "m1") is None and not s.sent_keys

import time
from unittest.mock import MagicMock, patch

import pytest

from vera import polish as P
from vera.compose import compose
from vera.facts import resolve

FACTS = {"ctr": "2.1%", "peer_ctr": "3.0%", "name": "Dr. Meera"}
BODY = "Dr. Meera, your CTR is 2.1% vs 3.0% for peers. Reply 1 to fix it, or 2 to skip."


def gemini_resp(text):
    m = MagicMock()
    m.raise_for_status.return_value = None
    m.json.return_value = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return m


@pytest.fixture(autouse=True)
def env(monkeypatch):
    P._cache.clear()
    monkeypatch.setenv("LLM_POLISH", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


def test_disabled_returns_original(monkeypatch):
    monkeypatch.setenv("LLM_POLISH", "0")
    with patch("vera.polish.requests.post") as post:
        assert P.polish(BODY, FACTS, [], False, "k") == BODY
        post.assert_not_called()


def test_valid_rewrite_accepted():
    new = "Dr. Meera, quick one: CTR sits at 2.1% while peers are at 3.0%. Reply 1 to fix it, or 2 to skip."
    with patch("vera.polish.requests.post", return_value=gemini_resp(new)):
        assert P.polish(BODY, FACTS, [], False, "k1") == new


def test_invented_number_rejected():
    bad = "Dr. Meera, CTR 2.1% vs 3.0% — that's 28% fewer patients. Reply 1 to fix it, or 2 to skip."
    with patch("vera.polish.requests.post", return_value=gemini_resp(bad)):
        assert P.polish(BODY, FACTS, [], False, "k2") == BODY


def test_taboo_rejected():
    bad = "Dr. Meera, guaranteed fix: CTR 2.1% vs 3.0%. Reply 1 to fix it, or 2 to skip."
    with patch("vera.polish.requests.post", return_value=gemini_resp(bad)):
        assert P.polish(BODY, FACTS, ["guaranteed"], False, "k3") == BODY


def test_timeout_returns_original():
    import requests
    with patch("vera.polish.requests.post", side_effect=requests.Timeout()):
        assert P.polish(BODY, FACTS, [], False, "k4") == BODY


def test_cache_makes_second_call_free():
    new = "Dr. Meera, CTR is 2.1% against 3.0% for peers. Reply 1 to fix it, or 2 to skip."
    with patch("vera.polish.requests.post", return_value=gemini_resp(new)) as post:
        P.polish(BODY, FACTS, [], False, "same")
        P.polish(BODY, FACTS, [], False, "same")
        assert post.call_count == 1


def test_extra_reply_option_rejected():
    bad = "Dr. Meera, CTR 2.1% vs 3.0%. Reply 3 for a call. Reply 1 to fix it, or 2 to skip."
    with patch("vera.polish.requests.post", return_value=gemini_resp(bad)):
        assert P.polish(BODY, FACTS, [], False, "k5") == BODY


def test_changed_cta_rejected():
    bad = "Dr. Meera, CTR 2.1% vs 3.0%. Want me to fix it?"
    with patch("vera.polish.requests.post", return_value=gemini_resp(bad)):
        assert P.polish(BODY, FACTS, [], False, "k6") == BODY


def test_groq_fallback_used_when_gemini_fails(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    new = "Dr. Meera, CTR is 2.1%, peers 3.0%. Reply 1 to fix it, or 2 to skip."
    groq = MagicMock()
    groq.raise_for_status.return_value = None
    groq.json.return_value = {"choices": [{"message": {"content": new}}]}

    def fake(url, **kw):
        if "googleapis" in url:
            raise RuntimeError("down")
        return groq
    with patch("vera.polish.requests.post", side_effect=fake):
        assert P.polish(BODY, FACTS, [], False, "k7") == new


def test_deadline_ships_rule_drafts(loaded_store, seed_triggers):
    ctxs, actions = {}, []
    for tid in list(seed_triggers)[:4]:
        ctx = resolve(loaded_store, seed_triggers[tid])
        a = compose(ctx)
        actions.append(a)
        ctxs[a["trigger_id"]] = ctx

    def slow(*a, **k):
        time.sleep(1.0)
        return gemini_resp("x")
    with patch("vera.polish.requests.post", side_effect=slow):
        t0 = time.time()
        out = P.polish_all(actions, ctxs, deadline_s=0.2)
        assert time.time() - t0 < 0.8
    assert [a["body"] for a in out] == [a["body"] for a in actions]

import time

import pytest

from vera.reply import classify, handle_reply
from vera.store import Store

AUTO = "Thank you for contacting us! Our team will respond shortly."
QUALIFYING = ["would you", "do you", "what if", "how about", "can you tell"]


@pytest.fixture()
def s(seed_categories, seed_merchants):
    st = Store()
    st.put("category", "dentists", 1, seed_categories["dentists"])
    st.put("merchant", "m_001_drmeera_dentist_delhi", 1, seed_merchants["m_001_drmeera_dentist_delhi"])
    return st


def r(store, msg, conv="conv_x", mid="m_001_drmeera_dentist_delhi", turn=2):
    return handle_reply(store, {"conversation_id": conv, "merchant_id": mid, "message": msg, "turn_number": turn})


def test_auto_reply_escalation(s):
    assert [r(s, AUTO)["action"] for _ in range(4)] == ["send", "wait", "end", "end"]


def test_auto_reply_escalates_across_rotating_conversation_ids(s):
    acts = [r(s, AUTO, conv=f"conv_auto_{i}")["action"] for i in range(1, 5)]
    assert acts[:3] == ["send", "wait", "end"]


def test_hostile_ends(s):
    assert r(s, "Stop messaging me. This is useless spam.")["action"] == "end"


def test_hinglish_hostile_ends(s):
    assert r(s, "band karo ye messages")["action"] == "end"
    assert classify("mat bhejo") == "hostile"


def test_hinglish_auto_reply_detected():
    assert classify("Aapki jaankari ke liye bahut-bahut shukriya, hum jald hi sampark karenge") == "auto_reply"


def test_commit_switches_to_action(s):
    out = r(s, "Ok lets do it. Whats next?")
    body = out["body"].lower()
    assert out["action"] == "send"
    assert not any(q in body for q in QUALIFYING)
    assert "done" in body or "drafting" in body


def test_hinglish_commit(s):
    assert classify("haan kar do") == "commit" and classify("theek hai") == "commit"


def test_objection_sends_once_then_waits(s):
    first = r(s, "Too expensive, not now")
    assert first["action"] == "send" and first["body"].count("Reply") == 1
    assert "2,410" in first["body"] or "2410" in first["body"]
    assert r(s, "baad mein, time nahi")["action"] == "wait"


def test_off_topic_steers_back(s):
    out = r(s, "who will win the IPL?")
    assert out["action"] == "send" and out["body"].count("Reply") == 1
    for team in ("CSK", "MI", "RCB", "win"):
        assert team not in out["body"]


def test_question_answered_from_facts(s):
    out = r(s, "how many calls did I get?")
    assert out["action"] == "send" and "18" in out["body"]


def test_reply_without_any_context():
    out = handle_reply(Store(), {"conversation_id": "conv_new", "merchant_id": "ghost", "message": "Ok lets do it. Whats next?"})
    assert out["action"] == "send" and "None" not in out["body"]


def test_reply_under_5s(s):
    t0 = time.time()
    for msg in (AUTO, "yes", "why?", "hmm", "Stop"):
        r(s, msg, conv=f"c_{msg}")
    assert time.time() - t0 < 5


def test_state_is_per_conversation(s):
    assert r(s, "Stop", conv="a")["action"] == "end"
    assert r(s, "yes", conv="b")["action"] == "send"
    assert r(s, "yes", conv="a")["action"] == "end"


def test_other_waits(s):
    assert r(s, "hmm")["action"] == "wait"


def test_commit_body_names_trigger_deliverable(s, seed_triggers):
    t = seed_triggers["trg_001_research_digest_dentists"]
    s.put("trigger", t["id"], 1, t)
    out = r(s, "yes", conv=f"conv_{t['id']}")
    assert "patient recall message" in out["body"]
    generic = r(s, "yes", conv="conv_other")["body"]
    assert "draft abhi draft" not in generic and "drafting the draft" not in generic


@pytest.fixture()
def full(loaded_store):
    return loaded_store


def test_customer_reply_2_books_second_slot(full):
    out = r(full, "2", conv="conv_trg_003_recall_due_priya")
    assert out["action"] == "send" and "Thu 6 Nov, 5pm" in out["body"]
    assert "Dr. Meera" not in out["body"] and "2,410" not in out["body"]


def test_customer_reply_1_books_first_slot(full):
    out = r(full, "1", conv="conv_trg_003_recall_due_priya")
    assert "Wed 5 Nov, 6pm" in out["body"] and "Dr. Meera," not in out["body"]


def test_merchant_option_2_acts_on_offered_option(full):
    conv = "conv_trg_004_perf_dip_bharat"
    full.conversations[conv] = [{"from": "bot", "action": "send",
                                 "text": "Dr. Bharat, calls down. Reply 1 to let me refresh, or 2 to see the full breakdown first."}]
    out = r(full, "2", conv=conv, mid="m_002_bharat_dentist_mumbai")
    assert out["action"] == "send" and "see the full breakdown first" in out["body"]
    assert "drop it" not in out["body"]


def test_merchant_option_2_skip_waits(full):
    conv = "conv_trg_012_milestone_mylari"
    full.conversations[conv] = [{"from": "bot", "action": "send", "text": "Suresh, x. Reply 1 to get it, or 2 to skip."}]
    assert r(full, "2", conv=conv, mid="m_006_southindiancafe_restaurant_bangalore")["action"] == "wait"

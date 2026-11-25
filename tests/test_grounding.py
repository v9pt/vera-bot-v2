from vera.grounding import extract_claims, ungrounded


def test_clean_text_has_no_ungrounded():
    facts = {"ctr": "2.1%", "peer_ctr": "3.0%", "views": "2410"}
    assert ungrounded("Your CTR is 2.1% vs 3.0% for peers on 2,410 views.", facts) == []


def test_flags_invented_percent():
    assert ungrounded("28% fewer return patients", {"ctr": "2.1%"}) == ["28%"]


def test_ignores_reply_options():
    text = "Reply 1 to get the draft, or 2 to skip."
    assert extract_claims(text) == set()
    assert ungrounded("Reply 1 for Wed 5 Nov, 6pm, 2 for Thu 6 Nov, 5pm.",
                      {"a": "Wed 5 Nov, 6pm", "b": "Thu 6 Nov, 5pm"}) == []


def test_thousands_separator_equivalence():
    assert ungrounded("2,410 views", {"views": "2410"}) == []
    assert ungrounded("2410 views", {"views": "2,410"}) == []


def test_fraction_and_percent_agree():
    assert ungrounded("CTR 0.021", {"ctr": "2.1%"}) == []
    assert ungrounded("calls fell 50%", {"p_delta_pct": "-50%"}) == []


def test_date_in_payload_is_grounded():
    facts = {"p_deadline_iso": "2026-12-15"}
    assert ungrounded("Deadline: 15 Dec.", facts) == []
    assert ungrounded("Deadline: Dec 15.", facts) == []
    assert ungrounded("Deadline: 16 Dec.", facts) == ["16 dec"]


def test_iso_time_grounds_display_time():
    assert ungrounded("Match at 7:30pm", {"t": "2026-04-26T19:30:00+05:30"}) == []

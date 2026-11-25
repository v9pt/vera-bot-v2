import re


def cta_count(body: str) -> int:
    replies = len(re.findall(r"\bReply\b", body))
    trailing_q = 1 if body.rstrip().endswith("?") else 0
    return replies + (trailing_q if replies == 0 else 0)


def distinct_fact_values(body: str, facts: dict) -> int:
    return len({v for v in facts.values() if len(v) >= 2 and v in body})

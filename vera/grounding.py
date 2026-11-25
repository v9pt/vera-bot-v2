"""Grounding checker: every number, date and time in a body must come from the facts.

Pure functions, no I/O. Claims are compared on normalised values, so "2,410" matches
"2410", "50%" matches a fact "-50%", and "0.021" matches a fact "2.1%".
"""
from __future__ import annotations

import re

MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"

ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?")
DATE_DM_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MON + r"(?![a-z])", re.I)
DATE_MD_RE = re.compile(r"\b" + _MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\d)", re.I)
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.I)
NUM_RE = re.compile(r"(?<![\d.])([+-]?)(₹|rs\.?\s?)?(\d{1,3}(?:,\d{2,3})+|\d+)(\.\d+)?\s*(%)?", re.I)
# Reply option digits ("Reply 1 to ..., or 2 to ...") are UI, not claims.
REPLY_OPT_RE = re.compile(
    r"(?:\breply\s+|\bor\s+|\bya\s+|,\s*)([1-3])(?=\s*(?:[:=)\-\u2014\u2013])|\s+(?:to|for|se|ke|if|bhejiye|karein)\b|\s*$)",
    re.I | re.M,
)


def norm_num(x: float) -> str:
    x = abs(x)
    if float(x).is_integer():
        return str(int(x))
    return ("%.6f" % x).rstrip("0").rstrip(".")


def _time_str(h: int, m: int) -> str:
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{suffix}" if m else f"{h12}{suffix}"


def iso_to_display(value: str) -> tuple[str | None, str | None]:
    """'2026-11-05T18:00:00+05:30' -> ('5 Nov', '6pm'). Local wall time as written."""
    m = ISO_RE.search(value or "")
    if not m:
        return None, None
    y, mo, d, hh, mm = m.groups()
    try:
        date = f"{int(d)} {MONTHS[int(mo) - 1].capitalize()}"
    except (IndexError, ValueError):
        return None, None
    time = _time_str(int(hh), int(mm)) if hh is not None else None
    return date, time


def _scan(text: str) -> tuple[set[str], set[str], list[tuple[str, str]], str]:
    """Returns (dates, times, numbers[(surface, normalised)], residue_text)."""
    dates: set[str] = set()
    times: set[str] = set()
    t = text or ""

    def _iso(m):
        y, mo, d, hh, mm = m.groups()
        try:
            dates.add(f"{int(d)} {MONTHS[int(mo) - 1]}")
        except (IndexError, ValueError):
            return m.group(0)
        if hh is not None:
            times.add(_time_str(int(hh), int(mm)))
        return " "

    t = ISO_RE.sub(_iso, t)

    def _dm(m):
        dates.add(f"{int(m.group(1))} {m.group(2).lower()[:3]}")
        return " "

    def _md(m):
        dates.add(f"{int(m.group(2))} {m.group(1).lower()[:3]}")
        return " "

    t = DATE_DM_RE.sub(_dm, t)
    t = DATE_MD_RE.sub(_md, t)

    def _tm(m):
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
        times.add(f"{h}:{mi:02d}{ap}" if mi else f"{h}{ap}")
        return " "

    t = TIME_RE.sub(_tm, t)

    nums: list[tuple[str, str]] = []
    for m in NUM_RE.finditer(t):
        sign, cur, intpart, frac, pct = m.groups()
        raw = intpart.replace(",", "") + (frac or "")
        try:
            val = float(raw)
        except ValueError:
            continue
        surface = ("₹" if cur else "") + norm_num(val) + ("%" if pct else "")
        nums.append((surface, norm_num(val)))
    return dates, times, nums, t


def extract_claims(text: str) -> set[str]:
    stripped = REPLY_OPT_RE.sub(lambda m: m.group(0).replace(m.group(1), " "), text or "")
    dates, times, nums, _ = _scan(stripped)
    return dates | times | {s for s, _ in nums}


def allowed_from_facts(facts: dict[str, str]) -> tuple[set[str], set[str], set[str]]:
    dates: set[str] = set()
    times: set[str] = set()
    numbers: set[str] = set()
    for value in (facts or {}).values():
        if value is None:
            continue
        v = str(value)
        d, t, nums, _ = _scan(v)
        dates |= d
        times |= t
        # also keep the raw components of dates/times/identifiers as plain numbers
        for m in re.finditer(r"\d+(?:\.\d+)?", v.replace(",", "")):
            numbers.add(norm_num(float(m.group(0))))
        for surface, n in nums:
            numbers.add(n)
            f = float(n)
            if surface.endswith("%"):
                numbers.add(norm_num(f / 100))
            if 0 < f < 1.5 and not f.is_integer():
                numbers.add(norm_num(f * 100))
    return dates, times, numbers


def ungrounded(text: str, facts: dict[str, str], extra_allowed: set[str] = frozenset()) -> list[str]:
    dates, times, numbers = allowed_from_facts(facts)
    extra = {str(x).lower() for x in extra_allowed}
    bad: list[str] = []
    for claim in sorted(extract_claims(text)):
        c = claim.lower()
        if c in extra:
            continue
        if re.fullmatch(r"\d{1,2} [a-z]{3}", c):
            ok = c in dates
        elif re.fullmatch(r"\d{1,2}(:\d{2})?(am|pm)", c):
            ok = c in times
        else:
            core = c.lstrip("₹").rstrip("%")
            ok = core in numbers or core in extra
        if not ok:
            bad.append(claim)
    return bad

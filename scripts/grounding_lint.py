#!/usr/bin/env python3
"""Compose every seed trigger and fail on ungrounded claims, CTA count or taboo words.

Usage: python scripts/grounding_lint.py   (exit 0 = clean)
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vera.compose import compose  # noqa: E402
from vera.facts import resolve  # noqa: E402
from vera.grounding import ungrounded  # noqa: E402
from vera.store import Store  # noqa: E402
from vera.voice import find_taboo, taboo_of  # noqa: E402


def load_store(data: pathlib.Path) -> tuple[Store, list[dict]]:
    s = Store()
    for f in sorted((data / "categories").glob("*.json")):
        c = json.loads(f.read_text())
        s.put("category", c.get("slug", f.stem), 1, c)
    for name, container, key in (("merchants_seed.json", "merchants", "merchant_id"),
                                 ("customers_seed.json", "customers", "customer_id")):
        for item in json.loads((data / name).read_text())[container]:
            s.put(container.rstrip("s"), item[key], 1, item)
    triggers = json.loads((data / "triggers_seed.json").read_text())["triggers"]
    for t in triggers:
        s.put("trigger", t["id"], 1, t)
    return s, triggers


def cta_count(body: str) -> int:
    n = len(re.findall(r"\bReply\b", body))
    return n if n else (1 if body.rstrip().endswith("?") else 0)


def main() -> int:
    store, triggers = load_store(ROOT / "data")
    problems = []
    for t in triggers:
        ctx = resolve(store, t)
        if ctx is None:
            problems.append((t["id"], "could not resolve merchant/category"))
            continue
        body = compose(ctx)["body"]
        bad = ungrounded(body, ctx.facts)
        if bad:
            problems.append((t["id"], f"ungrounded: {bad}"))
        if cta_count(body) != 1:
            problems.append((t["id"], f"CTA count {cta_count(body)}"))
        taboo = find_taboo(body, taboo_of(ctx))
        if taboo:
            problems.append((t["id"], f"taboo: {taboo}"))
    for tid, msg in problems:
        print(f"FAIL {tid}: {msg}")
    print(f"{len(triggers)} triggers checked, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

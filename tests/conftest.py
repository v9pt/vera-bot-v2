import json
import pathlib

import pytest

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"


def _load(name, container, key):
    data = json.loads((DATA / name).read_text())
    return {item[key]: item for item in data[container]}


@pytest.fixture(scope="session")
def seed_categories():
    out = {}
    for f in sorted((DATA / "categories").glob("*.json")):
        c = json.loads(f.read_text())
        out[c.get("slug", f.stem)] = c
    return out


@pytest.fixture(scope="session")
def seed_merchants():
    return _load("merchants_seed.json", "merchants", "merchant_id")


@pytest.fixture(scope="session")
def seed_customers():
    return _load("customers_seed.json", "customers", "customer_id")


@pytest.fixture(scope="session")
def seed_triggers():
    return _load("triggers_seed.json", "triggers", "id")


@pytest.fixture()
def loaded_store(seed_categories, seed_merchants, seed_customers, seed_triggers):
    """A fresh Store with every seed context pushed at version 1."""
    from vera.store import Store

    s = Store()
    for slug, c in seed_categories.items():
        s.put("category", slug, 1, c)
    for mid, m in seed_merchants.items():
        s.put("merchant", mid, 1, m)
    for cid, c in seed_customers.items():
        s.put("customer", cid, 1, c)
    for tid, t in seed_triggers.items():
        s.put("trigger", tid, 1, t)
    return s

def test_seed_loaded(seed_categories, seed_merchants, seed_customers, seed_triggers):
    assert len(seed_categories) == 5
    assert len(seed_triggers) == 25
    for t in seed_triggers.values():
        assert t["merchant_id"] in seed_merchants

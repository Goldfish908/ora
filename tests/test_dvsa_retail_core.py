from scripts.dvsa_retail_core import (asset_audit, load_assets,
                                      semantic_feedback)


def data():
    return {
        "products": ["A"], "locations": ["s"], "periods": 1,
        "shelf_life": {"A": 3}, "demand_curve": {"A": [10]},
        "demand_share": {"s": 1}, "network": {"sub_edges": []},
    }


def solution():
    return {"I": {"A|s|1|3": 10}, "sales": {"A|s|1|1": 10}, "lost": {}, "sub": {}}


def test_initial_inventory_asset_allows_fresh_bucket_but_rejects_old_stock():
    assets, hashes = load_assets()
    initial = next(asset for asset in assets if asset["asset_id"] == "retailopt.initial_inventory_zero")
    clean = asset_audit([initial], data(), solution())[0]
    wrong_solution = solution()
    wrong_solution["I"]["A|s|1|2"] = 4
    wrong = asset_audit([initial], data(), wrong_solution)[0]
    assert clean["status"] == "SATISFIED"
    assert clean["evaluated"] == 2
    assert wrong["status"] == "VIOLATED"
    assert wrong["violations"][0]["lhs"] == 4
    assert len(hashes) == 2


def test_single_period_shelf_life_has_no_old_buckets():
    assets, _ = load_assets()
    initial = next(asset for asset in assets if asset["asset_id"] == "retailopt.initial_inventory_zero")
    row = data()
    row["shelf_life"]["A"] = 1
    result = asset_audit([initial], row, solution())[0]
    assert result["status"] == "SATISFIED"
    assert result["evaluated"] == 0


def test_combined_feedback_catches_init_without_hiding_demand_balance():
    assets, _ = load_assets()
    wrong = solution()
    wrong["I"]["A|s|1|1"] = 3
    feedback, audits = semantic_feedback(assets, data(), wrong)
    assert feedback["status"] == "VIOLATED"
    assert feedback["violations"][0]["asset_id"] == "retailopt.initial_inventory_zero"
    assert len(audits) == 2
    clean, _ = semantic_feedback(assets, data(), solution())
    assert clean["status"] == "SATISFIED"
    missing, _ = semantic_feedback(assets, data(), None)
    assert missing["status"] == "UNKNOWN"

import json
from pathlib import Path

from ora_agent.dvsa import asset_sha256, run_asset
from scripts.dvsa_retailopt import compare, demand_cells

ROOT = Path(__file__).resolve().parents[1]


def load_asset():
    return json.loads((ROOT / "assets/dvsa/retailopt_demand_v0.1.json").read_text())


def sample_data():
    return {
        "products": ["A"], "locations": ["s"], "periods": 1,
        "shelf_life": {"A": 2}, "demand_curve": {"A": [10]},
        "demand_share": {"s": 1}, "network": {"sub_edges": []},
    }


def test_real_asset_sums_dynamic_shelf_life_and_is_versioned():
    asset = load_asset()
    solution = {"sales": {"A|s|1|1": 4, "A|s|1|2": 6}, "lost": {}, "sub": {}}
    result = run_asset(asset, sample_data(), solution, domain="retailopt")
    assert result["status"] == "SATISFIED"
    assert result["evaluated"] == 1
    assert len(asset_sha256(asset)) == 64


def test_real_asset_catches_omitted_substitution_outflow_in_reported_solution():
    asset = load_asset()
    data = sample_data()
    data.update(products=["A", "B"], demand_curve={"A": [10], "B": [5]},
                shelf_life={"A": 1, "B": 1})
    data["network"]["sub_edges"] = [["A", "B"]]
    solution = {"sales": {"A|s|1|1": 10, "B|s|1|1": 5},
                "lost": {}, "sub": {"A|B|s|1": 4}}
    result = run_asset(asset, data, solution, domain="retailopt")
    assert result["status"] == "VIOLATED"
    assert result["violations"][0]["delta"] == 4


def test_legacy_binding_parser_does_not_accept_arbitrary_text():
    data = sample_data()
    result = {"violations": [("C-DEMAND", "[A,s,1] balance 10 != 9")]}
    assert demand_cells(result, data) == [["A", "s", 1]]


def test_compare_marks_missing_tables_unknown_not_consistent(monkeypatch):
    class Legacy:
        @staticmethod
        def check(data, solution):
            return {"violations": [], "warnings": []}

    monkeypatch.setattr("scripts.dvsa_retailopt.legacy", Legacy)
    result = compare(load_asset(), sample_data(), {"sales": {}})
    assert result["dvsa_status"] == "UNKNOWN"
    assert result["dvsa_unknown"]
    assert not result["implementation_consistent"]

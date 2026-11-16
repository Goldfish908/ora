import copy

import pytest

from ora_agent.dvsa import (InvalidSpec, asset_sha256, render_text, run_asset)


def demand_asset():
    return {
        "asset_id": "retailopt.demand_substitution_balance",
        "schema_version": "dvsa.expr.v0.1",
        "asset_version": "0.1.0",
        "source": {"reference": "RetailOpt demand and substitution contract"},
        "text": "Sales plus substitution outflow minus inflow plus lost sales equals demand.",
        "scope": {
            "domain": "retailopt",
            "required_data": ["products", "locations", "periods", "demand_curve", "demand_share", "network.sub_edges"],
            "required_solution": ["sales", "lost", "sub"],
        },
        "forall": {
            "p": {"path": "data.products"},
            "l": {"path": "data.locations"},
            "t": {"range": [1, {"add": [{"path": "data.periods"}, 1]}]},
        },
        "local": {
            "demand": {"mul": [
                {"index": {"value": {"index": {"value": {"path": "data.demand_curve"}, "at": {"var": "p"}}}, "at": {"sub": [{"var": "t"}, 1]}}},
                {"index": {"value": {"path": "data.demand_share"}, "at": {"var": "l"}}},
            ]},
            "sales_total": {"sum": {
                "forall": {"r": {"range": [1, 2]}},
                "value": {"lookup": {"path": "solution.sales", "key": [{"var": "p"}, {"var": "l"}, {"var": "t"}, {"var": "r"}], "default": 0}},
            }},
            "sub_out": {"sum": {
                "forall": {"e": {"path": "data.network.sub_edges"}},
                "where": {"eq": [{"index": {"value": {"var": "e"}, "at": 0}}, {"var": "p"}]},
                "value": {"lookup": {"path": "solution.sub", "key": [{"index": {"value": {"var": "e"}, "at": 0}}, {"index": {"value": {"var": "e"}, "at": 1}}, {"var": "l"}, {"var": "t"}], "default": 0}},
            }},
            "sub_in": {"sum": {
                "forall": {"e": {"path": "data.network.sub_edges"}},
                "where": {"eq": [{"index": {"value": {"var": "e"}, "at": 1}}, {"var": "p"}]},
                "value": {"lookup": {"path": "solution.sub", "key": [{"index": {"value": {"var": "e"}, "at": 0}}, {"index": {"value": {"var": "e"}, "at": 1}}, {"var": "l"}, {"var": "t"}], "default": 0}},
            }},
            "lost_value": {"lookup": {"path": "solution.lost", "key": [{"var": "p"}, {"var": "l"}, {"var": "t"}], "default": 0}},
        },
        "lhs": {"add": [{"var": "sales_total"}, {"var": "sub_out"}, {"neg": {"var": "sub_in"}}, {"var": "lost_value"}]},
        "rhs": {"var": "demand"},
        "relation": "eq",
        "tolerance": {"abs": 1e-6, "rel": 1e-6},
    }


def data(demand=10):
    return {
        "products": ["A"], "locations": ["s"], "periods": 1,
        "demand_curve": {"A": [demand]}, "demand_share": {"s": 1},
        "network": {"sub_edges": []},
    }


def solution(sales=10):
    return {"sales": {"A|s|1|1": sales}, "lost": {}, "sub": {}}


def test_clean_and_wrong_retail_demand_balance():
    asset = demand_asset()
    clean = run_asset(asset, data(), solution(), domain="retailopt")
    wrong = run_asset(asset, data(), solution(11), domain="retailopt")
    assert clean["status"] == "SATISFIED"
    assert clean["evaluated"] == 1
    assert wrong["status"] == "VIOLATED"
    assert wrong["violations"][0]["lhs"] == 11
    assert wrong["violations"][0]["rhs"] == 10
    assert wrong["violations"][0]["bindings"] == {"p": "A", "l": "s", "t": 1}


def test_frozen_asset_replays_on_new_numbers_without_code_change():
    asset = demand_asset()
    first = run_asset(asset, data(12), solution(12), domain="retailopt")
    second = run_asset(asset, data(37), solution(37), domain="retailopt")
    assert first["status"] == second["status"] == "SATISFIED"
    assert first["implementation_sha256"] == second["implementation_sha256"]


def test_substitution_outflow_cannot_disappear_from_demand():
    row = data()
    row["products"] = ["A", "B"]
    row["demand_curve"] = {"A": [10], "B": [5]}
    row["network"]["sub_edges"] = [["A", "B"]]
    sol = solution()
    sol["sales"]["B|s|1|1"] = 5
    sol["sub"] = {"A|B|s|1": 4}
    result = run_asset(demand_asset(), row, sol, domain="retailopt")
    assert result["status"] == "VIOLATED"
    assert result["violations"][0]["lhs"] == 14


def test_wrong_domain_is_not_applicable():
    result = run_asset(demand_asset(), {}, {}, domain="bwor")
    assert result["status"] == "NOT_APPLICABLE"
    assert result["evaluated"] == 0


def test_missing_required_table_is_unknown_not_clean_or_violation():
    result = run_asset(demand_asset(), data(), {"sales": {}}, domain="retailopt")
    assert result["status"] == "UNKNOWN"
    assert result["evaluated"] == 0
    assert "solution.lost" in result["unknown"][0]["detail"]


def test_missing_applicability_path_is_unknown_not_applicable():
    asset = demand_asset()
    asset["scope"]["applicability"] = {"gt": [{"path": "data.missing_flag"}, 0]}
    result = run_asset(asset, data(), solution(), domain="retailopt")
    assert result["status"] == "UNKNOWN"


def test_false_applicability_is_not_applicable():
    asset = demand_asset()
    asset["scope"]["applicability"] = {"gt": [{"path": "data.periods"}, 1]}
    result = run_asset(asset, data(), solution(), domain="retailopt")
    assert result["status"] == "NOT_APPLICABLE"


def test_nonfinite_and_division_by_zero_are_unknown():
    result = run_asset(demand_asset(), data(), solution(float("nan")), domain="retailopt")
    assert result["status"] == "UNKNOWN"
    asset = demand_asset()
    asset["lhs"] = {"div": [{"var": "sales_total"}, 0]}
    result = run_asset(asset, data(), solution(), domain="retailopt")
    assert result["status"] == "UNKNOWN"


def test_negative_array_index_is_rejected_not_python_wraparound():
    asset = demand_asset()
    asset["local"]["demand"] = {"index": {"value": {"path": "data.demand_share"}, "at": -1}}
    asset["local"]["demand"] = {"index": {"value": {"index": {"value": {"path": "data.demand_curve"}, "at": {"var": "p"}}}, "at": -1}}
    result = run_asset(asset, data(), solution(), domain="retailopt")
    assert result["status"] == "UNKNOWN"


def test_boolean_is_not_a_number():
    result = run_asset(demand_asset(), data(), solution(True), domain="retailopt")
    assert result["status"] == "UNKNOWN"


def test_unsupported_operator_is_rejected_as_bad_spec():
    asset = demand_asset()
    asset["lhs"] = {"call": "os.system"}
    with pytest.raises(InvalidSpec, match="unsupported"):
        run_asset(asset, data(), solution(), domain="retailopt")


def test_missing_relation_is_rejected_before_evaluation():
    asset = demand_asset()
    del asset["relation"]
    with pytest.raises(InvalidSpec):
        run_asset(asset, data(), solution(), domain="retailopt")


def test_expression_budget_returns_unknown():
    asset = demand_asset()
    result = run_asset(asset, data(), solution(), domain="retailopt")
    assert result["status"] == "SATISFIED"
    from ora_agent.dvsa import Interpreter, UnknownValue
    interpreter = Interpreter(data(), solution(), max_nodes=2)
    with pytest.raises(UnknownValue, match="node budget"):
        interpreter._eval(asset["lhs"], {"sales_total": 1, "sub_out": 0, "sub_in": 0, "lost_value": 0})


def test_hash_and_text_memory_are_stable_and_versioned():
    asset = demand_asset()
    digest = asset_sha256(asset)
    asset["implementation_sha256"] = "self-field-is-excluded"
    assert asset_sha256(asset) == digest
    assert render_text(asset) == asset["text"]
    changed = copy.deepcopy(asset)
    changed["asset_version"] = "0.1.1"
    assert asset_sha256(changed) != digest


def test_malformed_source_cannot_be_registered():
    asset = demand_asset()
    asset["source"] = {}
    with pytest.raises(InvalidSpec, match="source.reference"):
        asset_sha256(asset)

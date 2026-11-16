from pathlib import Path

import pytest

from ora_agent.scoped_assets import compile_asset, load_asset, validate_asset

ROOT = Path(__file__).resolve().parents[1]
ASSET_NAMES = ("makespan_v0.1.json", "objective_recompute_v0.1.json",
               "resource_bound_v0.1.json", "variable_domain_v0.1.json",
               "state_conservation_v0.1.json", "indicator_link_v0.1.json",
               "job_precedence_v0.1.json")


def asset(name):
    return load_asset(ROOT / "assets" / "scoped_ir" / name)


def test_all_assets_pass_independent_validation():
    for name in ASSET_NAMES:
        result = validate_asset(asset(name))
        assert result["status"] == "validated", name
        assert result["evaluation"]["detection"] == 1.0
        assert result["evaluation"]["false_positive"] == 0.0
        assert result["evaluation"]["unknown"] == 0


def test_makespan_template_uses_max_not_add():
    spec = compile_asset(asset("makespan_v0.1.json"),
                         asset("makespan_v0.1.json")["validation"]["binding"])
    assert "max" in spec["invariants"][0]["rhs"]
    assert "add" not in spec["invariants"][0]["rhs"]


def test_scope_mismatch_is_rejected_before_evaluation():
    binding = asset("makespan_v0.1.json")["validation"]["binding"]
    binding["terms"] = binding["terms"][:1]
    with pytest.raises(ValueError, match="requires 2 activities"):
        compile_asset(asset("makespan_v0.1.json"), binding)


def test_objective_recompute_uses_linear_terms():
    spec = compile_asset(asset("objective_recompute_v0.1.json"),
                         asset("objective_recompute_v0.1.json")["validation"]["binding"])
    assert spec["invariants"][0]["lhs"] == {"path": "solution.objective"}
    assert "add" in spec["invariants"][0]["rhs"]


def test_resource_bound_preserves_relation_and_limit():
    spec = compile_asset(asset("resource_bound_v0.1.json"),
                         asset("resource_bound_v0.1.json")["validation"]["binding"])
    invariant = spec["invariants"][0]
    assert invariant["relation"] == "le"
    assert invariant["rhs"] == 10


def test_variable_domain_compiles_each_variable():
    binding = asset("variable_domain_v0.1.json")["validation"]["binding"]
    binding["terms"] = binding["terms"] + [{"path": "solution.variables.y"}]
    spec = compile_asset(asset("variable_domain_v0.1.json"), binding)
    assert len(spec["invariants"]) == 2
    assert spec["invariants"][1]["rhs"] == {"round": {"path": "solution.variables.y"}}


def test_state_conservation_separates_initialization_and_flow():
    current = asset("state_conservation_v0.1.json")
    spec = compile_asset(current, current["validation"]["binding"])
    initial, flow = spec["invariants"]
    assert initial["lhs"] == {"path": "solution.variables.stock_0"}
    assert initial["rhs"] == 0
    assert flow["lhs"] == {"path": "solution.variables.stock_1"}
    assert flow["rhs"] == {
        "add": [{"path": "solution.variables.stock_0"},
                {"path": "solution.variables.production"},
                {"neg": {"path": "solution.variables.demand"}}]}


@pytest.mark.parametrize("label,rule", [
    ("wrong_initial", "state_conservation_initial"),
    ("wrong_flow", "state_conservation_flow"),
])
def test_state_conservation_fires_on_the_correct_mechanism(label, rule):
    current = asset("state_conservation_v0.1.json")
    result = validate_asset(current)
    record = next(row for row in result["evaluation"]["records"] if row["key"] == label)
    assert record["fired"] is True
    assert [item["rule"] for item in record["violations"]] == [rule]


def test_state_conservation_template_can_be_rebound_without_code_changes():
    current = asset("state_conservation_v0.1.json")
    binding = current["validation"]["binding"]
    rebound = {
        "initial": {"path": "solution.variables.inventory_start", "value": 0},
        "next": {"path": "solution.variables.inventory_end"},
        "previous": {"path": "solution.variables.inventory_start"},
        "inflows": [{"path": "solution.variables.received"}],
        "outflows": [{"path": "solution.variables.shipped"}],
        "source_span": binding["source_span"],
        "flow_source_span": binding["flow_source_span"],
    }
    spec = compile_asset(current, rebound)
    paths = {spec["invariants"][0]["lhs"]["path"],
             spec["invariants"][1]["lhs"]["path"]}
    assert paths == {"solution.variables.inventory_start",
                     "solution.variables.inventory_end"}



def test_indicator_link_validates_both_directions_and_multiple_clean_cells():
    result = validate_asset(asset("indicator_link_v0.1.json"))
    assert result["status"] == "validated"
    records = {row["key"]: row for row in result["evaluation"]["records"]}
    assert not records["clean"]["fired"]
    assert not records["clean_positive"]["fired"]
    assert [item["rule"] for item in records["wrong_off"]["violations"]] == [
        "supplier_indicator_off"]
    assert [item["rule"] for item in records["wrong_on"]["violations"]] == [
        "supplier_indicator_on"]


def test_indicator_reference_hash_tampering_is_rejected():
    current = asset("indicator_link_v0.1.json")
    evidence = current["validation"]["binding"]["links"][0]["source_evidence"]
    evidence["sha256"] = "0" * 64
    result = validate_asset(current)
    assert result["status"] == "rejected"
    assert result["evaluation"]["rejected_count"] > 0


def test_indicator_requires_independent_auxiliary_variable_evidence():
    current = asset("indicator_link_v0.1.json")
    del current["validation"]["binding"]["links"][0]["source_evidence"]
    result = validate_asset(current)
    assert result["status"] == "rejected"
    assert any("independent source evidence" in item["reason"]
               for item in result["evaluation"]["records"][0]["rejected"])

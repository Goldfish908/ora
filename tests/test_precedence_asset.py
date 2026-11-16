import copy

import pytest

from ora_agent.flow_shop import structure_audit
from ora_agent.scoped_assets import compile_asset, load_asset, validate_asset
from ora_agent.scoped_ir import evaluate_spec
from tests.test_flow_shop import toy


def asset():
    return load_asset("assets/scoped_ir/job_precedence_v0.1.json")


def test_precedence_asset_accepts_non_strict_boundary_and_legitimate_waiting():
    result = validate_asset(asset())
    assert result["status"] == "validated"
    records = {row["key"]: row for row in result["evaluation"]["records"]}
    assert records["clean"]["fired"] is False
    assert records["clean_wait"]["fired"] is False
    assert records["wrong"]["fired"] is True


def test_strict_precedence_is_not_silently_changed_to_non_strict():
    binding = copy.deepcopy(asset()["validation"]["binding"])
    binding["relation"] = "gt"
    spec = compile_asset(asset(), binding)
    question = asset()["validation"]["question"]

    def cell(key, wrong, value):
        return {"key": key, "wrong": wrong, "mutation": key, "reference_violations": [],
                "solution": {"variables": {"end_a": 5.0, "start_b": value}, "objective": 0.0}}

    result = evaluate_spec(spec, question, [cell("clean_strict", False, 6.0),
                                           cell("wrong_equal", True, 5.0)], "strict")
    assert result["records"][0]["fired"] is False
    assert result["records"][1]["fired"] is True
    binding = dict(binding, strict=True)
    assert structure_audit(toy(), binding)["status"] == "UNKNOWN"


def test_precedence_requires_independent_binding_evidence():
    current = asset()
    del current["validation"]["binding"]["source_evidence"]
    result = validate_asset(current)
    assert result["status"] == "rejected"
    assert result["evaluation"]["unknown"] > 0


def test_duration_terms_must_be_positive():
    binding = copy.deepcopy(asset()["validation"]["binding"])
    binding["duration_terms"] = [{"path": "solution.variables.x_1_1", "coefficient": -1}]
    with pytest.raises(ValueError, match="durations must be positive"):
        compile_asset(asset(), binding)

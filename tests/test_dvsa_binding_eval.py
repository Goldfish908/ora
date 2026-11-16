from pathlib import Path

from ora_agent.dvsa_templates import load_library
from scripts.dvsa_binding_eval import evaluate_bindings

ROOT = Path(__file__).resolve().parents[1]
_, TEMPLATES = load_library(ROOT / "assets/dvsa/bwor_primitives_v0.1.json")


def reference():
    model = {
        "schema_version": "dvsa.model.v0.1", "problem_id": "toy",
        "variables": {"x": {"domain": "real", "lb": 0}, "y": {"domain": "real", "lb": 0}},
        "data": {"limit": 4},
        "constraints": [{"constraint_id": "capacity", "source": "total capacity is four",
                         "relation": "le", "lhs": {"add": [{"var": "x"}, {"var": "y"}]},
                         "rhs": {"path": "data.limit"}}],
        "objective": {"sense": "maximize", "expression": {"add": [{"var": "x"}, {"var": "y"}]}},
    }
    return {"model": model, "solution": {"variables": {"x": 2, "y": 2}, "objective": 4},
            "revision": "test"}


def binding(binding_id, template_id, data):
    return {"binding_id": binding_id, "template_id": template_id,
            "source": "total capacity is four", "data": data}


def terms():
    return [{"variable": "x", "coefficient": 1}, {"variable": "y", "coefficient": 1}]


def test_independent_bindings_match_reference_behavior_not_just_ids():
    doc = {"bindings": [
        binding("custom_capacity_name", "bwor.resource_capacity", {"terms": terms(), "limit": 4}),
        binding("custom_objective_name", "bwor.objective_recompute", {"terms": terms(), "constant": 0}),
    ]}
    result = evaluate_bindings(reference(), doc, TEMPLATES)
    assert result["summary"]["detection"] == 1
    assert result["summary"]["behavioral_rule_coverage"] == 1
    assert result["summary"]["clean_problem_false_positive"] == 0
    assert result["summary"]["unknown_events"] == 0


def test_wrong_limit_can_detect_but_is_not_semantic_match_and_false_positive():
    doc = {"bindings": [
        binding("wrong_capacity", "bwor.resource_capacity", {"terms": terms(), "limit": 3}),
        binding("objective", "bwor.objective_recompute", {"terms": terms(), "constant": 0}),
    ]}
    result = evaluate_bindings(reference(), doc, TEMPLATES)
    summary = result["summary"]
    assert summary["detection"] == 1
    assert summary["detection_using_only_clean_pass_bindings"] == 0.5
    assert summary["clean_problem_false_positive"] == 1
    assert summary["behavioral_rule_coverage"] == 0.5
    assert "wrong_capacity" in summary["unmatched_candidate_bindings"]


def test_missing_variable_is_unknown_not_detection_or_false_positive():
    doc = {"bindings": [binding("missing", "bwor.resource_capacity",
                                {"terms": [{"variable": "z", "coefficient": 1}], "limit": 4})]}
    result = evaluate_bindings(reference(), doc, TEMPLATES)
    summary = result["summary"]
    assert summary["detection"] == 0
    assert summary["clean_problem_false_positive"] == 0
    assert summary["unknown_events"] == 3
    assert summary["behavioral_rule_coverage"] == 0

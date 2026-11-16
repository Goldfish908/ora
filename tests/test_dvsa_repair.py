from pathlib import Path

from ora_agent.dvsa_repair import schema_errors, score_solution
from ora_agent.dvsa_templates import load_library
from scripts.dvsa_repair import deterministic_feedback

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
    return {"model": model}


def test_shared_schema_rejects_missing_extra_and_changed_domains():
    expected = reference()["model"]["variables"]
    assert schema_errors({"variables": expected}, expected) == []
    changed = {"variables": {"x": {"domain": "integer", "lb": 0}, "z": {"domain": "real", "lb": 0}}}
    errors = schema_errors(changed, expected)
    assert any("missing variable: y" in error for error in errors)
    assert any("unexpected variable: z" in error for error in errors)
    assert any("x.domain" in error for error in errors)


def test_business_score_requires_semantics_and_objective_quality():
    ref = reference()
    assert score_solution(ref, {"variables": {"x": 2, "y": 2}, "objective": 4}, 4)["business_correct"]
    infeasible = score_solution(ref, {"variables": {"x": 3, "y": 2}, "objective": 4}, 4)
    assert infeasible["objective_correct"]
    assert not infeasible["semantic_valid"]
    assert not infeasible["business_correct"]
    suboptimal = score_solution(ref, {"variables": {"x": 1, "y": 1}, "objective": 2}, 4)
    assert suboptimal["semantic_valid"]
    assert not suboptimal["objective_correct"]
    assert not suboptimal["business_correct"]
    assert not score_solution(ref, None, 4)["business_correct"]


def test_dvsa_feedback_fires_only_on_numeric_violation():
    doc = {"bindings": [{"binding_id": "capacity", "template_id": "bwor.resource_capacity",
                         "source": "total capacity is four",
                         "data": {"terms": [{"variable": "x", "coefficient": 1},
                                            {"variable": "y", "coefficient": 1}], "limit": 4}}]}
    violated, _ = deterministic_feedback(reference(), doc, {"variables": {"x": 3, "y": 2}}, TEMPLATES)
    clean, _ = deterministic_feedback(reference(), doc, {"variables": {"x": 2, "y": 2}}, TEMPLATES)
    unknown, _ = deterministic_feedback(reference(), doc, {"variables": {"x": 2}}, TEMPLATES)
    assert violated["status"] == "VIOLATED"
    assert violated["violations"][0]["violations"][0]["lhs"] == 5
    assert clean["status"] == "SATISFIED"
    assert unknown["status"] == "UNKNOWN"


def test_execution_recovery_is_shared_but_not_counted_as_semantic_trigger():
    from scripts.dvsa_repair import repair_trigger
    assert repair_trigger("dvsa", {"status": "SATISFIED"}, True) == "no_call"
    assert repair_trigger("dvsa", {"status": "VIOLATED"}, True) == "dvsa_violation"
    assert repair_trigger("dvsa", {"status": "UNKNOWN"}, False) == "execution_failure_unknown_semantics"
    assert repair_trigger("text_memory", {"status": "not_provided"}, True) == "scheduled_self_review"

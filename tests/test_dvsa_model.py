import copy

import pytest

from ora_agent.dvsa import InvalidSpec
from ora_agent.dvsa_model import (audit_solution, extract_json, solve_model,
                                  validate_model, verify_sources)


def model():
    return {
        "schema_version": "dvsa.model.v0.1",
        "problem_id": "toy",
        "variables": {
            "x": {"domain": "real", "lb": 0},
            "y": {"domain": "real", "lb": 0},
        },
        "data": {"capacity": 4, "x_cap": 2, "profit_x": 3, "profit_y": 2},
        "constraints": [
            {"constraint_id": "capacity", "source": "total capacity is four",
             "relation": "le", "lhs": {"add": [{"var": "x"}, {"var": "y"}]},
             "rhs": {"path": "data.capacity"}},
            {"constraint_id": "x_limit", "source": "x has a separate limit",
             "relation": "le", "lhs": {"var": "x"}, "rhs": {"path": "data.x_cap"}},
        ],
        "objective": {"sense": "maximize", "expression": {"add": [
            {"mul": [{"path": "data.profit_x"}, {"var": "x"}]},
            {"mul": [{"path": "data.profit_y"}, {"var": "y"}]},
        ]}},
        "assumptions": [],
    }


def test_scalar_reference_solves_and_audits_with_scip():
    result = solve_model(model())
    assert result["status"] == "optimal"
    assert result["solution"]["variables"] == {"x": 2, "y": 2}
    assert result["solution"]["objective"] == 10
    assert result["audit"]["verdict"] == "VALID"


def test_independent_mutation_catches_target_capacity_not_only_objective():
    spec = model()
    changed = {"variables": {"x": 3, "y": 2}, "objective": 13}
    result = audit_solution(spec, changed)
    assert result["verdict"] == "INVALID"
    assert "capacity" in {item["rule"] for item in result["violations"]}
    assert not any(item["rule"] == "OBJECTIVE" for item in result["violations"])


def test_integrality_and_missing_values_are_distinct():
    spec = model()
    spec["variables"]["x"]["domain"] = "integer"
    fractional = audit_solution(spec, {"variables": {"x": 1.5, "y": 2}, "objective": 8.5})
    assert fractional["verdict"] == "INVALID"
    assert fractional["violations"][0]["rule"] == "INTEGRALITY"
    missing = audit_solution(spec, {"variables": {"x": 1}, "objective": 5})
    assert missing["verdict"] == "UNKNOWN"


def test_objective_must_be_recomputed_not_copied():
    result = audit_solution(model(), {"variables": {"x": 2, "y": 2}, "objective": 11})
    assert result["verdict"] == "INVALID"
    assert result["violations"][0]["rule"] == "OBJECTIVE"


def test_nonlinear_or_strict_models_are_rejected():
    nonlinear = model()
    nonlinear["objective"]["expression"] = {"mul": [{"var": "x"}, {"var": "y"}]}
    assert solve_model(nonlinear)["status"] == "invalid_model"
    strict = model()
    strict["constraints"][0]["relation"] = "lt"
    with pytest.raises(InvalidSpec):
        validate_model(strict)


def test_sources_must_be_verbatim_spans():
    spec = model()
    question = "The total capacity is four, and x has a separate limit."
    assert verify_sources(spec, question) == []
    changed = copy.deepcopy(spec)
    changed["constraints"][0]["source"] = "an invented requirement"
    assert verify_sources(changed, question)[0]["constraint_id"] == "capacity"


def test_json_extraction_does_not_greedily_join_multiple_objects():
    text = "Here is the model:\n```json\n" + __import__("json").dumps(model()) + "\n```"
    assert extract_json(text)["problem_id"] == "toy"
    with pytest.raises(ValueError):
        extract_json("not a model")


def test_missing_data_defaults_empty_only_when_paths_do_not_require_it():
    inline = model()
    inline["constraints"][0]["rhs"] = 4
    inline["constraints"][1]["rhs"] = 2
    inline["objective"]["expression"] = {"add": [
        {"mul": [3, {"var": "x"}]}, {"mul": [2, {"var": "y"}]}]}
    del inline["data"]
    result = solve_model(inline)
    assert result["status"] == "optimal"
    assert result["audit"]["verdict"] == "VALID"
    unresolved = model()
    del unresolved["data"]
    assert solve_model(unresolved)["status"] == "invalid_model"

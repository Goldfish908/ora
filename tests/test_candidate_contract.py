import copy
import json
import sys

import pytest

from ora_agent.dvsa import InvalidSpec
from ora_agent.dvsa_model import (extract_json, normalize_candidate,
                                  validate_candidate_paths, validate_model)
from scripts import dvsa_candidate


def model():
    return {
        "schema_version": "dvsa.model.v0.1",
        "problem_id": "toy",
        "variables": {"x": {"domain": "real", "lb": 0, "ub": 2}},
        "data": {"limit": 2},
        "constraints": [{
            "constraint_id": "limit",
            "source": "x has a limit",
            "relation": "le",
            "lhs": {"var": "x"},
            "rhs": {"path": "data.limit"},
        }],
        "objective": {"sense": "minimize", "expression": {"var": "x"}},
        "assumptions": [],
        "modeling_conflicts": [],
    }


def declaration(name="x"):
    return {"name": name, "domain": "real", "lb": 0, "ub": 2}


def test_exact_variable_declaration_list_is_converted_without_mutating_input():
    candidate = model()
    candidate["variables"] = [declaration()]
    original = copy.deepcopy(candidate)
    normalized = normalize_candidate(candidate)
    assert candidate == original
    assert normalized is not candidate
    assert normalized["variables"] == {
        "x": {"domain": "real", "lb": 0, "ub": 2},
    }
    validate_model(normalized)
    assert validate_candidate_paths(normalized) is normalized


def test_duplicate_variable_names_are_rejected():
    candidate = model()
    candidate["variables"] = [declaration(), declaration()]
    with pytest.raises(InvalidSpec, match="duplicate variable name: x"):
        normalize_candidate(candidate)


def test_variable_declaration_without_name_is_rejected():
    candidate = model()
    spec = declaration()
    del spec["name"]
    candidate["variables"] = [spec]
    with pytest.raises(InvalidSpec, match="exactly name/domain/lb/ub"):
        normalize_candidate(candidate)


def test_variable_declaration_with_extra_field_is_rejected():
    candidate = model()
    candidate["variables"] = [{**declaration(), "description": "extra"}]
    with pytest.raises(InvalidSpec, match="exactly name/domain/lb/ub"):
        normalize_candidate(candidate)


@pytest.mark.parametrize("name", ["", "1x", "data", "solution"])
def test_variable_declaration_requires_a_legal_name(name):
    candidate = model()
    candidate["variables"] = [declaration(name)]
    with pytest.raises(InvalidSpec, match="invalid variable name"):
        normalize_candidate(candidate)


@pytest.mark.parametrize("variables", [None, "x", 1])
def test_other_variable_container_types_are_rejected(variables):
    candidate = model()
    candidate["variables"] = variables
    with pytest.raises(InvalidSpec, match="object or declaration list"):
        normalize_candidate(candidate)


def test_truncated_nested_object_is_not_promoted_to_candidate():
    truncated = ('{"schema_version":"dvsa.model.v0.1","problem_id":"toy",'
                 '"objective":{"sense":"minimize","expression":1}')
    nested = extract_json(truncated)
    assert nested == {"sense": "minimize", "expression": 1}
    with pytest.raises(InvalidSpec, match="variables"):
        normalize_candidate(nested)
    assert "problem_id" not in nested


def test_undefined_data_path_is_rejected_before_solving():
    candidate = model()
    candidate["constraints"][0]["rhs"] = {"path": "data.undefined"}
    validate_model(candidate)
    with pytest.raises(InvalidSpec, match="undefined data path: data.undefined"):
        validate_candidate_paths(candidate)


def test_normal_object_model_is_unchanged():
    candidate = model()
    original = copy.deepcopy(candidate)
    normalized = normalize_candidate(candidate)
    assert normalized is candidate
    assert candidate == original
    validate_model(normalized)
    assert validate_candidate_paths(normalized) is candidate


@pytest.mark.parametrize("case,expected_status", [
    ("duplicate", "contract_invalid"),
    ("problem_id", "contract_invalid"),
    ("shared_schema", "invalid_shared_schema"),
    ("solve", "solve_failed"),
])
def test_candidate_entrypoint_preserves_response_and_separates_statuses(
        tmp_path, monkeypatch, case, expected_status):
    candidate = model()
    candidate["variables"] = [declaration()]
    expected_variables = copy.deepcopy(model()["variables"])
    solve_result = None
    if case == "duplicate":
        candidate["variables"].append(declaration())
    elif case == "problem_id":
        candidate["problem_id"] = "other"
    elif case == "shared_schema":
        expected_variables["x"]["lb"] = 1
    else:
        solve_result = {"status": "infeasible", "solver_calls": 1}
    reference = {
        "model": {**model(), "variables": expected_variables},
        "question": "x has a limit",
        "revision": "test",
    }
    response = {"content": json.dumps(candidate), "usage": {}, "latency_s": 0.1}

    def solve(*args, **kwargs):
        if solve_result is None:
            raise AssertionError("solver must not be called")
        return solve_result

    monkeypatch.setattr(dvsa_candidate, "load_rows",
                        lambda split: [{"id": "toy", "answer": 0}])
    monkeypatch.setattr(dvsa_candidate, "select_reference",
                        lambda split, problem_id: reference)
    monkeypatch.setattr(dvsa_candidate.llm_mod, "load_config", lambda: {})
    monkeypatch.setattr(dvsa_candidate.llm_mod, "chat", lambda *args, **kwargs: response)
    monkeypatch.setattr(dvsa_candidate, "solve_model", solve)
    monkeypatch.setattr(sys, "argv", [
        "dvsa_candidate.py", "--ids", "toy", "--out", str(tmp_path),
    ])
    dvsa_candidate.main()

    target = tmp_path / "toy" / "initial"
    assert json.loads((target / "response.json").read_text()) == response
    result = json.loads((target / "result.json").read_text())
    assert result["status"] == expected_status
    if expected_status == "contract_invalid":
        expected_error = "duplicate variable name" if case == "duplicate" else "problem_id mismatch"
        assert expected_error in result["error"]
        assert not (target / "candidate.json").exists()
    else:
        saved = json.loads((target / "candidate.json").read_text())
        assert saved["variables"] == model()["variables"]
        assert isinstance(json.loads(response["content"])["variables"], list)
    if case == "shared_schema":
        assert result["schema_errors"]
    if case == "solve":
        assert result["solve"] == solve_result

import copy

import pytest

from ora_agent.dvsa import InvalidSpec
from ora_agent.dvsa_model import (
    normalize_candidate_paths,
    solve_model,
    validate_candidate_paths,
    validate_model,
)


def candidate():
    return {
        "schema_version": "dvsa.model.v0.1", "problem_id": "toy",
        "variables": {"x": {"domain": "real", "lb": 0, "ub": None}},
        "data": {"supply": 4, "coefficients": [3]},
        "constraints": [{"constraint_id": "supply", "source": "3x equals 4",
                         "relation": "eq",
                         "lhs": {"mul": [{"lookup": {"path": "coefficients", "index": 0}},
                                          {"var": "x"}]},
                         "rhs": {"path": "supply"}}],
        "objective": {"sense": "minimize", "expression": {"var": "x"}},
        "assumptions": [], "modeling_conflicts": [],
    }


def test_direct_paths_and_list_lookup_normalize_without_mutating_input():
    original = candidate()
    before = copy.deepcopy(original)
    normalized, changes = normalize_candidate_paths(original)
    assert original == before
    assert normalized["constraints"][0]["rhs"] == {"path": "data.supply"}
    assert normalized["constraints"][0]["lhs"]["mul"][0] == {
        "index": {"value": {"path": "data.coefficients"}, "at": 0}}
    assert {change["kind"] for change in changes} == {"data_path_prefix", "lookup_list_index"}
    validate_model(normalized)
    validate_candidate_paths(normalized)
    solved = solve_model(normalized)
    assert solved["status"] == "optimal"
    assert solved["solution"]["variables"]["x"] == pytest.approx(4 / 3)
    assert solved["solution"]["objective"] == pytest.approx(4 / 3)


def test_unknown_direct_path_and_solution_namespace_are_rejected():
    original = candidate()
    original["constraints"][0]["rhs"] = {"path": "missing"}
    with pytest.raises(InvalidSpec, match="undefined data path: data.missing"):
        normalize_candidate_paths(original)
    original["constraints"][0]["rhs"] = {"path": "solution.x"}
    with pytest.raises(InvalidSpec, match="only read data paths"):
        normalize_candidate_paths(original)


def test_unconverted_direct_path_is_no_longer_silently_accepted():
    original = candidate()
    original["constraints"][0]["lhs"] = {"var": "x"}
    with pytest.raises(InvalidSpec, match="data namespace"):
        validate_candidate_paths(original)


def test_invalid_lookup_and_index_shapes_fail_before_solver():
    original = candidate()
    original["constraints"][0]["lhs"]["mul"][0]["lookup"]["index"] = 3
    with pytest.raises(InvalidSpec, match="out of range"):
        normalize_candidate_paths(original)
    original = candidate()
    original["data"]["table"] = {"a": 1}
    original["constraints"][0]["lhs"] = {"lookup": {"path": "table", "index": 0}}
    normalized, _ = normalize_candidate_paths(original)
    with pytest.raises(InvalidSpec, match="lookup requires path/key"):
        validate_candidate_paths(normalized)
    original["constraints"][0]["lhs"] = {"index": {"path": "coefficients", "at": 0}}
    normalized, _ = normalize_candidate_paths(original)
    with pytest.raises(InvalidSpec, match="index requires value and at"):
        validate_candidate_paths(normalized)

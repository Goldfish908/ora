import hashlib
import json

import pytest

from ora_agent.declarative_neighborhood import (
    DECISION_REPAIR,
    MODEL_DIAGNOSIS,
    OBJECTIVE_OPTIMIZATION,
    DecisionArtifact,
    DependencyGraph,
    NeighborhoodSpec,
    ViolationKey,
    build_neighborhood,
    repair_neighborhood,
    required_inputs,
)


def violation(requirement_id, index, rule_part):
    return ViolationKey(requirement_id, index, rule_part).to_dict()


def graph():
    return DependencyGraph(
        {
            ViolationKey("R-x", ("x",), "lower").stable_key: ["x"],
            ViolationKey("R-y", ("y",), "upper").stable_key: ["y"],
            ViolationKey("R-total", ("global",), "balance").stable_key: ["x"],
        },
        {"x": ["y"], "y": [], "z": [], "far": []},
    )


def checker(decisions):
    if not isinstance(decisions, dict) or any(
        name not in decisions for name in ("x", "y", "z")
    ):
        return {"business_status": "unknown", "violations": [], "objective": None}
    if decisions["x"] == 2 and decisions.get("force_unknown"):
        return {"business_status": "unknown", "violations": [], "objective": None}
    violations = []
    if decisions["x"] < 1:
        violations.append(violation("R-x", ("x",), "lower"))
    if decisions["y"] > 0:
        violations.append(violation("R-y", ("y",), "upper"))
    return {
        "business_status": "fail" if violations else "pass",
        "violations": violations,
        "objective": decisions["x"] + decisions["y"],
    }


def test_only_violation_variables_and_direct_neighbors_are_released():
    parent = {"x": 0, "y": 4, "z": 7, "far": 9}
    raw = json.dumps(parent, indent=2).encode()
    spec = build_neighborhood(
        parent,
        [violation("R-x", ("x",), "lower")],
        graph(),
        parent_bytes=raw,
    )

    assert spec.released_variables == ("x", "y")
    assert spec.fixed_variables == ("far", "z")
    assert spec.fixed_values == {"z": 7, "far": 9}
    assert spec.parent_bytes == raw
    assert spec.parent_sha256 == hashlib.sha256(raw).hexdigest()

    restored = NeighborhoodSpec.from_dict(json.loads(spec.to_json()))
    assert restored == spec
    assert restored.parent_bytes == raw


def test_unrelated_variable_is_fixed_and_solver_cannot_change_it():
    parent = {"x": 0, "y": 0, "z": 7, "far": 9}

    def solve(spec):
        assert spec.fixed_values["far"] == 9
        changed = dict(parent, x=1, far=100)
        return {"status": "optimal", "decisions": changed}

    result = repair_neighborhood(parent, graph(), checker, solve)

    assert not result.accepted
    assert result.reason == "fixed_variable_changed"
    assert result.decisions == parent
    assert result.decisions["far"] == 9


def test_empty_neighborhood_is_rejected_without_calling_solver():
    parent = {"x": 1, "y": 0, "z": 7}
    called = []

    def solve(spec):
        called.append(spec)
        return {"status": "optimal", "values": {"x": 2, "y": 0}}

    result = repair_neighborhood(parent, graph(), checker, solve)

    assert not result.accepted
    assert result.reason == "empty_neighborhood"
    assert called == []
    assert result.checkpoint is not None
    assert result.checkpoint.decisions == parent


def test_parent_hash_and_original_bytes_survive_accepted_repair():
    parent = {"x": 0, "y": 0, "z": 7}
    raw = b'{\n  "x": 0, "y": 0, "z": 7\n}\n'

    def solve(spec):
        assert spec.parent_bytes == raw
        return {"status": "feasible", "values": {"x": 1, "y": 0}}

    result = repair_neighborhood(parent, graph(), checker, solve, parent_bytes=raw)

    assert result.accepted
    assert result.parent_bytes == raw
    assert result.parent_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.selected.decisions == {"x": 1, "y": 0, "z": 7}
    assert result.selected.raw_bytes != raw


def test_new_violation_is_rejected_and_parent_is_selected():
    parent = {"x": 0, "y": 0, "z": 7}
    new_key = ViolationKey("R-y", ("y",), "upper").stable_key

    def solve(spec):
        return {"status": "optimal", "values": {"x": 1, "y": 1}}

    result = repair_neighborhood(parent, graph(), checker, solve)

    assert not result.accepted
    assert result.reason == "new_violations"
    assert result.introduced_violations == (new_key,)
    assert result.decisions == parent
    assert result.candidate.decisions == {"x": 1, "y": 1, "z": 7}


def test_unknown_full_check_is_rejected():
    parent = {"x": 0, "y": 0, "z": 7, "force_unknown": False}

    def solve(spec):
        complete = dict(parent, x=2, force_unknown=True)
        return {"status": "optimal", "decisions": complete}

    result = repair_neighborhood(
        parent,
        graph(),
        checker,
        solve,
        variable_names=["x", "y"],
    )

    assert not result.accepted
    assert result.reason == "candidate_unknown"
    assert result.decisions == parent


def test_unknown_solver_status_is_rejected_before_candidate_check():
    parent = {"x": 0, "y": 0, "z": 7}
    calls = []

    def counting_checker(decisions):
        calls.append(decisions.copy())
        return checker(decisions)

    result = repair_neighborhood(
        parent,
        graph(),
        counting_checker,
        lambda spec: {"status": None, "values": {"x": 1, "y": 0}},
    )

    assert not result.accepted
    assert result.reason == "solver_status_unknown"
    assert len(calls) == 1
    assert result.decisions == parent


def test_full_solver_result_cannot_drop_parent_decisions():
    parent = {"x": 0, "y": 0, "z": 7}

    result = repair_neighborhood(
        parent,
        graph(),
        checker,
        lambda spec: {"status": "optimal", "decisions": {"x": 1, "y": 0}},
    )

    assert not result.accepted
    assert result.reason == "parent_decision_lost"
    assert result.decisions == parent


def objective_checker(decisions):
    return {
        "business_status": "pass",
        "violations": [],
        "objective": decisions["x"] + decisions["y"],
    }


@pytest.mark.parametrize(
    "sense,better,worse",
    [("minimize", -1, 1), ("maximize", 1, -1)],
)
def test_objective_direction_uses_independent_recomputed_value(sense, better, worse):
    parent = {"x": 0, "y": 0, "z": 5}

    def optimize(spec):
        value = better if sense == spec.objective_sense else worse
        return {
            "status": "optimal",
            "values": {"x": value, "y": 0},
            "objective": -999 if sense == "minimize" else 999,
        }

    accepted = repair_neighborhood(
        parent,
        graph(),
        objective_checker,
        optimize,
        mode=OBJECTIVE_OPTIMIZATION,
        objective_sense=sense,
        seed_variables=["x"],
    )
    assert accepted.accepted
    assert accepted.candidate_report["objective"] == better

    def regress(spec):
        return {"status": "optimal", "values": {"x": worse, "y": 0}}

    rejected = repair_neighborhood(
        parent,
        graph(),
        objective_checker,
        regress,
        mode=OBJECTIVE_OPTIMIZATION,
        objective_sense=sense,
        seed_variables=["x"],
    )
    assert not rejected.accepted
    assert rejected.reason == "objective_regression"
    assert rejected.decisions == parent


def test_feasible_checkpoint_and_its_bytes_survive_rejected_candidate():
    parent = {"x": 0, "y": 0, "z": 7}
    checkpoint_decisions = {"x": 1, "y": 0, "z": 7}
    checkpoint_raw = b'{ "x": 1, "y": 0, "z": 7 }'
    checkpoint = DecisionArtifact.create(checkpoint_decisions, checkpoint_raw)

    result = repair_neighborhood(
        parent,
        graph(),
        checker,
        lambda spec: {"status": "optimal", "values": {"x": 1, "y": 1}},
        checkpoint=checkpoint,
    )

    assert not result.accepted
    assert result.reason == "new_violations"
    assert result.decisions == parent
    assert result.checkpoint is not None
    assert result.checkpoint.decisions == checkpoint_decisions
    assert result.checkpoint.raw_bytes == checkpoint_raw
    assert result.checkpoint.sha256 == hashlib.sha256(checkpoint_raw).hexdigest()


def test_partial_repair_can_fix_old_key_but_cannot_introduce_one():
    parent = {"x": 0, "y": 1, "z": 7}

    result = repair_neighborhood(
        parent,
        graph(),
        checker,
        lambda spec: {"status": "feasible", "values": {"x": 1, "y": 1}},
    )

    assert result.accepted
    assert result.fixed_violations == (
        ViolationKey("R-x", ("x",), "lower").stable_key,
    )
    assert result.remaining_violations == (
        ViolationKey("R-y", ("y",), "upper").stable_key,
    )
    assert result.checkpoint is None


def test_model_diagnosis_inputs_are_not_conflated_with_decision_repair():
    assert "model_artifacts" in required_inputs(MODEL_DIAGNOSIS)
    assert "model_diagnostics" in required_inputs(MODEL_DIAGNOSIS)
    assert "local_solver_callback" in required_inputs(DECISION_REPAIR)
    assert "objective_sense_and_independently_recomputed_objectives" in required_inputs(
        OBJECTIVE_OPTIMIZATION,
    )

    parent = {"x": 0, "y": 0, "z": 7}
    result = repair_neighborhood(
        parent,
        graph(),
        checker,
        lambda spec: {"status": "optimal", "values": {"x": 1, "y": 0}},
        mode=MODEL_DIAGNOSIS,
    )
    assert not result.accepted
    assert result.reason == "model_diagnosis_requires_model_inputs"


def test_pyscipopt_sub_milp_honors_fixed_values_and_full_check():
    pyscipopt = pytest.importorskip("pyscipopt")
    parent = {"x": 0.0, "y": 3.0, "z": 7.0}

    def milp_checker(decisions):
        violations = []
        if decisions["x"] < 2 - 1e-8:
            violations.append(violation("R-x", ("x",), "lower"))
        if decisions["x"] + decisions["y"] < 5 - 1e-8:
            violations.append(violation("R-total", ("global",), "balance"))
        return {
            "business_status": "fail" if violations else "pass",
            "violations": violations,
            "objective": decisions["x"] + decisions["y"],
        }

    def solve(spec):
        assert spec.released_variables == ("x", "y")
        assert spec.fixed_values == {"z": 7.0}
        model = pyscipopt.Model()
        model.hideOutput()
        variables = {
            name: model.addVar(name=name, vtype="I", lb=0, ub=10)
            for name in ("x", "y", "z")
        }
        for name, value in spec.fixed_values.items():
            model.addCons(variables[name] == value)
        model.addCons(variables["x"] >= 2)
        model.addCons(variables["x"] + variables["y"] >= 5)
        model.setObjective(variables["x"] + variables["y"], "minimize")
        model.optimize()
        status = model.getStatus()
        if status != "optimal":
            return {"status": status}
        return {
            "status": status,
            "values": {
                name: float(model.getVal(variables[name]))
                for name in spec.released_variables
            },
        }

    result = repair_neighborhood(parent, graph(), milp_checker, solve)

    assert result.accepted
    assert result.decisions["z"] == 7.0
    assert result.decisions["x"] >= 2
    assert result.decisions["x"] + result.decisions["y"] >= 5
    assert result.candidate_report["business_status"] == "pass"

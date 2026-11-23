from __future__ import annotations

import hashlib

import pytest

from ora_agent.declarative_neighborhood import DECISION_REPAIR, OBJECTIVE_OPTIMIZATION, DecisionArtifact
from ora_agent.federated_neighborhood import FederatedNeighborhoodRepair
from ora_agent.federated_public_ir import load_public_files, load_public_problem
from ora_agent.population_repair import (
    FEASIBLE,
    BusinessResult,
    Candidate,
    Evaluation,
    Mutation,
)
from scripts.federated_population_audit import (
    DIRECT_OPERATION,
    OBJECTIVE_OPERATION,
    OPERATIONS,
    STRATEGIES,
    _official_comparison,
    make_initial,
    make_operators,
    official_stage,
    run_strategies,
    summarize_run,
)
from scripts.federated_repair_audit import CLEAN_PATH, duplicate_client
from ora_agent.federated_public_ir import solution_file_to_artifact


@pytest.fixture(scope="module")
def repair():
    return FederatedNeighborhoodRepair(load_public_files())


def test_real_operator_payloads_bind_parent_hash_and_full_release(repair):
    files = repair.public_files
    problem = load_public_problem(files)
    clean = solution_file_to_artifact(CLEAN_PATH, files)
    wrong = duplicate_client(clean, problem, files)
    initial = make_initial(wrong, repair)

    mutations = [operator(initial) for operator in make_operators(repair)]

    assert tuple(mutation.operation for mutation in mutations) == OPERATIONS
    assert all(mutation.payload["parent_sha256"] == wrong.sha256 for mutation in mutations)
    from ora_agent.population_repair import payload_digest
    assert len({payload_digest(mutation.payload) for mutation in mutations}) == len(OPERATIONS)
    default, direct, objective = mutations
    assert default.payload["spec_signature"]["mode"] == DECISION_REPAIR
    assert 0 < default.payload["spec_signature"]["released_variable_count"] < len(repair.variable_names)
    assert direct.payload["spec_signature"]["released_variable_count"] == len(repair.variable_names)
    assert direct.payload["spec_signature"]["fixed_variable_count"] == 0
    assert objective.payload["spec_signature"]["mode"] == OBJECTIVE_OPTIMIZATION

    clean_objective = make_operators(repair)[2](make_initial(clean, repair))
    assert clean_objective.payload["spec_signature"]["mode"] == OBJECTIVE_OPTIMIZATION
    assert clean_objective.payload["parent_sha256"] == clean.sha256


def _generic_initial():
    artifact = DecisionArtifact.create({"value": 10}, b"root")
    return Candidate.seed(
        {"artifact_sha256": artifact.sha256, "root": True},
        Evaluation(
            {"source": "test"},
            BusinessResult(FEASIBLE, objective=10, sense="max"),
            cost=0.0,
            checkpoint=artifact,
            structure=artifact.sha256,
        ),
        id="root",
    )


def _generic_operators():
    deltas = dict(zip(OPERATIONS, (2.0, 3.0, -1.0)))

    def operator(parent, operation):
        return Mutation(
            operation,
            {"parent_sha256": parent.checkpoint.sha256, "parent_id": parent.id,
             "operation": operation},
            cost=0.25,
        )

    return [lambda parent, operation=operation: operator(parent, operation)
            for operation in OPERATIONS], deltas


def test_shared_root_equal_caps_exploration_and_cost_reconciliation():
    initial = _generic_initial()
    operators, deltas = _generic_operators()

    def evaluator(mutation, parent):
        objective = parent.business_result.objective + deltas[mutation.operation]
        artifact = DecisionArtifact.create(
            {"value": objective}, f"{initial.id}:{mutation.payload['parent_id']}:{mutation.operation}".encode())
        return Evaluation(
            {"solver": {"solve_seconds": 0.1}, "repair_accepted": True,
             "repair_reason": "accepted"},
            BusinessResult(FEASIBLE, objective=objective, sense="max"),
            cost=0.5,
            checkpoint=artifact,
            structure=artifact.sha256,
        )

    runs, _ = run_strategies(initial, evaluator, operators)

    assert runs["population"].evaluations == 6
    assert runs["single_chain"].evaluations == 6
    assert runs["direct_full"].evaluations == 1
    assert all(run.initial is initial for run in runs.values())
    assert runs["population"].total_cost == pytest.approx(4.5)
    assert runs["single_chain"].total_cost == pytest.approx(4.5)
    assert runs["population"].exploration
    assert runs["single_chain"].exploration
    for strategy in STRATEGIES:
        summary = summarize_run(runs[strategy])
        expected_evaluations = 1 if strategy == "direct_full" else 6
        assert summary["cost_reconciled"] is True
        assert summary["best_from_elite"] is True
        assert summary["best_role"] == "elite"
        assert summary["evaluated_candidate_count"] == expected_evaluations
        assert summary["total_search_seconds"] == pytest.approx(0.75 * expected_evaluations)
        assert summary["solver_seconds"] == pytest.approx(0.1 * expected_evaluations)


def _official_payload(objective):
    return {
        "evaluation": {"feasible": True, "objective": objective, "errors": []},
        "reward": {"feasibility": 1.0, "quality": 2.0},
        "reward_details": {"feasibility": 1.0, "quality": 2.0},
        "runner": {"return_code": 0, "timed_out": False, "wall_seconds": 0.01},
    }


def test_official_stage_re_evaluates_only_frozen_final_best(tmp_path, monkeypatch):
    def row(label):
        arms = {}
        for index, strategy in enumerate(STRATEGIES):
            raw = f"{label}:{strategy}:best".encode()
            digest = hashlib.sha256(raw).hexdigest()
            path = tmp_path / "final" / label / strategy / "solution.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            arms[strategy] = {"best_sha256": digest, "official": None}
        return {"scenario": label, "arms": arms, "official_comparisons": {}}

    audit = {
        "selection_complete": True,
        "official_feedback_used_for_candidate_selection": False,
        "official_complete": False,
        "scenarios": [row("duplicate_client")],
        "clean_control": row("clean_control"),
        "summary": {},
    }
    seen = []

    def fake_prepare(packet, workspace, artifacts, validate):
        (workspace / "submissions").mkdir(parents=True)

    def fake_official(packet, workspace, outdir):
        digest = hashlib.sha256((workspace / "submissions/solution.csv").read_bytes()).hexdigest()
        seen.append(digest)
        outdir.mkdir(parents=True)
        return _official_payload(100.0)

    monkeypatch.setattr("scripts.federated_population_audit.prepare_workspace", fake_prepare)
    monkeypatch.setattr("scripts.federated_population_audit.official_evaluate", fake_official)
    result = official_stage(None, audit, tmp_path)

    expected = {
        arm["best_sha256"]
        for item in [audit["scenarios"][0], audit["clean_control"]]
        for arm in item["arms"].values()
    }
    assert set(seen) == expected
    assert len(seen) == len(expected)
    assert result["official_complete"] is True
    assert result["official_feedback_used_for_candidate_selection"] is False
    assert all(
        arm["official"]["candidate_sha256"] == arm["best_sha256"]
        for item in [result["scenarios"][0], result["clean_control"]]
        for arm in item["arms"].values()
    )


def test_official_population_gain_is_honest_about_tie_and_negative():
    base = {"true_correct": True, "feasible": True, "quality": 2.0,
            "objective": 10.0, "evaluation_unknown": False}
    tied = _official_comparison(dict(base), dict(base))
    worse = _official_comparison({**base, "objective": 9.0}, dict(base))
    better = _official_comparison({**base, "objective": 11.0}, dict(base))
    assert tied["gain"] == "tie"
    assert worse["gain"] == "negative"
    assert better["gain"] == "positive"

from __future__ import annotations

import copy
import hashlib
import random
import sys

import pytest

if sys.version_info < (3, 10):
    pytest.skip("GEPA federated experiment tests require Python >=3.10", allow_module_level=True)

from ora_agent.declarative_neighborhood import DecisionArtifact
from ora_agent.gepa_repair import DIRECT_FULL_REOPTIMIZATION, FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION
from ora_agent.population_repair import (
    ELITE,
    EXPLORATION,
    FEASIBLE,
    INFEASIBLE,
    UNKNOWN,
    BusinessResult,
    Candidate,
    Evaluation,
    Mutation,
)
from scripts.gepa_federated_experiment import (
    ARMS,
    DIRECT_FULL,
    EVALUATION_BUDGET,
    OLD_POPULATION,
    OPERATIONS,
    PARETO_MERGE,
    PARETO_ONLY,
    CandidateBridge,
    attempt_compatible_merge,
    direct_path_coverage,
    frontier_summary,
    merge_summary,
    official_stage,
    operations_for_generation,
    run_gepa_search,
    summarize_search,
)
from scripts.federated_population_audit import DEFAULT_OPERATION


class RecordingChecker:
    def __init__(self, status="pass"):
        self.status = status
        self.calls = []

    def check(self, decisions):
        self.calls.append(copy.deepcopy(decisions))
        objective = float(decisions.get("a", 0) + decisions.get("b", 0))
        return {
            "business_status": self.status,
            "objective": objective,
            "violations": [] if self.status == "pass" else [{
                "key": "generic", "requirement_id": "generic", "status": "fail",
            }],
        }


def make_candidate(
    candidate_id,
    decisions,
    objective,
    *,
    parent=None,
    operation="initial",
    status=FEASIBLE,
    role=ELITE,
    cost=0.01,
):
    artifact = DecisionArtifact.create(decisions, f"{candidate_id}:original".encode())
    if parent is None:
        return Candidate.seed(
            {"artifact_sha256": artifact.sha256, "root": True},
            Evaluation(
                {"source": "test", "solver": {}},
                BusinessResult(status, objective=objective, sense="max"),
                cost=cost,
                checkpoint=artifact,
                structure=artifact.sha256,
            ),
            id=candidate_id,
        )
    return Candidate(
        id=candidate_id,
        parent_id=parent.id,
        operation=operation,
        payload={"operation": operation, "parent_sha256": parent.checkpoint.sha256},
        execution_result={"source": "test", "solver": {"solve_seconds": 0.01}},
        business_result=BusinessResult(status, objective=objective, sense="max"),
        cost=cost,
        checkpoint=artifact,
        generation=parent.generation + 1,
        structure=artifact.sha256,
        proposal_cost=0.0,
        evaluation_cost=cost,
        role=role,
    )


def merge_lineage(checker):
    root = make_candidate("root", {"a": 0, "b": 0}, 1.0)
    left = make_candidate(
        "left", {"a": 1, "b": 0}, 2.0,
        parent=root, operation=DEFAULT_OPERATION, cost=0.02,
    )
    right = make_candidate(
        "right", {"a": 0, "b": 1}, 3.0,
        parent=root, operation=DIRECT_FULL_REOPTIMIZATION, cost=0.03,
    )
    bridge = CandidateBridge(objective_scale=10.0, cost_scale=60.0, checker=checker)
    return root, left, right, bridge


def test_three_objective_frontiers_do_not_conflate_native_winners_and_archive():
    checker = RecordingChecker()
    root, left, right, bridge = merge_lineage(checker)
    weak = make_candidate(
        "weak", {"a": 0, "b": 0, "weak": 1}, 1.5,
        parent=root, operation=DEFAULT_OPERATION, cost=0.04,
    )

    result = frontier_summary([root, left, right, weak], bridge)

    assert result["score_keys"] == ["feasibility", "public_objective", "negative_cost"]
    assert result["native_per_key_winners"]["feasibility"] == ["left", "right", "root", "weak"]
    assert result["native_per_key_winner_count"] == 4
    assert result["non_dominated_archive_count"] == 3
    assert set(result["non_dominated_archive_ids"]) == {"root", "left", "right"}
    assert "weak" not in result["non_dominated_archive_ids"]
    assert bridge.scores(root) == {
        "feasibility": 1.0,
        "public_objective": 0.1,
        "negative_cost": pytest.approx(-0.01 / 60.0),
    }


def test_merge_is_tested_only_for_compatible_novel_full_pass():
    checker = RecordingChecker()
    root, left, right, bridge = merge_lineage(checker)

    attempt = attempt_compatible_merge(
        [root, left, right], bridge, rng=random.Random(4), merged_id="merged",
    )

    assert attempt.outcome.accepted
    assert attempt.record["compatible_observed"] is True
    assert attempt.record["novel_observed"] is True
    assert attempt.record["valid_full_public_pass"] is True
    assert attempt.record["tested"] is True
    assert attempt.record["not_tested"] is False
    assert checker.calls == [{"a": 1, "b": 1}]
    summary = merge_summary([attempt.record])
    assert summary["tested"] == 1
    assert summary["not_tested"] == 0
    assert summary["invalid"] == 0


def test_duplicate_merge_is_not_tested_and_does_not_call_full_checker():
    checker = RecordingChecker()
    root, left, right, bridge = merge_lineage(checker)
    existing = make_candidate(
        "existing", {"a": 1, "b": 1}, 4.0,
        parent=root, operation=DEFAULT_OPERATION, cost=0.04,
    )

    attempt = attempt_compatible_merge(
        [root, left, right, existing], bridge, rng=random.Random(4), merged_id="merged",
    )

    assert not attempt.outcome.accepted
    assert attempt.record["tested"] is False
    assert attempt.record["not_tested"] is True
    assert attempt.record["valid_full_public_pass"] is False
    assert checker.calls == []
    assert merge_summary([attempt.record])["invalid"] == 0


def test_failed_full_check_is_not_tested_not_invalid():
    checker = RecordingChecker("fail")
    root, left, right, bridge = merge_lineage(checker)

    attempt = attempt_compatible_merge(
        [root, left, right], bridge, rng=random.Random(4), merged_id="merged",
    )

    assert attempt.outcome.reason == "public_check_failed"
    assert attempt.record["compatible_observed"] is True
    assert attempt.record["novel_observed"] is True
    assert attempt.record["valid_full_public_pass"] is False
    assert attempt.record["tested"] is False
    assert attempt.record["not_tested"] is True
    assert merge_summary([attempt.record])["invalid"] == 0


def generic_initial(status=INFEASIBLE):
    return make_candidate("root", {"a": 0, "b": 0}, 8.0 if status == INFEASIBLE else 10.0, status=status)


def generic_operators():
    return [
        lambda parent, operation=operation: Mutation(
            operation,
            {"operation": operation, "parent_sha256": parent.checkpoint.sha256},
            cost=0.01,
        )
        for operation in OPERATIONS
    ]


def generic_evaluator(mutation, parent):
    operation = mutation.operation
    if operation == DEFAULT_OPERATION:
        if parent.id == "root" and parent.business_result.status == INFEASIBLE:
            decisions, objective, status = {"a": 1, "b": 0}, 10.0, FEASIBLE
        else:
            return Evaluation(
                {"repair_accepted": False, "repair_reason": "empty_neighborhood", "solver": {}},
                BusinessResult(UNKNOWN, sense="max", hard_errors={"empty_neighborhood"}),
                cost=0.02,
                checkpoint=parent.checkpoint,
                structure=parent.checkpoint.sha256,
            )
    elif operation == DIRECT_FULL_REOPTIMIZATION:
        decisions = {"a": 0, "b": 1}
        objective = 9.0 if parent.business_result.status == INFEASIBLE else parent.business_result.objective - 1.0
        status = FEASIBLE
    elif operation == FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION:
        if parent.business_result.status != FEASIBLE:
            return Evaluation(
                {"repair_accepted": False, "repair_reason": "optimization_requires_feasible_parent", "solver": {}},
                BusinessResult(UNKNOWN, sense="max", hard_errors={"infeasible_parent"}),
                cost=0.02,
                checkpoint=parent.checkpoint,
                structure=parent.checkpoint.sha256,
            )
        decisions = dict(parent.checkpoint.decisions)
        decisions["b"] = 1
        objective = parent.business_result.objective + 2.0
        status = FEASIBLE
    else:
        raise AssertionError(operation)
    artifact = DecisionArtifact.create(decisions)
    return Evaluation(
        {
            "repair_accepted": True,
            "repair_reason": "accepted",
            "solver": {"solve_seconds": 0.1, "solver_status": "optimal"},
            "candidate_sha256": artifact.sha256,
        },
        BusinessResult(status, objective=objective, sense="max"),
        cost=0.1,
        checkpoint=artifact,
        structure=artifact.sha256,
    )


def test_pareto_only_preserves_mutation_rotation_and_connects_direct_path():
    initial = generic_initial()
    bridge = CandidateBridge(objective_scale=8.0, checker=RecordingChecker())

    result = run_gepa_search(
        initial, generic_evaluator, generic_operators(), bridge, merge_enabled=False, seed=19,
    )
    summary = summarize_search(result, bridge, PARETO_ONLY)

    expected_operations = [*operations_for_generation(1), *operations_for_generation(2)]
    assert [proposal["operation"] for proposal in result.proposals] == expected_operations
    assert result.run.evaluations <= EVALUATION_BUDGET
    assert summary["solver_call_count"] <= EVALUATION_BUDGET
    assert summary["direct_path_coverage"]["mechanism_success"] is True
    assert summary["direct_path_coverage"]["covered_direct_candidate_ids"]
    executed = [
        event for event in summary["direct_path_events"]
        if event["event"] == "objective_operation_executed"
    ]
    assert executed and all(event["solver_called"] for event in executed)
    assert summary["cost_ledger_reconciled"] is True
    assert sum(entry["total_seconds"] for entry in summary["cost_ledger"]) == pytest.approx(
        summary["total_search_seconds"]
    )


def test_merge_arm_only_substitutes_slots_and_never_exceeds_budget():
    initial = generic_initial()
    bridge = CandidateBridge(objective_scale=8.0, checker=RecordingChecker())
    pareto = run_gepa_search(
        initial, generic_evaluator, generic_operators(), bridge, merge_enabled=False, seed=19,
    )
    merged = run_gepa_search(
        initial, generic_evaluator, generic_operators(), bridge, merge_enabled=True, seed=19,
    )
    pareto_summary = summarize_search(pareto, bridge, PARETO_ONLY)
    merge_summary_row = summarize_search(merged, bridge, PARETO_MERGE)

    assert [item["operation"] for item in merged.proposals] == [item["operation"] for item in pareto.proposals]
    assert merged.run.evaluations == pareto.run.evaluations <= EVALUATION_BUDGET
    assert merge_summary_row["solver_call_count"] == pareto_summary["solver_call_count"]
    assert merge_summary_row["solver_call_count"] <= EVALUATION_BUDGET
    assert merge_summary_row["merge"]["attempted"] > 0
    assert merge_summary_row["merge"]["tested"] == 0
    assert merge_summary_row["merge"]["not_tested"] == merge_summary_row["merge"]["attempted"]
    assert merge_summary_row["merge"]["invalid"] == 0
    assert merge_summary_row["direct_path_coverage"]["mechanism_success"] is True
    assert merge_summary_row["cost_ledger_reconciled"] is True


def test_clean_control_cannot_select_a_worse_artifact():
    initial = generic_initial(FEASIBLE)
    bridge = CandidateBridge(objective_scale=10.0, checker=RecordingChecker())

    def regressing_evaluator(mutation, parent):
        artifact = DecisionArtifact.create({"a": 0, "b": parent.generation + 1})
        return Evaluation(
            {"repair_accepted": True, "repair_reason": "accepted", "solver": {"solve_seconds": 0.1}},
            BusinessResult(FEASIBLE, objective=parent.business_result.objective - 1.0, sense="max"),
            cost=0.1,
            checkpoint=artifact,
            structure=artifact.sha256,
        )

    result = run_gepa_search(
        initial, regressing_evaluator, generic_operators(), bridge, merge_enabled=True, seed=19,
    )

    assert result.run.best is initial
    assert result.run.best.checkpoint.raw_bytes == initial.checkpoint.raw_bytes
    assert result.run.exploration
    assert all(candidate.role != ELITE for candidate in result.run.candidates[1:])


def _official_payload(objective=10.0):
    return {
        "evaluation": {"feasible": True, "objective": objective, "errors": []},
        "reward": {"feasibility": 1.0, "quality": 2.0},
        "reward_details": {"feasibility": 1.0, "quality": 2.0},
        "runner": {"return_code": 0, "timed_out": False, "wall_seconds": 0.25},
    }


def test_official_stage_rechecks_every_frozen_hash_before_any_evaluation(tmp_path, monkeypatch):
    def row(label):
        arms = {}
        frozen = {}
        for arm in ARMS:
            raw = f"{label}:{arm}".encode()
            digest = hashlib.sha256(raw).hexdigest()
            path = tmp_path / "final" / label / arm / "solution.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            arms[arm] = {
                "best_sha256": digest,
                "official": None,
                "total_search_seconds": 1.0,
                "direct_path_coverage": {"mechanism_success": arm == PARETO_ONLY},
                "merge": {"tested": 0},
            }
            frozen[f"{label}/{arm}"] = digest
        return {"scenario": label, "arms": arms}, frozen

    scenario, frozen_scenario = row("duplicate_client")
    clean, frozen_clean = row("clean_control")
    audit = {
        "selection_complete": True,
        "official_feedback_used_for_candidate_selection": False,
        "official_complete": False,
        "scenarios": [scenario],
        "clean_control": clean,
        "frozen_final_sha256": {**frozen_scenario, **frozen_clean},
        "summary": {},
    }
    calls = []

    def fake_prepare(packet, workspace, artifacts, validate):
        (workspace / "submissions").mkdir(parents=True)

    def fake_official(packet, workspace, outdir):
        assert audit["selection_complete"] is True
        calls.append(hashlib.sha256((workspace / "submissions/solution.csv").read_bytes()).hexdigest())
        return _official_payload()

    monkeypatch.setattr("scripts.gepa_federated_experiment.prepare_workspace", fake_prepare)
    monkeypatch.setattr("scripts.gepa_federated_experiment.official_evaluate", fake_official)
    result = official_stage(None, audit, tmp_path)

    assert len(calls) == 2 * len(ARMS)
    assert set(calls) == set(audit["frozen_final_sha256"].values())
    assert result["official_complete"] is True
    for item in (result["scenarios"][0], result["clean_control"]):
        for arm in ARMS:
            assert item["arms"][arm]["official"]["true_correct"] is True
            assert item["arms"][arm]["total_cost_seconds_including_official"] == pytest.approx(1.25)


def test_official_stage_fails_closed_on_post_freeze_mutation(tmp_path):
    arms = {}
    frozen = {}
    for arm in ARMS:
        raw = arm.encode()
        digest = hashlib.sha256(raw).hexdigest()
        path = tmp_path / "final" / "scenario" / arm / "solution.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        arms[arm] = {"best_sha256": digest, "official": None}
        frozen[f"scenario/{arm}"] = digest
    audit = {
        "selection_complete": True,
        "official_feedback_used_for_candidate_selection": False,
        "scenarios": [{"scenario": "scenario", "arms": arms}],
        "clean_control": {"scenario": "clean", "arms": {}},
        "frozen_final_sha256": frozen,
    }
    (tmp_path / "final" / "scenario" / DIRECT_FULL / "solution.csv").write_bytes(b"changed")

    with pytest.raises(ValueError, match="frozen elite-best changed"):
        official_stage(None, audit, tmp_path)

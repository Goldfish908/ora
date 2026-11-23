import hashlib
import json
from pathlib import Path

import pytest

from ora_agent.declarative_neighborhood import DecisionArtifact, build_neighborhood
from ora_agent.industryor_neighborhood import (
    ID9_QUESTION_SHA256,
    IndustryORNeighborhood,
    NotReadyError,
    constraint_key,
    solution_from_decisions,
)
from scripts.industryor_declarative_audit import repair_root, run_problem, score_public_answer

ROOT = Path(__file__).resolve().parents[1]
FAILED_PATH = ROOT / "tests/fixtures/industryor_failed_solution.json"
CORRECT_PATH = ROOT / "tests/fixtures/industryor_correct_solution.json"


def adapter():
    return IndustryORNeighborhood(ROOT, 9)


def test_only_qualified_registered_problem_with_reviewed_public_semantics_is_ready():
    assert adapter().public.question_sha256 == ID9_QUESTION_SHA256
    with pytest.raises(NotReadyError, match="qualified independent business audit"):
        IndustryORNeighborhood(ROOT, 1)
    with pytest.raises(NotReadyError, match="qualified independent business audit"):
        IndustryORNeighborhood(ROOT, 48)
    with pytest.raises(NotReadyError, match="no reviewed public MILP adapter"):
        IndustryORNeighborhood(ROOT, 20)


def test_not_ready_never_turns_unqualified_or_unadapted_problems_into_business_wins():
    unadapted = run_problem(ROOT, 20, FAILED_PATH)
    unqualified = run_problem(ROOT, 48, FAILED_PATH)

    assert unadapted["status"] == "not_ready"
    assert unadapted["registered_qualified"] is True
    assert unadapted["roots"] == []
    assert unqualified["status"] == "not_ready"
    assert unqualified["registered_qualified"] is False
    assert unqualified["roots"] == []


def test_decision_artifact_preserves_original_solution_bytes_and_state():
    raw = FAILED_PATH.read_bytes()
    artifact = adapter().artifact(raw)

    assert artifact.raw_bytes == raw
    assert artifact.sha256 == hashlib.sha256(raw).hexdigest()
    assert artifact.decisions["objective"] == 623.0
    assert artifact.decisions["variables"]["y2"] == 1.0
    assert artifact.decisions["state"]["solver_status"] == "optimal"
    assert solution_from_decisions(artifact.decisions) == json.loads(raw)


def test_narrow_link_violation_has_stable_key_and_bounded_dependency_release():
    subject = adapter()
    artifact = subject.artifact(FAILED_PATH.read_bytes())
    report = subject.business_report(artifact.decisions)
    expected_key = constraint_key(9, "link_x3_y2").stable_key

    assert report["business_status"] == "fail"
    assert [row["key"] for row in report["violations"]] == [expected_key]
    assert report["verdicts"]["execution_and_public_constraints"] == "fail"
    assert report["registered_audit"]["business_objective"] == 623.0
    spec = build_neighborhood(
        artifact,
        report["violations"],
        subject.graph,
        variable_names=[f"variables.{name}" for name in artifact.decisions["variables"]],
    )

    assert spec.violation_keys == (expected_key,)
    assert spec.released_variables == (
        "variables.x1", "variables.x2", "variables.x3", "variables.x4", "variables.y2",
    )
    assert spec.fixed_variables == ("variables.y1", "variables.y_A", "variables.y_R")
    assert spec.fixed_values["variables.y_A"] == 1.0
    assert spec.parent_bytes == artifact.raw_bytes


def test_same_root_repair_uses_independent_audit_not_public_answer():
    subject = adapter()
    artifact = subject.artifact(FAILED_PATH.read_bytes())
    original = DecisionArtifact.create(artifact.decisions, artifact.raw_bytes)

    def repair_values(spec):
        complete = json.loads(json.dumps(artifact.decisions))
        complete["variables"]["y2"] = 0.0
        complete["state"]["solution_count"] = 1
        return {"status": "optimal", "decisions": complete,
                "parent_sha256": spec.parent_sha256}

    from ora_agent.declarative_neighborhood import repair_neighborhood

    result = repair_neighborhood(
        original,
        subject.graph,
        subject.business_report,
        repair_values,
        variable_names=[f"variables.{name}" for name in original.decisions["variables"]],
    )

    assert result.accepted
    assert result.fixed_violations == (constraint_key(9, "link_x3_y2").stable_key,)
    assert result.selected.decisions["variables"]["y2"] == 0.0
    assert result.selected.decisions["variables"]["y_A"] == 1.0
    assert result.candidate_report["registered_audit"]["business_correct"] is True
    assert result.candidate_report["registered_audit"]["optimality"] == "proven_optimal"


def test_correct_root_is_retained_without_calling_solver():
    subject = adapter()
    artifact = subject.artifact(CORRECT_PATH.read_bytes())
    result = subject.repair(artifact)

    assert not result.accepted
    assert result.reason == "empty_neighborhood"
    assert result.solve_status is None
    assert result.selected.raw_bytes == artifact.raw_bytes
    assert result.selected.sha256 == artifact.sha256
    assert result.checkpoint is not None
    assert result.checkpoint.raw_bytes == artifact.raw_bytes
    assert result.parent_report["registered_audit"]["business_correct"] is True
    assert subject.solver is None


def test_objective_or_execution_failure_is_not_ready_for_narrow_adapter():
    subject = adapter()
    artifact = subject.artifact(FAILED_PATH.read_bytes())
    decisions = json.loads(json.dumps(artifact.decisions))
    decisions["objective"] = 0.0
    changed = DecisionArtifact.create(decisions)

    with pytest.raises(NotReadyError, match="outside the narrow public-constraint adapter"):
        subject.repair(changed)


def test_invalid_or_unaudited_artifact_is_not_business_correct():
    record = repair_root(adapter(), b'{"schema_version":"other"}', "bad")
    assert record["status"] == "not_ready"
    assert record["business_correct"] is None
    assert not record["public_answer_scored"]


def test_real_scip_recovers_failure_preserves_control_and_scores_answer_afterward():
    pytest.importorskip("pyscipopt")
    subject = adapter()
    failed = repair_root(subject, FAILED_PATH.read_bytes(), "narrow_failure")
    correct = repair_root(subject, CORRECT_PATH.read_bytes(), "correct_control")
    score_public_answer(failed, 623.0)
    score_public_answer(correct, 623.0)

    assert failed["status"] == "ready"
    assert failed["repair_accepted"]
    assert failed["business_recovered"]
    assert failed["fixed_violations"] == [constraint_key(9, "link_x3_y2").stable_key]
    assert failed["introduced_violations"] == []
    assert failed["solve_status"] == "optimal"
    assert failed["cost"]["scip_sub_milp_runs"] == 1
    assert failed["cost"]["llm_calls"] == 0
    assert failed["parent_business"]["business_correct"] is False
    assert failed["selected_business"]["business_correct"] is True
    assert failed["selected_business"]["independent_optimality"] == "proven_optimal"
    assert failed["parent_public_answer"]["reported_model_objective_match_abs_0_1"] is True
    assert failed["selected_public_answer"]["reported_model_objective_match_abs_0_1"] is True
    assert failed["selected"]["decisions"]["variables"]["y2"] == 0.0
    assert failed["selected"]["decisions"]["variables"]["y_A"] == 1.0

    assert correct["status"] == "ready"
    assert correct["correct_root_preserved"]
    assert correct["repair_reason"] == "empty_neighborhood"
    assert correct["cost"]["scip_sub_milp_runs"] == 0
    assert correct["selected_business"]["business_correct"] is True
    assert correct["selected_sha256"] == correct["parent_sha256"]
    assert subject.solver.runs == 1

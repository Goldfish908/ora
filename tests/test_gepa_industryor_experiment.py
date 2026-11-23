from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

if sys.version_info < (3, 10):
    pytest.skip("GEPA IndustryOR tests require Python >=3.10", allow_module_level=True)

from ora_agent.gepa_repair import DIRECT_FULL_REOPTIMIZATION
from scripts.gepa_industryor_experiment import (
    ARMS,
    DECLARATIVE,
    DIRECT_FULL,
    EVALUATION_BUDGET,
    PARETO_MERGE,
    PRIMARY_ARMS,
    ROOT_MANIFEST,
    load_root_cases,
    run_arm,
    score_frozen,
)

ROOT = Path(__file__).resolve().parents[1]
FAILED = ROOT / "work/industryor_structured_dev_v0.2/prob_020/execution_A/solution.json"
CORRECT = ROOT / "work/industryor_structured_dev_v0.2/prob_020/structured_dag/local/solution.json"
MANIFEST_DEFAULT = ROOT / "work/industryor_next_stage_v0.1/prob_020/solution.json"


def test_explicit_root_manifest_never_uses_unreliable_default_root():
    assert ROOT_MANIFEST["problem_id"] == 20
    assert ROOT_MANIFEST["validation_scope"] == "development_only_not_heldout"
    assert ROOT_MANIFEST["use_manifest_default_roots"] is False
    assert PRIMARY_ARMS == ("direct-full", "declarative", "single", "old-population", "pareto-only")
    assert set(ARMS) == set(PRIMARY_ARMS) | {PARETO_MERGE}

    cases = load_root_cases(ROOT)
    by_role = {case.role: case for case in cases}

    assert set(by_role) == {"narrow_failure", "correct_control"}
    assert by_role["narrow_failure"].path == FAILED
    assert by_role["correct_control"].path == CORRECT
    assert MANIFEST_DEFAULT not in {case.path for case in cases}
    failed_report = by_role["narrow_failure"].parent_report["registered_audit"]
    correct_report = by_role["correct_control"].parent_report["registered_audit"]
    assert failed_report["business_correct"] is False
    assert failed_report["violations"] == [
        "business constraint failed: cars_imply_blocks",
        "business constraint failed: link_x3_y3",
        "business constraint failed: link_x4_y4",
    ]
    assert correct_report["business_correct"] is True
    assert correct_report["optimality"] == "proven_optimal"
    assert by_role["correct_control"].raw == CORRECT.read_bytes()


def test_real_five_arm_and_merge_contract_uses_same_root_budget_and_public_checks():
    pytest.importorskip("pyscipopt")
    case = next(case for case in load_root_cases(ROOT) if case.role == "narrow_failure")

    results = {arm: run_arm(ROOT, case, arm, time_limit=5.0) for arm in ARMS}

    for arm, result in results.items():
        summary = result.summary
        assert summary["root_sha256"] == case.artifact.sha256
        assert summary["evaluation_budget"] == EVALUATION_BUDGET
        assert summary["child_evaluations"] <= EVALUATION_BUDGET
        assert summary["public_answer_scored"] is False
        assert summary["final_independent_audit"] is None
        assert summary["best_public"]["status"] == "FEASIBLE"
        assert summary["best_public"]["objective"] == 956.0
        assert summary["cost_reconciled"] is True
        assert summary["adapter_counters"]["business_audit_calls"] > 0
        for candidate in summary["candidates"]:
            assert "violations" in candidate
            assert candidate["parent_sha256"]
    assert results[DIRECT_FULL].summary["child_evaluations"] == 1
    assert results[DECLARATIVE].summary["child_evaluations"] == 1
    direct = results[DIRECT_FULL].summary["candidates"][0]
    assert direct["operation"] == DIRECT_FULL_REOPTIMIZATION
    assert direct["spec_signature"]["released_variable_count"] == 8
    merge = results[PARETO_MERGE].summary["merge"]
    assert merge["attempted"] > 0
    assert merge["tested"] == 0
    assert merge["not_tested"] == merge["attempted"]
    assert merge["invalid"] == 0


def frozen_audit(tmp_path: Path):
    raw = CORRECT.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    path = tmp_path / "final/correct_control/declarative/solution.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    arm = {
        "best_sha256": digest,
        "total_search_seconds": 0.25,
        "final_independent_audit": None,
        "public_answer": None,
    }
    return {
        "selection_complete": True,
        "public_answer_used_for_candidate_selection": False,
        "final_independent_audit_complete": False,
        "public_answer_scored": False,
        "frozen_final_sha256": {"correct_control/declarative": digest},
        "scenarios": [{
            "role": "correct_control",
            "artifact_path": str(CORRECT.relative_to(ROOT)),
            "root_sha256": digest,
            "arms": {"declarative": arm},
        }],
    }, path, arm


def test_final_score_and_public_answer_are_strictly_post_freeze(tmp_path):
    audit, path, arm = frozen_audit(tmp_path)
    answer_calls = []

    def answer():
        answer_calls.append(True)
        assert audit["selection_complete"] is True
        assert audit["final_independent_audit_complete"] is True
        return 956.0

    result = score_frozen(audit, ROOT, tmp_path, answer_loader=answer)

    assert answer_calls == [True]
    assert result["public_answer_scored"] is True
    assert result["final_independent_audit_complete"] is True
    assert arm["final_independent_audit"]["business_correct"] is True
    assert arm["final_independent_audit"]["optimality"] == "proven_optimal"
    assert arm["public_answer"]["business_objective_match_abs_0_1"] is True
    assert arm["public_answer"]["en_answer"] == 956.0
    assert hashlib.sha256(path.read_bytes()).hexdigest() == arm["best_sha256"]


def test_post_freeze_mutation_fails_before_score_or_answer(tmp_path):
    audit, path, arm = frozen_audit(tmp_path)
    path.write_bytes(b"changed")
    calls = []

    with pytest.raises(ValueError, match="frozen final changed"):
        score_frozen(
            audit,
            ROOT,
            tmp_path,
            answer_loader=lambda: calls.append("answer"),
            scorer=lambda *args: calls.append("score"),
        )

    assert calls == []
    assert arm["final_independent_audit"] is None
    assert audit["public_answer_scored"] is False


def test_internal_decision_bytes_are_explicitly_exported_for_final_score(tmp_path):
    from ora_agent.declarative_neighborhood import DecisionArtifact
    from ora_agent.industryor_neighborhood import IndustryORNeighborhood

    audit, path, arm = frozen_audit(tmp_path)
    artifact = IndustryORNeighborhood(ROOT, 20).artifact(CORRECT.read_bytes())
    internal_raw = DecisionArtifact.create(artifact.decisions).raw_bytes
    internal_digest = hashlib.sha256(internal_raw).hexdigest()
    path.write_bytes(internal_raw)
    arm["best_sha256"] = internal_digest
    audit["frozen_final_sha256"]["correct_control/declarative"] = internal_digest

    result = score_frozen(audit, ROOT, tmp_path, answer_loader=lambda: 956.0)

    assert arm["final_independent_audit"]["audit_status"] == "complete"
    assert arm["final_independent_audit"]["business_correct"] is True
    assert result["public_answer_scored"] is True

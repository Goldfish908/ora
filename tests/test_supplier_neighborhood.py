from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest

from ora_agent.declarative_neighborhood import OBJECTIVE_OPTIMIZATION, DecisionArtifact
from ora_agent.supplier_neighborhood import (
    ARMS,
    DECLARATIVE,
    DIRECT_FULL,
    OBJECTIVE_FAILURE_VIOLATIONS,
    PARETO,
    NotReadyError,
    SupplierNeighborhood,
    supplier_milp,
)
from scripts.supplier_neighborhood_audit import (
    ROOT_MANIFEST,
    generate_selection,
    load_root_cases,
    run,
    run_arm,
    score_frozen,
)

ROOT = Path(__file__).resolve().parents[1]
ID19_FAILED = ROOT / "work/industryor_next_stage_v0.1/prob_019/solution.json"
ID21_FAILED = ROOT / "work/industryor_next_stage_v0.1/prob_021/solution.json"
ID19_CORRECT = ROOT / "work/industryor_structured_dev_v0.2/prob_019/structured_dag/regenerate/solution.json"
ID21_CORRECT = ROOT / "work/industryor_structured_dev_v0.2/prob_021/execution_A/solution.json"
ID19_FORBIDDEN_DEFAULT = ROOT / "work/industryor_structured_dev_v0.2/prob_019/execution_A/solution.json"


def _contains_answer(value) -> bool:
    if isinstance(value, dict):
        return any(key == "en_answer" or _contains_answer(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_answer(item) for item in value)
    return False


def _case(problem_id: int, role: str = "objective_failure"):
    return next(case for case in load_root_cases(ROOT, problem_id) if case.role == role)


def test_public_milp_multiplies_unit_cost_by_quantity_per_order():
    id19 = supplier_milp(19)
    id21 = supplier_milp(21)

    assert id19.q == {"x_A": 15, "x_B": 10, "x_C": 10}
    assert id19.c == {"x_A": 50, "x_B": 45, "x_C": 40}
    assert id19.objective_coefficients == {"x_A": 750, "x_B": 450, "x_C": 400}
    assert id19.objective({"x_A": 4, "x_B": 1, "x_C": 3}) == 4650
    assert 50 * 4 + 45 * 1 + 40 * 3 == 365
    assert (id19.lower, id19.upper, id19.k) == (100, 500, 1)
    assert id19.M == {"x_A": 33, "x_B": 50, "x_C": 50}

    assert id21.q == {"x_A": 20, "x_B": 15, "x_C": 15}
    assert id21.c == {"x_A": 120, "x_B": 110, "x_C": 100}
    assert id21.objective_coefficients == {"x_A": 2400, "x_B": 1650, "x_C": 1500}
    assert id21.objective({"x_A": 3, "x_B": 2, "x_C": 4}) == 16500
    assert 120 * 3 + 110 * 2 + 100 * 4 == 980
    assert (id21.lower, id21.upper, id21.k) == (150, 600, 2)
    assert id21.M == {"x_A": 30, "x_B": 40, "x_C": 40}


def test_explicit_roots_preserve_bytes_and_assert_objective_failure_not_constraint_failure():
    assert ROOT_MANIFEST["use_manifest_default_roots"] is False
    assert ROOT_MANIFEST["validation_scope"] == "development_only_not_heldout"
    assert ARMS == (DIRECT_FULL, DECLARATIVE, PARETO)

    cases = load_root_cases(ROOT)
    by_key = {(case.problem_id, case.role): case for case in cases}
    assert set(by_key) == {
        (19, "objective_failure"), (19, "correct_control"),
        (21, "objective_failure"), (21, "correct_control"),
    }
    assert by_key[19, "objective_failure"].path == ID19_FAILED
    assert by_key[21, "objective_failure"].path == ID21_FAILED
    assert by_key[19, "correct_control"].path == ID19_CORRECT
    assert by_key[21, "correct_control"].path == ID21_CORRECT
    assert ID19_FORBIDDEN_DEFAULT not in {case.path for case in cases}

    for case in cases:
        assert case.raw == case.path.read_bytes()
        assert case.artifact.raw_bytes == case.raw
        assert case.artifact.sha256 == hashlib.sha256(case.raw).hexdigest()
        assert case.artifact.sha256 == case.root_spec["sha256"]
        assert base64.b64decode(case.artifact.to_dict()["raw_bytes_base64"]) == case.raw

    for problem_id, reported, business in ((19, 365.0, 4650.0), (21, 980.0, 16500.0)):
        score = by_key[problem_id, "objective_failure"].parent_score
        assert score["business_correct"] is False
        assert score["optimality"] == "suboptimal"
        assert score["model_objective_consistent"] is False
        assert score["violations"] == OBJECTIVE_FAILURE_VIOLATIONS
        assert score["business_objective"] == business
        assert by_key[problem_id, "objective_failure"].artifact.decisions["objective"] == reported
        assert all(score["execution_checks"].values())
        assert all(row["passed"] for row in score["variable_audit"].values())
        assert all(row["passed"] for row in score["constraint_checks"])

    for problem_id, objective in ((19, 4000.0), (21, 15000.0)):
        score = by_key[problem_id, "correct_control"].parent_score
        assert score["business_correct"] is True
        assert score["optimality"] == "proven_optimal"
        assert score["model_objective_consistent"] is True
        assert score["violations"] == []
        assert score["business_objective"] == objective


def test_objective_dependency_graph_releases_all_variables_and_no_narrow_fixed_subset():
    adapter = SupplierNeighborhood(ROOT, 19)
    case = _case(19)

    direct = adapter.build_spec(case.artifact, case.parent_score, DIRECT_FULL)
    declarative = adapter.build_spec(case.artifact, case.parent_score, DECLARATIVE)

    expected = tuple(f"variables.{name}" for name in ("x_A", "x_B", "x_C", "y_A", "y_B"))
    for spec in (direct, declarative):
        assert spec.mode == OBJECTIVE_OPTIMIZATION
        assert spec.objective_sense == "minimize"
        assert spec.released_variables == expected
        assert spec.fixed_variables == ()
        assert spec.fixed_values == {}
        assert spec.parent_bytes == case.raw
        assert spec.parent_sha256 == case.artifact.sha256
        assert spec.dependency_graph_sha256 == adapter.graph.sha256
    assert direct.violation_keys == ()
    assert len(declarative.violation_keys) == 2
    assert direct.to_dict() != declarative.to_dict()
    assert set(adapter.graph.to_dict()["adjacency"]) == set(expected)


def test_artifact_validation_is_exact_and_fail_closed():
    adapter = SupplierNeighborhood(ROOT, 19)
    value = json.loads(ID19_FAILED.read_text())
    value["variables"]["opaque"] = 0
    value["variable_types"]["opaque"] = "INTEGER"
    with pytest.raises(NotReadyError, match="exact reviewed variable set"):
        adapter.artifact(json.dumps(value).encode())

    with pytest.raises(NotReadyError, match="qualified|supported|reviewed"):
        SupplierNeighborhood(ROOT, 20)


def test_real_direct_full_and_declarative_recover_both_objective_and_optimality():
    pytest.importorskip("pyscipopt")
    direct = run_arm(ROOT, _case(19), DIRECT_FULL, time_limit=5.0)
    declarative = run_arm(ROOT, _case(21), DECLARATIVE, time_limit=5.0)

    for record, objective in ((direct, 4000.0), (declarative, 15000.0)):
        assert record["status"] == "ready"
        assert record["business_recovered"] is True
        assert record["ordinary_constraint_narrow_repair"] is False
        assert record["selected_independent_audit"]["business_correct"] is True
        assert record["selected_independent_audit"]["optimality"] == "proven_optimal"
        assert record["selected_independent_audit"]["business_objective"] == objective
        assert record["selected"]["decisions"]["objective"] == objective
        assert record["selected"]["decisions"]["variables"] == {
            "x_A": 0.0, "x_B": 0.0, "x_C": 10.0, "y_A": 0.0, "y_B": 0.0,
        }
        assert record["cost"]["scip_runs"] == 1
        assert record["cost"]["llm_calls"] == 0
        assert record["public_answer_scored"] is False
        assert record["final_independent_audit"] is None
        assert len(record["candidate_lineage"]) == 1
        candidate = record["candidate_lineage"][0]
        assert candidate["parent_sha256"] == record["parent_sha256"]
        assert candidate["accepted"] is True
        assert candidate["spec"]["released_variables"] == [
            "variables.x_A", "variables.x_B", "variables.x_C", "variables.y_A", "variables.y_B",
        ]
        assert candidate["spec"]["fixed_variables"] == []


def test_real_pareto_rejects_bookkeeping_only_suboptimum_and_keeps_lineage():
    pytest.importorskip("pyscipopt")
    record = run_arm(ROOT, _case(19), PARETO, time_limit=5.0)

    assert record["business_recovered"] is True
    assert record["selected_independent_audit"]["business_objective"] == 4000.0
    assert record["cost"]["scip_runs"] == 1
    assert len(record["candidate_lineage"]) == 2
    bookkeeping = next(row for row in record["candidate_lineage"] if row["operation"] == "objective_bookkeeping_only")
    reoptimized = next(row for row in record["candidate_lineage"] if row["operation"] == "full_milp_reoptimization")
    assert bookkeeping["accepted"] is False
    assert bookkeeping["independent_audit"]["business_correct"] is False
    assert bookkeeping["independent_audit"]["model_objective_consistent"] is True
    assert bookkeeping["independent_audit"]["optimality"] == "suboptimal"
    assert bookkeeping["independent_audit"]["business_objective"] == 4650.0
    assert bookkeeping["changed_variables"] == []
    assert reoptimized["accepted"] is True
    assert reoptimized["independent_audit"]["business_correct"] is True
    assert len(reoptimized["changed_variables"]) == 5
    assert set(record["pareto"]["frontier_candidate_ids"]) == {
        bookkeeping["candidate_id"], reoptimized["candidate_id"],
    }
    assert record["pareto"]["root_dominated_by"] == bookkeeping["candidate_id"]
    assert record["selected_candidate_id"] == reoptimized["candidate_id"]
    for row in record["candidate_lineage"]:
        assert row["parent_sha256"] == record["parent_sha256"]
        assert row["candidate_sha256"]


def test_correct_controls_are_noop_and_byte_identical_for_every_arm():
    for problem_id in (19, 21):
        case = _case(problem_id, "correct_control")
        for arm in ARMS:
            record = run_arm(ROOT, case, arm, time_limit=5.0)
            assert record["status"] == "ready"
            assert record["correct_root_preserved"] is True
            assert record["business_recovered"] is False
            assert record["selected_sha256"] == case.artifact.sha256
            assert record["selected"]["raw_bytes_base64"] == case.artifact.to_dict()["raw_bytes_base64"]
            assert record["candidate_lineage"] == []
            assert record["cost"]["scip_runs"] == 0


def test_non_objective_constraint_failure_is_not_ready_not_a_narrow_repair():
    adapter = SupplierNeighborhood(ROOT, 19)
    case = _case(19)
    decisions = copy.deepcopy(case.artifact.decisions)
    decisions["variables"]["x_C"] = 0.0
    parent = DecisionArtifact.create(decisions)
    score = adapter.score(parent)
    assert any(row["rule"] == "B_implies_C_order" and not row["passed"]
               for row in score["constraint_checks"])

    with pytest.raises(NotReadyError, match="outside joint objective-error"):
        adapter.repair(parent, score, DECLARATIVE)


@pytest.fixture(scope="module")
def frozen_id19_audit():
    pytest.importorskip("pyscipopt")
    return generate_selection(ROOT, ids=(19,), time_limit=5.0)


def test_final_audit_and_en_answer_are_strictly_post_freeze(frozen_id19_audit):
    audit = copy.deepcopy(frozen_id19_audit)
    assert audit["selection_complete"] is True
    assert audit["public_answer_scored"] is False
    assert not _contains_answer(audit)
    answer_calls = []
    score_calls = []

    def answer(problem_id):
        answer_calls.append(problem_id)
        assert audit["final_independent_audit_complete"] is True
        assert all(row["final_independent_audit"] is not None
                   for scenario in audit["scenarios"] for row in scenario["arms"].values())
        return 4000.0

    def scorer(problem_id, solution):
        score_calls.append((problem_id, solution["objective"]))
        from scripts.industryor_next_stage import score_solution
        return score_solution(problem_id, solution)

    result = score_frozen(audit, ROOT, answer_loader=answer, scorer=scorer)

    assert answer_calls == [19]
    assert len(score_calls) == 6
    assert result["public_answer_scored"] is True
    assert result["final_independent_audit_complete"] is True
    for scenario in result["scenarios"]:
        for record in scenario["arms"].values():
            assert record["final_independent_audit"]["audit_status"] == "complete"
            assert record["public_answer"]["scored_after_freeze"] is True
            assert record["public_answer"]["en_answer"] == 4000.0
            assert record["public_answer"]["business_objective_match_abs_0_1"] is True


def test_post_freeze_mutation_fails_before_score_or_answer(frozen_id19_audit):
    audit = copy.deepcopy(frozen_id19_audit)
    record = audit["scenarios"][0]["arms"][DIRECT_FULL]
    record["selected"]["raw_bytes_base64"] = base64.b64encode(b"changed").decode("ascii")
    calls = []

    with pytest.raises(ValueError, match="frozen final changed"):
        score_frozen(
            audit,
            ROOT,
            answer_loader=lambda problem_id: calls.append(("answer", problem_id)),
            scorer=lambda problem_id, solution: calls.append(("score", problem_id)),
        )
    assert calls == []


def test_real_end_to_end_writes_only_requested_audit_and_report(tmp_path):
    pytest.importorskip("pyscipopt")
    audit = run(ROOT, tmp_path, time_limit=5.0)

    assert audit["status"] == "ready"
    assert audit["summary"]["failure_arm_recoveries"] == 6
    assert audit["summary"]["failure_arm_runs"] == 6
    assert audit["summary"]["correct_control_original_bytes_preserved"] == 6
    assert audit["summary"]["correct_control_arm_runs"] == 6
    assert audit["summary"]["scip_runs"] == 6
    assert audit["summary"]["llm_calls"] == 0
    assert audit["summary"]["not_ready_problems"] == 0
    assert audit["post_freeze_public_answer"]["19"]["en_answer"] == 4000.0
    assert audit["post_freeze_public_answer"]["21"]["en_answer"] == 15000.0
    assert {path.name for path in tmp_path.iterdir()} == {"audit.json", "report.md"}
    saved = json.loads((tmp_path / "audit.json").read_text())
    assert saved["frozen_final_sha256"] == audit["frozen_final_sha256"]
    report = (tmp_path / "report.md").read_text()
    assert "development validation" in report
    assert "非 heldout" in report
    assert "不是普通约束窄修复" in report
    assert "not_ready" in report
    assert "structured_dag/regenerate/solution.json" in report


def test_post_freeze_decision_mutation_fails_before_score_or_answer(frozen_id19_audit):
    audit = copy.deepcopy(frozen_id19_audit)
    record = audit["scenarios"][0]["arms"][DIRECT_FULL]
    record["selected"]["decisions"]["variables"]["x_C"] = 9.0
    calls = []

    with pytest.raises(ValueError, match="frozen final changed"):
        score_frozen(
            audit,
            ROOT,
            answer_loader=lambda problem_id: calls.append(("answer", problem_id)),
            scorer=lambda problem_id, solution: calls.append(("score", problem_id)),
        )
    assert calls == []

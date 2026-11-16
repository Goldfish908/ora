import copy
import hashlib
import json

import pytest

from ora_agent.acceptance import can_accept
from ora_agent.dvsa_model import solve_model
from scripts import bwor_scoped_loop as loop


ELIGIBLE = ("BWOR-058", "BWOR-009", "BWOR-029", "BWOR-039", "BWOR-056", "BWOR-066")
CORRECT = ELIGIBLE[1:]


def prepared(problem_id):
    case = loop.load_screened_case(problem_id)
    assert case["eligible"] is True
    return loop.prepare_case(case)


def objective_terms(expression, coefficient, variable):
    return [item for item in expression.get("add", [])
            if item.get("mul", [None, None])[0] == coefficient
            and item.get("mul", [None, None])[1] == {"var": variable}]


def test_preregistered_screening_excludes_two_without_relabeling():
    screened = {problem_id: loop.load_screened_case(problem_id) for problem_id in loop.IDS}
    assert tuple(problem_id for problem_id, case in screened.items() if case["eligible"]) == ELIGIBLE
    assert screened["BWOR-001"]["exclusion_reason"] == "shared_variable_schema_mismatch"
    assert screened["BWOR-042"]["exclusion_reason"] == "missing_required_artifacts"
    assert screened["BWOR-058"]["initial_score"]["business_correct"] is False
    assert screened["BWOR-058"]["natural_objective_error"] is True
    assert {item["rule"] for item in
            screened["BWOR-058"]["initial_score"]["reference_audit"]["violations"]} == {"OBJECTIVE"}
    for problem_id in CORRECT:
        assert screened[problem_id]["initial_score"]["business_correct"] is True
    assert len({case["family"] for case in screened.values() if case["eligible"]}) == 6


@pytest.mark.parametrize("problem_id", ELIGIBLE)
def test_strict_gate_has_clean_natural_and_wrong_objective_cells(problem_id):
    case = prepared(problem_id)
    gate = case["gate"]
    assert gate["accepted"] is True
    assert gate["evaluation"]["dev_passed"] is True
    assert gate["evaluation"]["unknown"] == 0
    assert gate["evaluation"]["rejected_count"] == 0
    assert gate["evaluation"]["not_applicable"] == 0
    records = {record["key"]: record for record in gate["evaluation"]["records"]}
    assert records["reference_clean"]["fired"] is False
    assert records["wrong_objective"]["fired"] is True
    assert records["natural_initial"]["wrong"] is (problem_id == "BWOR-058")
    assert records["natural_initial"]["fired"] is (problem_id == "BWOR-058")
    assert gate["independent_scores"]["reference_clean"]["business_correct"] is True
    assert gate["independent_scores"]["wrong_objective"]["business_correct"] is False
    assert gate["natural_error_present"] is (problem_id == "BWOR-058")


def test_scoped_ir_uses_solution_paths_constants_and_complete_provenance():
    case = prepared("BWOR-058")
    invariant = case["spec"]["invariants"][0]
    evidence = invariant["source_evidence"]
    assert invariant["source_span"] == case["question"]
    assert evidence["span"] in evidence["text"]
    assert hashlib.sha256(evidence["text"].encode()).hexdigest() == evidence["sha256"]
    assert evidence["sha256"] == case["provenance"]["reference_model"]["sha256"]
    assert case["binding"]["question_sha256"] == hashlib.sha256(case["question"].encode()).hexdigest()
    assert case["binding"]["reference_solution_sha256"] == case["provenance"]["reference_solution"]["sha256"]
    assert all(term["path"].startswith("solution.variables.") for term in case["binding"]["terms"])
    assert "data." not in json.dumps(case["binding"]["scoped_rhs"])
    term = next(term for term in case["binding"]["terms"]
                if term["path"] == "solution.variables.x3_2")
    assert term["coefficient"] == 8.4


def test_linearization_handles_nested_constants_and_rejects_nonlinearity():
    model = {"variables": {"x": {}, "y": {}}, "data": {"coefficient": 6}}
    expression = {"add": [3, {"sub": [
        {"mul": [{"path": "data.coefficient"}, {"var": "x"}]},
        {"div": [{"neg": {"var": "y"}}, 2]},
    ]}]}
    constant, terms = loop._linear_expression(expression, model)
    assert constant == 3
    assert terms == {"x": 6, "y": 0.5}
    with pytest.raises(ValueError, match="nonlinear product"):
        loop._linear_expression({"mul": [{"var": "x"}, {"var": "y"}]}, model)
    with pytest.raises(ValueError, match="unbound objective constant path"):
        loop._linear_expression({"path": "data.missing"}, model)


def test_objective_only_patch_preserves_model_and_solves_058():
    case = prepared("BWOR-058")
    candidate = case["initial"]["model"]
    expression = case["reference"]["model"]["objective"]["expression"]
    repaired = loop.repair_objective_expression(candidate, expression)
    assert repaired["objective"]["expression"] == expression
    assert repaired["objective"]["sense"] == candidate["objective"]["sense"]
    for field in ("variables", "constraints", "data", "schema_version", "problem_id"):
        assert repaired[field] == candidate[field]
    assert objective_terms(expression, 8.4, "x3_2")
    assert not objective_terms(expression, 8.4, "x3_3")
    solved = solve_model(repaired)
    assert solved["status"] == "optimal"
    assert solved["solution"]["objective"] == 28.0
    score = loop.independent_score(case, solved["solution"])
    assert score["business_correct"] is True
    assert score["semantic_valid"] is True
    assert score["objective_correct"] is True


def test_fixed_progress_and_no_repair_share_initial_and_same_repairer(tmp_path):
    case = prepared("BWOR-058")
    results = {policy: loop.run_problem(case, policy, tmp_path) for policy in loop.POLICIES}
    assert len({row["initial_model_sha256"] for row in results.values()}) == 1
    no_repair = results["no_repair"]
    assert no_repair["accepted"] is False
    assert no_repair["baseline_fallback"] is True
    assert no_repair["final_score"]["business_correct"] is False
    assert no_repair["final_model_sha256"] == no_repair["initial_model_sha256"]
    for policy in ("fixed", "progress"):
        row = results[policy]
        assert row["accepted_round"] == 1
        assert row["final_score"]["business_correct"] is True
        assert row["reference_bound_development_recovery"] is True
        assert row["natural_first_recovery"] is False
        assert row["nl_cold_start"] is False
        assert row["solver_runs_this_run"] == 1
        assert row["tokens"] == 0
        repair = row["history"][0]["action"]
        assert repair["repairer"] == "repair_objective_expression"
        assert repair["changed_fields"] == ["objective.expression"]
    assert results["fixed"]["final_model_sha256"] == results["progress"]["final_model_sha256"]
    assert results["fixed"]["history"][0]["action"]["after_sha256"] == \
        results["progress"]["history"][0]["action"]["after_sha256"]


@pytest.mark.parametrize("problem_id", CORRECT)
@pytest.mark.parametrize("policy", ("fixed", "progress"))
def test_initially_correct_cases_stop_at_round_zero_unchanged(problem_id, policy, tmp_path):
    row = loop.run_problem(prepared(problem_id), policy, tmp_path)
    assert row["accepted_round"] == 0
    assert row["stop_reason"] == "accepted"
    assert row["round0_unchanged"] is True
    assert row["deterministic_transforms"] == 0
    assert row["solver_runs_this_run"] == 0
    assert row["final_model_sha256"] == row["initial_model_sha256"]
    assert row["history"][0]["action"]["name"] == "accept"
    assert row["final_score"]["business_correct"] is True


def test_rejected_gate_blocks_repair_and_falls_back(tmp_path):
    case = prepared("BWOR-058")
    case["gate"] = copy.deepcopy(case["gate"])
    case["gate"]["accepted"] = False
    case["gate"]["status"] = "rejected"
    row = loop.run_problem(case, "fixed", tmp_path)
    assert row["accepted"] is False
    assert row["stop_reason"] == "repair_checker_required"
    assert row["deterministic_transforms"] == 0
    assert row["solver_runs_this_run"] == 0
    assert row["final_model_sha256"] == row["initial_model_sha256"]
    assert row["final_score"]["business_correct"] is False


def test_unknown_after_repair_is_not_accepted(monkeypatch, tmp_path):
    case = prepared("BWOR-058")
    monkeypatch.setattr(loop, "solve_model", lambda *args, **kwargs: {
        "status": "optimal", "solver_calls": 1})
    row = loop.run_problem(case, "fixed", tmp_path)
    assert row["accepted"] is False
    assert row["baseline_fallback"] is True
    assert row["history"][1]["audit"]["status"] == "unknown"
    assert can_accept(row["history"][1]["audit"], "accepted") is False
    assert row["final_score"]["business_correct"] is False
    assert row["negative_result"]["kind"] == "unrecovered_natural_initial_error"


def test_no_change_repair_uses_exactly_two_opportunities(monkeypatch, tmp_path):
    case = prepared("BWOR-058")
    monkeypatch.setattr(loop, "repair_objective_expression",
                        lambda candidate, expression: copy.deepcopy(candidate))
    row = loop.run_problem(case, "fixed", tmp_path)
    assert row["stop_reason"] == "budget_exhausted"
    assert row["deterministic_transforms"] == 2
    assert row["solver_runs_this_run"] == 0
    assert len(row["history"]) == 3
    assert row["history"][-1]["round"] == 2
    assert row["accepted"] is False
    assert row["final_model_sha256"] == row["initial_model_sha256"]


def test_real_eight_problem_cohort_metrics_artifacts_and_resume(tmp_path):
    outdir = tmp_path / "cohort"
    analysis = loop.run_all(outdir)
    assert analysis["denominators"] == {
        "screened": 8, "eligible": 6, "excluded": 2, "per_arm": 6,
        "natural_recovery_opportunities": 1,
    }
    assert analysis["family_coverage"]["unique_families"] == 6
    assert analysis["family_coverage"]["by_split"] == {"dev": 1, "validation": 5}
    assert analysis["arms"]["no_repair"]["initial_reference_correct"] == 5
    assert analysis["arms"]["no_repair"]["final_reference_correct"] == 5
    for policy in ("fixed", "progress"):
        arm = analysis["arms"][policy]
        assert arm["n"] == 6
        assert arm["final_reference_correct"] == 6
        assert arm["improved"] == 1
        assert arm["reference_bound_development_recoveries"] == 1
        assert arm["natural_first_recoveries"] == 0
        assert arm["round0_unchanged"] == 5
        assert arm["solver_runs_this_run"] == 1
        assert arm["harmed_win"] == 0
        assert arm["accepted_but_reference_incorrect"] == 0
        assert arm["llm_calls"] == 0
        assert arm["tokens"] == 0
    assert all(checks["shared_initial_hash_across_arms"]
               for checks in analysis["paired_checks"].values())
    assert all(checks["fixed_progress_same_final_model"]
               for checks in analysis["paired_checks"].values())
    exclusions = {row["id"]: row["exclusion_reason"] for row in analysis["exclusions"]}
    assert exclusions == {"BWOR-001": "shared_variable_schema_mismatch",
                          "BWOR-042": "missing_required_artifacts"}
    assert len(analysis["run_config"]["config_sha256"]) == 64
    assert analysis["run_config"]["public_dataset_answers_read"] is False
    assert analysis["run_config"]["max_repairs"] == 2
    assert (outdir / "BWOR-001/exclusion.json").is_file()
    assert (outdir / "BWOR-042/exclusion.json").is_file()
    assert (outdir / "negative_results.json").is_file()
    for problem_id in ELIGIBLE:
        for name in ("model.json", "solution.json", "solve.json"):
            assert (outdir / problem_id / "shared_initial" / name).is_file()
        for name in ("spec.json", "binding.json", "gate.json", "validation_cells.json"):
            assert (outdir / problem_id / "scoped_ir" / name).is_file()
        for policy in loop.POLICIES:
            row = next(row for row in analysis["results"]
                       if row["id"] == problem_id and row["policy"] == policy)
            assert (outdir / problem_id / policy / "final/model.json").is_file()
            assert all("independent_score" in entry for entry in row["history"])
            assert all(entry["tokens"] == 0 for entry in row["history"])
    repaired = json.loads((outdir / "BWOR-058/fixed/final/model.json").read_text())
    assert repaired["objective"]["expression"] == \
        json.loads((outdir / "BWOR-058/reference/model.json").read_text())["objective"]["expression"]
    assert loop.run_all(outdir, resume=True) == analysis
    with pytest.raises(ValueError, match="different configuration"):
        loop.run_all(outdir, ids=("BWOR-058",), resume=True)

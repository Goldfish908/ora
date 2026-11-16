#!/usr/bin/env python3
"""Build and replay independently labelled Witness and repair-control scenarios."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.scoped_ir import evaluate_spec
from scripts.bwor_scoped_loop import (
    IDS as BWOR_IDS,
    independent_score as bwor_score,
    load_screened_case,
    prepare_case,
)
from scripts.industryor_next_stage import load_problem
from scripts.industryor_scoped_loop import MANIFEST, validation_cells
from scripts.scoped_ir_mamo_reuse import run_transfer

CONTROLLED = [
    ("delta_progress", "budget_difference", "local_patch/evidence_improved",
     "tests/test_repair_budget.py::test_lower_violation_delta_is_progress_and_keeps_local_patch"),
    ("error_chain", "new_error_after_repair", "regenerate/new_error_after_local_patch;stop/new_error_after_regenerate",
     "tests/test_repair_budget.py::test_new_error_after_local_patch_switches_candidate_and_stops_on_recurrence"),
    ("exact_duplicate", "duplicate_code_and_action", "stop/duplicate_action",
     "tests/test_repair_budget.py::test_exact_duplicate_action_is_rejected_for_complex_failure"),
    ("semantic_budget", "budget_difference", "local_patch;regenerate;stop/budget_exhausted_for_semantic_complex",
     "tests/test_repair_budget.py::test_complex_budget_allows_one_more_regeneration_then_stops"),
    ("unknown_missing_path", "unknown_and_missing_evidence", "acquire_evidence/needs_clarification",
     "tests/test_repair_budget.py::test_missing_data_path_requires_clarification_not_model_patch"),
    ("constraint_explosion", "constraint_explosion", "regenerate;stop/constraint_complexity_exceeded",
     "tests/test_repair_budget.py::test_constraint_explosion_only_allows_one_new_candidate"),
    ("configured_budgets", "budget_difference", "constraint_explosion/api=1/execution=2",
     "tests/test_repair_budget.py::test_custom_violation_threshold_and_execution_budget_are_explicit"),
    ("repeated_failure", "duplicate_failure", "local_patch;regenerate;stop/no_progress_after_local_patch_and_regenerate",
     "tests/test_repair_controller.py::test_repeated_failure_changes_action_then_stops_instead_of_looping"),
    ("identical_code", "duplicate_code", "regenerate/not_another_identical_local_patch",
     "tests/test_repair_controller.py::test_identical_code_and_identical_action_cannot_repeat"),
    ("accepted_stop", "false_trigger", "stop/accepted",
     "tests/test_repair_controller.py::test_accepted_candidate_stops_and_cannot_be_repaired_again"),
    ("missed_wrong_cell", "missed_trigger", "dev_rejected/every_wrong_cell_must_fire",
     "tests/test_scoped_ir.py::test_dev_pass_requires_every_wrong_cell_to_fire"),
    ("unknown_rejected_checker", "unknown_and_checker_rejection", "acquire_evidence;repair_checker",
     "tests/test_repair_controller.py::test_unknown_and_rejected_checker_are_not_accepted"),
    ("known_api_recurrence", "known_api_and_duplicate_failure", "specialized_api_repair;stop",
     "tests/test_repair_controller.py::test_specialized_api_repair_is_not_retried_on_the_same_failure"),
    ("zero_budget", "budget_exhaustion", "stop/budget_exhausted",
     "tests/test_repair_controller.py::test_budget_exhaustion_stops_before_another_repair"),
    ("unvalidated_checker", "unknown_checker", "acquire_evidence/checker_validation_required",
     "tests/test_repair_controller.py::test_unvalidated_checker_cannot_accept_surface_clean_candidate"),
    ("truncated_json", "malformed_json", "contract_invalid/no_identifier_or_model_promotion",
     "tests/test_candidate_contract.py::test_truncated_nested_object_is_not_promoted_to_candidate"),
    ("undefined_data_path", "undefined_data_path", "invalid_spec/before_solver",
     "tests/test_candidate_contract.py::test_undefined_data_path_is_rejected_before_solving"),
    ("duplicate_variable", "schema_failure", "contract_invalid/duplicate_variable",
     "tests/test_candidate_contract.py::test_candidate_entrypoint_preserves_response_and_separates_statuses[duplicate-contract_invalid]"),
    ("wrong_problem_id", "problem_id_failure", "contract_invalid/problem_id_mismatch",
     "tests/test_candidate_contract.py::test_candidate_entrypoint_preserves_response_and_separates_statuses[problem_id-contract_invalid]"),
    ("shared_schema", "shared_schema_failure", "invalid_shared_schema/no_solver",
     "tests/test_candidate_contract.py::test_candidate_entrypoint_preserves_response_and_separates_statuses[shared_schema-invalid_shared_schema]"),
    ("solve_failure", "execution_failure", "solve_failed/not_business_correct",
     "tests/test_candidate_contract.py::test_candidate_entrypoint_preserves_response_and_separates_statuses[solve-solve_failed]"),
]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=1) + "\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def controlled_scenarios() -> list[dict]:
    return [{
        "scenario_id": f"control.{name}", "dataset": "controlled_counterexample",
        "source_kind": "manually_labelled_controlled_counterexample",
        "category": category,
        "input": {"code_and_evidence": "defined by the referenced test, independently of the controller action"},
        "label": {"expected_action_or_status": expected,
                  "label_source": "predeclared test oracle, not inferred from a new controller trace"},
        "exposure": "controlled_development_regression",
        "validation": {"test_node": node},
    } for name, category, expected, node in CONTROLLED]


def industry_scenarios() -> list[dict]:
    manifest = json.loads(MANIFEST.read_text())
    rows = {row["id"]: row for row in manifest["problems"]}
    scenarios = []
    for problem_id in (19, 20, 21):
        question = rows[problem_id]["question"]
        spec_path = ROOT / f"work/industryor_scoped_loop_v0.6/prob_{problem_id:03d}/fixed/spec.json"
        spec = json.loads(spec_path.read_text())
        problem = load_problem(problem_id)
        cells = validation_cells(problem_id, problem.solution)
        records = evaluate_spec(spec, question, cells, str(problem_id))["records"]
        for cell, record in zip(cells, records):
            score = problem.scorer(cell["solution"])
            scenarios.append({
                "scenario_id": f"industryor.{problem_id}.{cell['key']}",
                "dataset": "IndustryOR", "source_kind": "natural_initial_or_independent_mutation",
                "category": cell["mutation"], "input": {"question": question, "solution": cell["solution"]},
                "label": {"witness_should_fire": cell["wrong"], "business_correct": score["business_correct"],
                          "label_source": "independent variable/constraint/objective/optimality scorer"},
                "observed": {"asset_status": record["status"], "asset_fired": record["fired"],
                             "business_correct": score["business_correct"], "business_score": score},
                "evidence": {"spec": relative(spec_path), "spec_sha256": digest(spec_path),
                             "source_manifest": relative(MANIFEST), "source_manifest_sha256": digest(MANIFEST),
                             "scorer": "scripts/industryor_next_stage.py:score_solution"},
                "exposure": "historical_development_not_frozen",
                "trajectory": f"work/industryor_scoped_loop_v0.6/prob_{problem_id:03d}/fixed/result.json",
            })
    return scenarios


def bwor_scenarios() -> list[dict]:
    scenarios = []
    for problem_id in BWOR_IDS:
        screened = load_screened_case(problem_id)
        if not screened["eligible"]:
            continue
        case = prepare_case(screened)
        cells = case["cells"]
        records = evaluate_spec(case["spec"], case["question"], cells, problem_id)["records"]
        for cell, record in zip(cells, records):
            score = bwor_score(case, cell["solution"])
            scenarios.append({
                "scenario_id": f"bwor.{problem_id}.{cell['key']}",
                "dataset": "BWOR", "source_kind": "shared_natural_initial_or_reference_mutation",
                "category": cell["mutation"], "input": {"question": case["question"], "solution": cell["solution"]},
                "label": {"witness_should_fire": cell["wrong"], "business_correct": score["business_correct"],
                          "label_source": "independent reference model and solution scorer"},
                "observed": {"asset_status": record["status"], "asset_fired": record["fired"],
                             "business_correct": score["business_correct"], "business_score": score},
                "evidence": {"provenance": case["provenance"],
                             "scorer": "scripts/bwor_scoped_loop.py:independent_score"},
                "exposure": "historical_development_or_validation_replay_not_frozen",
                "trajectory": f"work/bwor_scoped_loop_v0.2/{problem_id}/fixed/result.json",
            })
    return scenarios


def mamo_scenarios(outdir: Path) -> tuple[list[dict], dict]:
    result = run_transfer(outdir / "mamo_gate_replay")
    spec = json.loads((outdir / "mamo_gate_replay/spec.json").read_text())
    cells = result["domain_cells"]
    records = evaluate_spec(spec, result["binding"]["source_span"], cells, "2")["records"]
    scenarios = []
    for cell, record in zip(cells, records):
        scenarios.append({
            "scenario_id": f"mamo.2.{cell['key']}", "dataset": "MAMO-ComplexLP",
            "source_kind": "domain_counterexample_with_unavailable_business_label",
            "category": "unsupported_integer_transfer",
            "input": {"question_excerpt": result["binding"]["source_span"], "solution": cell["solution"]},
            "label": {"witness_should_fire": None, "business_correct": None,
                      "gate_decision": "reject_missing_integer_evidence",
                      "label_source": "text/reference audit; no independent integer or full business evidence"},
            "observed": {"asset_status": record["status"], "asset_fired": record["fired"],
                         "rejected": record["rejected"]},
            "exposure": "historical_development_negative_transfer",
            "trajectory": relative(outdir / "mamo_gate_replay/analysis.json"),
        })
    lifecycle = {
        "lifecycle_id": "mamo.variable_domain.rejected_rollback.v0.2",
        "asset": result["asset"], "source": result["input_manifest"],
        "decision": "rejected_and_rolled_back", "registry_status": "not_promoted",
        "reason": result["negative_result"],
        "counterexamples": [row["scenario_id"] for row in scenarios],
        "gate": result["gate"], "rollback": result["rollback"],
        "replay": relative(outdir / "mamo_gate_replay/analysis.json"),
        "cost": {"authoring_llm_calls": 0, "repair_llm_calls": 0,
                 "solver_runs_this_run": result["solver_runs_this_run"]},
        "negative_result": "Historical public-objective improvement is not promoted to business recovery.",
        "historical_unpromoted_observation": "work/scoped_ir_mamo_reuse_v0.1/analysis.json",
    }
    return scenarios, lifecycle


def run_controller_tests(outdir: Path) -> dict:
    command = [sys.executable, "-m", "pytest", "-q", *(row[3] for row in CONTROLLED)]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
    output = completed.stdout + completed.stderr
    (outdir / "controller_pytest.txt").write_text(output)
    return {"command": command, "returncode": completed.returncode,
            "passed": completed.returncode == 0, "n_scenarios": len(CONTROLLED),
            "output": "controller_pytest.txt"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="work/witness_scenario_validation_v0.1")
    args = parser.parse_args()
    outdir = ROOT / args.out
    outdir.mkdir(parents=True, exist_ok=True)
    scenarios = industry_scenarios() + bwor_scenarios()
    mamo, lifecycle = mamo_scenarios(outdir)
    scenarios.extend(mamo)
    scenarios.extend(controlled_scenarios())
    controller = run_controller_tests(outdir)
    for row in scenarios:
        if row["source_kind"] == "manually_labelled_controlled_counterexample":
            row["validation"]["status"] = "passed" if controller["passed"] else "not_verified"
        else:
            row["validation"] = {"status": "replayed", "new_llm_calls": 0}
    with (outdir / "scenarios.jsonl").open("w") as handle:
        for row in scenarios:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    write_json(outdir / "asset_lifecycle.json", lifecycle)
    coverage = sorted({row["category"] for row in scenarios})
    required = {
        "duplicate_code_and_action", "new_error_after_repair", "false_trigger",
        "unknown_and_missing_evidence", "problem_id_failure", "malformed_json",
        "schema_failure", "constraint_explosion", "budget_difference",
    }
    manifest = {
        "schema_version": "witness.scenario_validation.v0.1",
        "protocol": "docs/paper/witness_repair_validation_protocol_v0.1.md",
        "exposure": "historical_development_and_controlled_regression_not_frozen",
        "scenario_count": len(scenarios),
        "business_scored_scenarios": sum(row["label"].get("business_correct") is not None for row in scenarios),
        "controlled_counterexamples": len(CONTROLLED),
        "negative_transfer_scenarios": len(mamo),
        "coverage": coverage,
        "required_coverage_present": sorted(required & set(coverage)),
        "required_coverage_missing": sorted(required - set(coverage)),
        "new_llm_calls": 0,
        "controller_tests": controller,
        "implementation_sha256": {name: digest(ROOT / name) for name in (
            "scripts/witness_scenario_validate.py", "ora_agent/repair_controller.py",
            "ora_agent/scoped_ir.py", "ora_agent/scoped_assets.py",
            "scripts/industryor_scoped_loop.py", "scripts/bwor_scoped_loop.py",
            "scripts/scoped_ir_mamo_reuse.py", "scripts/dvsa_win_safe_replay.py",
            "scripts/dvsa_retail_core.py", "ora_agent/flow_shop.py",
            "ora_agent/flow_shop_repair.py", "assets/scoped_ir/job_precedence_v0.1.json",
            "ora_agent/binding_protocol.py", "scripts/binding_validation_demo.py",
            "ora_agent/evidence_dag.py", "scripts/cold_start_binding.py",
            "scripts/internal_cold_start.py", "scripts/historical_cold_start.py",
            "scripts/cross_family_dag.py")},
        "source_analysis_sha256": {name: digest(ROOT / name) for name in (
            "work/dvsa/retailopt_win_safe_v0.1/analysis.json",
            "work/industryor_scoped_loop_v0.6/analysis.json",
            "work/bwor_scoped_loop_v0.2/analysis.json",
            "work/scoped_ir_mamo_scope_v0.2/analysis.json")},
        "files": {"scenarios": "scenarios.jsonl", "asset_lifecycle": "asset_lifecycle.json",
                  "controller_test_output": "controller_pytest.txt"},
        "label_boundary": "Witness scope labels and full business-correctness labels are separate; UNKNOWN is never promoted to a business pass.",
    }
    write_json(outdir / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=1))
    if len(scenarios) < 20 or required - set(coverage) or not controller["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

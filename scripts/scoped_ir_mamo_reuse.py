#!/usr/bin/env python3
"""Audit MAMO integer-domain transfer without treating an objective match as semantic proof."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.acceptance import can_accept
from ora_agent.scoped_assets import compile_asset, load_asset, validate_asset
from ora_agent.scoped_ir import evaluate_spec
from scripts.m1_pilot import run_code
from scripts.m3_industryor import force_integer_variables
from scripts.scoped_ir_e2e import current_cell
from scripts.scoped_ir_gate import gate


def objective_score(solution: dict, answer: float) -> dict:
    if not isinstance(solution, dict):
        return {"business_correct": False, "objective_correct": False}
    error = abs(float(solution["objective"]) - answer)
    return {"business_correct": error <= 0.1,
            "objective_correct": error <= 0.1,
            "objective_absolute_error": error}


def file_record(path: Path) -> dict:
    return {"path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def domain_cells(solution: dict) -> list[dict]:
    integer = copy.deepcopy(solution)
    integer["variables"] = {name: round(value) for name, value in solution["variables"].items()}
    zero = copy.deepcopy(solution)
    zero["variables"] = {name: 0.0 for name in solution["variables"]}
    return [
        {"key": "domain_integer_clean", "wrong": False,
         "mutation": "integer_only_not_business_optimum", "reference_violations": [],
         "solution": integer},
        {"key": "domain_zero_clean", "wrong": False,
         "mutation": "zero_integer_only_not_business_optimum", "reference_violations": [],
         "solution": zero},
        {"key": "natural_fractional_wrong", "wrong": True,
         "mutation": "fractional_value_under_unproven_integer_assumption",
         "reference_violations": ["domain_integer"], "solution": solution},
    ]


def run_transfer(outdir: Path) -> dict:
    problem_id = "2"
    dataset_path = ROOT / "data/external/mamo_complex_lp.json"
    code_path = ROOT / "runs/industryor/sandbox/z2_mamo_base4__2__r2/gen.py"
    solution_path = code_path.with_name("solution.json")
    template_path = ROOT / "assets/scoped_ir/variable_domain_v0.1.json"
    row = next(row for row in json.loads(dataset_path.read_text())
               if str(row["id"]) == problem_id)
    question = row["en_question"]
    code = code_path.read_text()
    solution = json.loads(solution_path.read_text())
    asset = load_asset(template_path)
    if validate_asset(asset)["status"] != "validated":
        raise ValueError("integer-domain template failed its controlled validation")
    binding = {
        "invariant_id": "mamo_countable_food_domain",
        "source_span": "Food_1",
        "terms": [{"path": f"solution.variables.{name}"} for name in solution["variables"]],
    }
    spec = compile_asset(asset, binding)
    cells = domain_cells(solution)
    gate_result = gate(spec, question, cells, problem_id)
    initial_audit = evaluate_spec(spec, question, [current_cell(solution)], problem_id)["records"][0]
    accepted = can_accept(initial_audit, gate_result)
    execution = None
    final_solution = solution
    final_audit = initial_audit
    if gate_result["accepted"] and not accepted:
        repaired_code = force_integer_variables(code)
        execution = run_code(repaired_code, outdir / "repaired")
        repaired_path = outdir / "repaired/solution.json"
        repaired = json.loads(repaired_path.read_text()) if repaired_path.exists() else None
        final_audit = evaluate_spec(spec, question, [current_cell(repaired)], problem_id)["records"][0]
        if can_accept(final_audit, gate_result):
            final_solution = repaired
    initial_score = objective_score(solution, float(row["en_answer"]))
    final_score = objective_score(final_solution, float(row["en_answer"]))
    promoted = final_solution is not solution
    result = {
        "problem_id": problem_id,
        "status": "completed" if promoted else "rejected_missing_integer_evidence",
        "reuse_type": "frozen_template_new_binding_with_gate",
        "exposure": "historical_development_not_frozen",
        "authoring_llm_calls": 0,
        "repair_llm_calls": 0,
        "solver_runs_this_run": 1 if execution is not None else 0,
        "asset": {"mechanism_id": asset["mechanism_id"], "version": asset["version"],
                  **file_record(template_path)},
        "input_manifest": {"code": file_record(code_path), "solution": file_record(solution_path),
                           "dataset": file_record(dataset_path)},
        "binding": binding,
        "gate": gate_result,
        "domain_cells": cells,
        "initial_audit": initial_audit,
        "final_audit": final_audit,
        "initial_score": initial_score,
        "final_score": final_score,
        "execution": execution,
        "score_scope": "public_objective_match_only_not_business_semantic_validation",
        "independent_business_scoring_available": False,
        "accepted": promoted,
        "improved": not initial_score["objective_correct"] and final_score["objective_correct"],
        "harmed_win": initial_score["objective_correct"] and not final_score["objective_correct"],
        "rollback": {"applied": not promoted, "reason": "candidate_or_gate_not_accepted",
                     "initial_solution_retained": not promoted},
        "negative_result": None if promoted else {
            "kind": "unsupported_integer_domain_transfer",
            "reason": "MAMO food quantities have no explicit integer text or independent domain reference.",
            "deployment_permitted": False,
            "public_objective_improvement_is_not_business_recovery": True,
        },
    }
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n")
    (outdir / "gate.json").write_text(json.dumps(gate_result, ensure_ascii=False, indent=1) + "\n")
    (outdir / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    return result


def main() -> None:
    result = run_transfer(ROOT / "work/scoped_ir_mamo_reuse_v0.2")
    print(json.dumps({key: result[key] for key in
                      ("status", "reuse_type", "authoring_llm_calls", "repair_llm_calls",
                       "solver_runs_this_run", "initial_score", "final_score", "rollback")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

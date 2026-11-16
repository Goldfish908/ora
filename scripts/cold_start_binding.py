#!/usr/bin/env python3
"""Cold-start binding validation and a real-error evidence DAG comparison."""
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.binding_protocol import BindingProposal, registry
from ora_agent.dvsa_linear import linearize
from ora_agent.dvsa_model import solve_model
from ora_agent.evidence_dag import CandidateNode, EvidenceDAG
from scripts.binding_validation_demo import evaluate_case, file_record, label
from scripts.bwor_scoped_loop import (
    digest,
    independent_score,
    load_screened_case,
    prepare_case,
    repair_objective_expression,
    scoped_objective,
)
from scripts.industryor_next_stage import MANIFEST, load_problem
from scripts.industryor_scoped_loop import CASES, independent_clean

PROTOCOL = ROOT / "docs/paper/cold_start_binding_protocol_v0.1.md"


def objective_case(available: dict) -> dict:
    case = prepare_case(load_screened_case("BWOR-058"))
    question = case["question"]
    cells = [label(cell, "independent BWOR reference model and solution") for cell in case["cells"]]
    _, binding, _ = scoped_objective(case)
    payload = {**binding, "source_evidence": case["spec"]["invariants"][0]["source_evidence"]}
    proposal = BindingProposal("objective_recompute", "reference_assisted", question, payload)
    candidate = case["initial"]["model"]
    coefficients, constant = linearize(candidate["objective"]["expression"], candidate)
    cold_payload = {
        "invariant_id": "candidate_derived_objective",
        "source_span": question,
        "terms": [{"path": f"solution.variables.{name}", "coefficient": coefficient}
                  for name, coefficient in coefficients.items()],
        "constant": constant,
    }
    missing_payload = copy.deepcopy(payload)
    missing_payload["source_span"] = "not a verbatim source span"
    result = evaluate_case(proposal, question, cells,
                           lambda solution, _: independent_score(case, solution),
                           cold_payload, missing_payload, available)
    return {"family": "BWOR_objective_recompute", "case": case, "cells": cells,
            "valid_proposal": proposal, "cold_payload": cold_payload, **result}


def resource_case(available: dict) -> dict:
    problem_id = 19
    problem = load_problem(problem_id)
    manifest = json.loads(MANIFEST.read_text())
    question = next(row["question"] for row in manifest["problems"] if row["id"] == problem_id)
    case = CASES[problem_id]
    clean = independent_clean(problem_id, problem.solution)
    wrong = copy.deepcopy(clean)
    wrong["variables"] = dict(clean["variables"], x_C=51.0)
    wrong["objective"] = 51 * case["unit_cost"]["x_C"] * case["per_order"]["x_C"]
    cells = [
        label({"key": "reference_clean", "wrong": False, "mutation": "independent_optimal_orders",
               "reference_violations": [], "solution": clean},
              "IndustryOR independent business scorer and bounded enumeration"),
        label({"key": "wrong_capacity", "wrong": True, "mutation": "chairs_above_500",
               "reference_violations": ["resource_bound"], "solution": wrong},
              "IndustryOR independent business scorer and bounded enumeration"),
    ]
    payload = {
        "invariant_id": "industryor_19_chair_capacity",
        "source_span": question,
        "terms": [{"path": f"solution.variables.{name}", "coefficient": case["per_order"][name]}
                  for name in ("x_A", "x_B", "x_C")],
        "relation": "le", "limit": case["maximum"],
    }
    proposal = BindingProposal("resource_bound", "reference_assisted", question, payload)
    wrong_payload = copy.deepcopy(payload)
    wrong_payload["limit"] = 99
    missing_payload = copy.deepcopy(payload)
    missing_payload["source_span"] = "not a verbatim source span"
    result = evaluate_case(proposal, question, cells,
                           lambda solution, _: problem.scorer(solution),
                           wrong_payload, missing_payload, available)
    return {"family": "IndustryOR_resource_bound", "inputs": {"manifest": file_record(MANIFEST)}, **result}


def real_error_dag(case_data: dict, outdir: Path) -> dict:
    case = case_data["case"]
    initial = case["initial"]
    initial_model = initial["model"]
    root = CandidateNode(
        node_id="root_initial", candidate_hash=digest(initial_model), parent_id=None,
        action="initial_no_repair", binding_sha256=case_data["wrong_binding"]["binding_sha256"],
        binding_status="rejected", execution=initial["solve"], business_audit=case["initial_score"],
        solver_runs=0, llm_calls=0)
    dag = EvidenceDAG()
    dag.add(root)
    repaired = repair_objective_expression(initial_model, case["reference"]["model"]["objective"]["expression"])
    execution = solve_model(repaired, time_limit=60.0)
    score = independent_score(case, execution.get("solution"))
    valid_branch = CandidateNode(
        node_id="reference_objective_patch", candidate_hash=digest(repaired), parent_id=root.node_id,
        action="reference_assisted_objective_patch",
        binding_sha256=case_data["valid"]["binding_sha256"], binding_status="validated",
        execution=execution, business_audit=score, solver_runs=1, llm_calls=0)
    dag.add(valid_branch)
    cold_branch = CandidateNode(
        node_id="candidate_derived_binding", candidate_hash=root.candidate_hash, parent_id=root.node_id,
        action="candidate_derived_binding", binding_sha256=case_data["wrong_binding"]["binding_sha256"],
        binding_status=case_data["wrong_binding"]["status"], execution=initial["solve"],
        business_audit=case["initial_score"], solver_runs=0, llm_calls=0)
    dag.add(cold_branch)
    single_execution = solve_model(repaired, time_limit=60.0)
    single_score = independent_score(case, single_execution.get("solution"))
    single = {"accepted": single_score["business_correct"], "solver_runs": 1,
              "candidate_hash": digest(repaired), "execution": single_execution,
              "business_audit": single_score, "new_llm_calls": 0}
    record = dag.to_dict()
    record["single_line"] = single
    record["comparison"] = {
        "same_business_correct": len(dag.accepted()) == 1 and single["accepted"],
        "same_solver_runs": record["total_solver_runs"] == single["solver_runs"] == 1,
        "dag_incremental_benefit": "not_demonstrated",
        "negative_branches_preserved": len(dag.negative_branches()),
        "valid_recovery_is_not_controller_gain": True,
    }
    record["source_inputs"] = case["provenance"]
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "dag.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n")
    return record


def main() -> None:
    available = registry()
    objective = objective_case(available)
    resource = resource_case(available)
    outdir = ROOT / "work/cold_start_binding_v0.1"
    dag = real_error_dag(objective, outdir)
    cases = [{key: value for key, value in objective.items()
              if key not in {"case", "cells", "valid_proposal", "cold_payload"}}, resource]
    summary = {
        "families": 2,
        "valid_bindings": sum(case["valid"]["accepted"] for case in cases),
        "wrong_bindings_rejected": sum(case["wrong_binding"]["status"] == "rejected" for case in cases),
        "missing_evidence_unknown": sum(case["missing_evidence"]["status"] == "unknown" for case in cases),
        "conflicts_unknown": sum(case["conflict_alternatives"]["status"] == "unknown" for case in cases),
        "accepted_but_business_incorrect": sum(
            case["valid"]["accepted"] and not case["valid"]["business_audit"]["business_correct"]
            for case in cases),
        "new_llm_calls": 0,
    }
    analysis = {
        "run_config": {
            "schema_version": "cold_start_binding.validation.v0.1",
            "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
            "exposure": "historical_development_saved_candidates_not_new_llm_or_frozen",
            "proposal_sources": {
                "valid": "reference_assisted",
                "candidate_derived": "saved natural candidate expression; no new LLM call",
            },
            "implementation_sha256": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                    "ora_agent/binding_protocol.py", "ora_agent/evidence_dag.py",
                    "ora_agent/scoped_assets.py", "ora_agent/scoped_ir.py",
                    "scripts/cold_start_binding.py")},
            "new_llm_calls": 0,
        },
        "summary": summary, "cases": cases, "dag": dag,
        "lifecycle": {
            "valid": "validated_in_demonstrated_scope_not_auto_promoted",
            "wrong_or_unknown": "rejected_not_promoted",
            "rollback": "root_initial is preserved with its hash and original negative audit",
            "negative_result": "Protocol reuse and one reference-bound recovery do not establish cross-family learning or DAG gains",
        },
    }
    (outdir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"summary": summary, "dag_comparison": dag["comparison"]}, ensure_ascii=False, indent=1))
    if summary != {"families": 2, "valid_bindings": 2, "wrong_bindings_rejected": 2,
                   "missing_evidence_unknown": 2, "conflicts_unknown": 2,
                   "accepted_but_business_incorrect": 0, "new_llm_calls": 0}:
        raise SystemExit(1)
    if not all(dag["comparison"][key] for key in
               ("same_business_correct", "same_solver_runs", "negative_branches_preserved")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

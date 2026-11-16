#!/usr/bin/env python3
"""Validate historical Qwen candidate-derived bindings against reference-assisted controls."""
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.binding_protocol import BindingProposal, evaluate_alternatives, registry, validate_proposal
from ora_agent.dvsa_linear import linearize
from ora_agent.dvsa_model import (
    extract_json,
    normalize_candidate,
    normalize_candidate_paths,
    solve_model,
    validate_candidate_paths,
    validate_model,
)
from ora_agent.dvsa_repair import schema_errors
from scripts.binding_validation_demo import evaluate_case, file_record, label
from scripts.dvsa_bwor_reference import load_rows
from scripts.frozen_scoped_evaluate import load_case as load_frozen_case
from scripts.bwor_scoped_loop import (
    independent_score,
    prepare_case,
    scoped_objective,
)

SOURCE = ROOT / "work/frozen_scoped_milestone_v0.1/BWOR-002/initial"
PROTOCOL = ROOT / "docs/paper/historical_cold_start_protocol_v0.1.md"


def load_case() -> tuple[dict, dict, dict]:
    response_path = SOURCE / "response.json"
    original_path = SOURCE / "result.json"
    original = json.loads(original_path.read_text())
    response = json.loads(response_path.read_text())
    raw = extract_json(response["content"])
    candidate = normalize_candidate(raw)
    validate_model(candidate)
    candidate, path_changes = normalize_candidate_paths(candidate)
    validate_candidate_paths(candidate)
    answers = {row["id"]: float(row["answer"]) for row in load_rows("frozen")}
    case = load_frozen_case("BWOR-002", answers)
    if schema_errors(candidate, case["reference"]["model"]["variables"]):
        raise ValueError("normalized candidate has incompatible variable schema")
    replay = solve_model(candidate, time_limit=60.0)
    if replay["status"] != "optimal":
        raise ValueError(f"historical candidate cannot solve after normalization: {replay}")
    case["initial"] = {"model": candidate, "solution": replay["solution"], "solve": replay}
    case["initial_score"] = independent_score(case, replay["solution"])
    case["natural_objective_error"] = not case["initial_score"]["business_correct"]
    source = {
        "response": file_record(response_path), "original_result": file_record(original_path),
        "generator": original["generator"], "original_llm_calls": original["llm_calls"],
        "original_usage": original["usage"], "path_normalizations": path_changes,
        "candidate_sha256": hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest(),
        "execution": replay,
    }
    return case, candidate, source


def objective_payload(model: dict, question: str) -> dict:
    coefficients, constant = linearize(model["objective"]["expression"], model)
    return {"invariant_id": "candidate_derived_objective", "source_span": question,
            "terms": [{"path": f"solution.variables.{name}", "coefficient": coefficient}
                      for name, coefficient in coefficients.items()], "constant": constant}


def resource_payload(model: dict, constraint_id: str) -> dict:
    constraint = next(row for row in model["constraints"] if row["constraint_id"] == constraint_id)
    lhs, lhs_constant = linearize(constraint["lhs"], model)
    rhs, rhs_constant = linearize(constraint["rhs"], model)
    return {"invariant_id": f"candidate_derived_{constraint_id}",
            "source_span": constraint["source"], "relation": constraint["relation"],
            "terms": [{"path": f"solution.variables.{name}", "coefficient": coefficient}
                      for name, coefficient in lhs.items()],
            "limit": rhs_constant - lhs_constant}


def evaluate_pair(cold: BindingProposal, reference: BindingProposal,
                  question: str, cells: list[dict], scorer, available: dict,
                  wrong_payload: dict, missing_payload: dict) -> dict:
    return {
        "cold_start": validate_proposal(cold, question, cells, scorer, available),
        "reference_assisted": validate_proposal(reference, question, cells, scorer, available),
        "wrong_binding": validate_proposal(
            BindingProposal(cold.mechanism_id, "cold_start_proposal", cold.source_span, wrong_payload),
            question, cells, scorer, available),
        "missing_evidence": validate_proposal(
            BindingProposal(cold.mechanism_id, "cold_start_proposal", "not in question", missing_payload),
            question, cells, scorer, available),
        "conflict": evaluate_alternatives([
            cold, BindingProposal(cold.mechanism_id, "cold_start_proposal", "not in question", missing_payload)
        ], question, cells, scorer, available),
    }


def objective_case(case: dict, candidate: dict, available: dict) -> dict:
    question = case["question"]
    cells = [label(cell, "independent BWOR reference model and solution") for cell in case["cells"]]
    cold = BindingProposal("objective_recompute", "cold_start_proposal", question,
                           objective_payload(candidate, question))
    _, reference_payload, _ = scoped_objective(case)
    reference = BindingProposal("objective_recompute", "reference_assisted", question,
                                {**reference_payload,
                                 "source_evidence": case["spec"]["invariants"][0]["source_evidence"]})
    wrong = objective_payload(candidate, question)
    wrong["terms"] = []
    return evaluate_pair(cold, reference, question, cells,
                         lambda solution, _: independent_score(case, solution), available,
                         wrong, {**wrong, "terms": []})


def resource_case(case: dict, candidate: dict, available: dict) -> dict:
    question = case["question"]
    clean = case["reference"]["solution"]
    wrong_solution = copy.deepcopy(clean)
    wrong_solution["variables"] = dict(clean["variables"])
    wrong_solution["variables"]["x4"] = max(0.0, wrong_solution["variables"]["x4"] - 1.0)
    cells = [
        label({"key": "reference_clean", "wrong": False, "mutation": "independent_reference_clean",
               "reference_violations": [], "solution": clean},
              "independent BWOR reference model and solution"),
        label({"key": "wrong_protein", "wrong": True, "mutation": "protein_below_requirement",
               "reference_violations": ["resource_bound"], "solution": wrong_solution},
              "independent BWOR reference model and solution"),
    ]
    cold = BindingProposal("resource_bound", "cold_start_proposal", "protein",
                           resource_payload(candidate, "c_protein"))
    reference = BindingProposal("resource_bound", "reference_assisted", "protein",
                                resource_payload(case["reference"]["model"], "c_protein"))
    wrong = resource_payload(candidate, "c_protein")
    wrong["limit"] += 1
    return evaluate_pair(cold, reference, question, cells,
                         lambda solution, _: independent_score(case, solution), available,
                         wrong, wrong)


def main() -> None:
    case, candidate, source = load_case()
    available = registry()
    objective = objective_case(case, available)
    resource = resource_case(case, available)
    cases = [objective, resource]
    summary = {
        "families": 2,
        "cold_start_valid": sum(case["cold_start"]["accepted"] for case in cases),
        "reference_assisted_valid": sum(case["reference_assisted"]["accepted"] for case in cases),
        "wrong_bindings_rejected": sum(case["wrong_binding"]["status"] == "rejected" for case in cases),
        "missing_evidence_unknown": sum(case["missing_evidence"]["status"] == "unknown" for case in cases),
        "conflicts_unknown": sum(case["conflict"]["status"] == "unknown" for case in cases),
        "accepted_but_business_incorrect": sum(
            case["cold_start"]["accepted"] and not case["cold_start"]["business_audit"]["business_correct"]
            for case in cases),
        "new_llm_calls": 0,
        "new_solver_runs": 1,
    }
    analysis = {
        "run_config": {
            "schema_version": "historical_llm.cold_start_binding.v0.1",
            "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
            "exposure": "historical_qwen_candidate_new_binding_validation_not_new_llm_or_frozen",
            "proposal_sources": {
                "cold_start": "historical Qwen candidate expression/constraint after deterministic normalization",
                "reference_assisted": "independent reference model specification",
            },
            "implementation_sha256": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                    "ora_agent/binding_protocol.py", "ora_agent/dvsa_model.py",
                    "ora_agent/scoped_assets.py", "ora_agent/scoped_ir.py",
                    "scripts/historical_cold_start.py")},
            "new_llm_calls": 0,
        },
        "source": source, "summary": summary, "cases": cases,
        "lifecycle": {
            "valid": "validated in demonstrated scope; historical LLM authorship is not a proof of correctness",
            "wrong_or_unknown": "rejected_not_promoted",
            "rollback": "original response and original result are preserved with SHA256",
            "negative_result": "No current LLM call or universal transfer is demonstrated",
        },
    }
    outdir = ROOT / "work/historical_cold_start_v0.1"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "normalized_candidate.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=1) + "\n")
    (outdir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    expected = {"families": 2, "cold_start_valid": 2, "reference_assisted_valid": 2,
                "wrong_bindings_rejected": 2, "missing_evidence_unknown": 2, "conflicts_unknown": 2,
                "accepted_but_business_incorrect": 0, "new_llm_calls": 0, "new_solver_runs": 1}
    if summary != expected:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

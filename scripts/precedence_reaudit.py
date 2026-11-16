#!/usr/bin/env python3
"""Re-audit natural two-machine models with independent structure and solution semantics."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.dvsa_model import solve_model
from ora_agent.flow_shop import audit_candidate, binding_for

IDS = ("BWOR-024", "BWOR-025")
PROTOCOL = ROOT / "docs/paper/precedence_witness_protocol_v0.1.md"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict:
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(path)}


def binding_manifest(binding: dict) -> dict:
    positions = binding["positions"]
    return {
        "kind": binding["kind"], "index_semantics": binding["index_semantics"],
        "jobs": binding["jobs"], "positions": positions,
        "durations": binding["durations"], "data_paths": binding["data_paths"],
        "completion_variables": {str(position): binding["ca"](position) for position in positions},
        "second_completion_variables": {str(position): binding["cb"](position) for position in positions},
        "assignment_variables": {f"{position}:{job}": binding["x"](position, job)
                                 for position in positions for job in binding["jobs"]},
        "makespan": binding["makespan"], "source": binding["source"],
    }


def reaudit_problem(problem_id: str, outdir: Path) -> dict:
    reference_dir = ROOT / "work/dvsa/bwor_reference/frozen" / problem_id
    initial_dir = ROOT / "work/bwor_candidate_blind_replay_v0.1" / problem_id / "initial"
    model_path = reference_dir / "model.json"
    question = (reference_dir / "question.txt").read_text()
    reference = json.loads(model_path.read_text())
    reference["source_sha256"] = sha(model_path)
    binding = binding_for(reference, question)
    candidate_path = initial_dir / "candidate.json"
    candidate = json.loads(candidate_path.read_text())
    reference_solution = json.loads((reference_dir / "solution.json").read_text())
    reference_audit = audit_candidate(reference, reference_solution, binding)
    replay = solve_model(candidate, time_limit=60.0)
    if replay["status"] != "optimal":
        raise ValueError(f"natural candidate did not solve: {problem_id}: {replay}")
    solution = replay["solution"]
    audit = audit_candidate(candidate, solution, binding)
    source_result = json.loads((initial_dir / "result.json").read_text())
    case_dir = outdir / problem_id
    case_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (("candidate.json", candidate), ("solution.json", solution),
                        ("binding.json", binding_manifest(binding)), ("audit.json", audit),
                        ("reference_audit.json", reference_audit), ("execution.json", replay)):
        (case_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n")
    correct = audit["business_correct"]
    return {
        "id": problem_id, "reference_clean": reference_audit["business_correct"],
        "independent_business_correct": correct,
        "status": audit["status"], "formulation": audit["structure"].get("formulation"),
        "index_semantics": audit.get("index_semantics"),
        "independent_optimum": (audit.get("solution") or {}).get("independent_optimum"),
        "legacy_reference_score": source_result.get("score"),
        "repair_action": "not_required" if correct else "repair_required_but_not_run",
        "accepted": correct, "accepted_but_business_incorrect": False if correct else None,
        "harmed_win": False, "new_llm_calls": 0,
        "solver_runs_this_reaudit": 1,
        "artifacts": str(case_dir),
        "inputs": {
            "reference_model": record(model_path),
            "reference_solution": record(reference_dir / "solution.json"),
            "candidate": record(candidate_path), "candidate_solution": record(initial_dir / "solution.json"),
            "question": record(reference_dir / "question.txt"),
            "old_result": record(initial_dir / "result.json"),
        },
    }


def run(outdir: Path) -> dict:
    results = [reaudit_problem(problem_id, outdir) for problem_id in IDS]
    analysis = {
        "run_config": {
            "schema_version": "precedence.natural_reaudit.v0.1", "ids": list(IDS),
            "exposure": "historical_development_not_frozen",
            "protocol_sha256": sha(PROTOCOL),
            "implementation_sha256": {
                name: sha(ROOT / name) for name in (
                    "ora_agent/flow_shop.py", "ora_agent/dvsa_model.py",
                    "ora_agent/dvsa_linear.py", "scripts/precedence_reaudit.py")},
            "new_llm_calls": 0,
        },
        "summary": {
            "n": len(results),
            "reference_clean": sum(row["reference_clean"] for row in results),
            "legacy_reference_correct": sum((row["legacy_reference_score"] or {}).get("business_correct", False)
                                             for row in results),
            "independent_business_correct": sum(row["independent_business_correct"] for row in results),
            "valid_alternative_formulations": sum(row["repair_action"] == "not_required" for row in results),
            "repair_required": sum(row["repair_action"] != "not_required" for row in results),
            "harmed_win": sum(row["harmed_win"] for row in results),
            "accepted_but_business_incorrect": sum(row["accepted_but_business_incorrect"] is True for row in results),
            "new_llm_calls": 0,
            "solver_runs_this_reaudit": sum(row["solver_runs_this_reaudit"] for row in results),
        },
        "results": results,
        "limitations": [
            "These two tasks were used for development and are not candidate-blind or new frozen evaluation.",
            "The old reference-only score and new formulation-aware independent score answer different semantic questions.",
            "Valid alternative formulations must not be repaired merely to resemble the reference model.",
            "No natural repair opportunity was found in these two tasks; no DAG benefit is claimed.",
        ],
    }
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=1) + "\n")
    return analysis


def main() -> None:
    analysis = run(ROOT / "work/precedence_witness_v0.1")
    print(json.dumps(analysis["summary"], ensure_ascii=False, indent=1))
    if analysis["summary"]["independent_business_correct"] != len(IDS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

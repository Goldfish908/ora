#!/usr/bin/env python3
"""Evaluate the registered new Qwen initials with the existing scoped repair kernel."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.dvsa_repair import score_solution
from scripts.bwor_scoped_loop import (
    POLICIES,
    digest,
    file_digest,
    file_record,
    prepare_case,
    run_problem,
    summarize,
    write_json,
)
from scripts.dvsa_bwor_reference import load_rows
from scripts.dvsa_reference_select import select_reference
from scripts.frozen_qwen_candidates import IDS, OUT

PROTOCOL = ROOT / "docs/paper/frozen_scoped_milestone_protocol_v0.1.md"


def load_case(problem_id: str, answers: dict, initial_root: Path | None = None) -> dict:
    reference = select_reference("frozen", problem_id)
    directory = (initial_root or OUT) / problem_id / "initial"
    result = json.loads((directory / "result.json").read_text())
    candidate_path = directory / "candidate.json"
    solution_path = directory / "solution.json"
    candidate = json.loads(candidate_path.read_text()) if candidate_path.exists() else None
    solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
    initial_score = result["score"]
    reference_score = score_solution(reference, reference["solution"], answers[problem_id])
    if not reference_score["business_correct"]:
        raise ValueError(f"independent reference failed its own score: {problem_id}")
    provenance = {
        "reference_model": file_record(reference["model_path"]),
        "reference_solution": file_record(reference["solution_path"]),
        "question": file_record(reference["question_path"]),
        "initial_result": file_record(directory / "result.json"),
        "generator": result["generator"],
    }
    return {
        "id": problem_id, "split": "frozen", "family": "bwor_frozen_new_qwen_initial",
        "eligible": True, "question": reference["question"],
        "reference": {"model": reference["model"], "solution": reference["solution"]},
        "reference_text": reference["model_path"].read_text(),
        "reference_score": reference_score,
        "initial": {"model": candidate, "solution": solution,
                    "solve": result.get("solve") or {"status": "no_solution"}},
        "initial_score": initial_score, "provenance": provenance,
        "initial_generation_status": result["status"],
        "natural_objective_error": not initial_score["business_correct"],
    }


def main() -> None:
    generation_manifest_path = OUT / "generation_manifest.json"
    if not generation_manifest_path.exists():
        raise FileNotFoundError("one-shot generation has not completed")
    generation_manifest = json.loads(generation_manifest_path.read_text())
    if {row["id"] for row in generation_manifest["results"]} != set(IDS):
        raise ValueError("generation does not cover all registered tasks")
    answers = {row["id"]: float(row["answer"]) for row in load_rows("frozen")}
    cases = [load_case(problem_id, answers) for problem_id in IDS]
    config = {
        "schema_version": "frozen.scoped_milestone.v0.1", "ids": list(IDS),
        "policies": list(POLICIES), "max_repairs": 2,
        "generation_manifest_sha256": file_digest(generation_manifest_path),
        "protocol_sha256": file_digest(PROTOCOL),
        "implementation_sha256": file_digest(Path(__file__)),
        "online_ranking": {"status": "not_run", "reason": "one candidate per problem"},
        "claims": ["new_qwen_initial", "first_evaluation_of_current_scoped_controller",
                   "reference_bound_repair", "not_whole_system_first_frozen", "not_sota"],
    }
    analysis_path = OUT / "analysis.json"
    if analysis_path.exists():
        previous = json.loads(analysis_path.read_text())
        if previous["run_config"] != config:
            raise ValueError("existing frozen analysis has a different configuration")
        print(json.dumps(previous["arms"], indent=1))
        return
    results = []
    for case in cases:
        prepared = prepare_case(case)
        for policy in POLICIES:
            result = run_problem(prepared, policy, OUT)
            result["reference_bound_development_recovery"] = bool(
                result["improved"] and result["accepted_round"] not in (None, 0)
                and result["deterministic_transforms"] > 0 and result["gate_accepted"])
            result["initial_generation_status"] = case["initial_generation_status"]
            write_json(OUT / case["id"] / policy / "result.json", result)
            results.append(result)
    negative = [{"id": case["id"], "kind": "initial_generation_or_solve_failure",
                 "status": case["initial_generation_status"]}
                for case in cases if case["initial_generation_status"] != "initial_scored"]
    negative.extend({"id": row["id"], "policy": row["policy"], **row["negative_result"]}
                    for row in results if row["negative_result"] is not None)
    analysis = {
        "run_config": config,
        "denominators": {"tasks": len(cases), "per_arm": len(cases),
                         "initial_errors": sum(not case["initial_score"]["business_correct"]
                                               for case in cases)},
        "arms": {policy: summarize(results, policy) for policy in POLICIES},
        "results": results, "negative_results": negative,
        "generation": generation_manifest,
        "limitations": [
            "Six new Qwen initial candidates; not the whole system's first frozen evaluation.",
            "Reference-bound objective repair, not autonomous NL modeling or memory evolution.",
            "Independent references are blind-authored and answer-checked, not expert gold labels.",
            "One candidate per problem, so online ranking was not run.",
        ],
    }
    write_json(analysis_path, analysis)
    write_json(OUT / "negative_results.json", negative)
    summary = {key: analysis[key] for key in
               ("run_config", "denominators", "arms", "negative_results", "generation", "limitations")}
    write_json(OUT / "summary.json", summary)
    print(json.dumps(analysis["arms"], indent=1))


if __name__ == "__main__":
    main()

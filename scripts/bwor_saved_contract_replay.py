#!/usr/bin/env python3
"""Replay all saved BWOR responses through the current fail-closed candidate contract."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.dvsa_model import (
    extract_json,
    normalize_candidate,
    normalize_candidate_paths,
    solve_model,
    validate_candidate_paths,
    validate_model,
)
from ora_agent.dvsa_repair import schema_errors, score_solution
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
from scripts.frozen_qwen_candidates import IDS
from scripts.frozen_scoped_evaluate import load_case

SOURCE = ROOT / "work/frozen_scoped_milestone_v0.1"
OUT = ROOT / "work/bwor_saved_contract_replay_v0.2"
PROTOCOL = ROOT / "docs/paper/bwor_saved_contract_protocol_v0.2.md"


def process_initial(problem_id: str, answers: dict, outdir: Path,
                    source_root: Path | None = None) -> dict:
    source = (source_root or SOURCE) / problem_id / "initial"
    target = outdir / problem_id / "initial"
    target.mkdir(parents=True, exist_ok=True)
    original = json.loads((source / "result.json").read_text())
    response_path = source / "response.json"
    response = json.loads(response_path.read_text())
    reference = select_reference("frozen", problem_id)
    record = {
        "problem_id": problem_id, "split": "frozen",
        "exposure": "historical_saved_response_replay_not_frozen",
        "generator": original.get("generator") or {"status": "not_recorded_in_legacy_result"},
        "source_result": file_record(source / "result.json"),
        "source_response": file_record(response_path),
        "source_prompt": (file_record(source / "prompt.txt")
                          if (source / "prompt.txt").exists() else None),
        "llm_calls": 0, "new_llm_calls": 0,
        "original_llm_calls": original.get("llm_calls"),
        "old_score": original.get("score"),
        "usage": original.get("usage"),
        "public_answer_hidden_from_original_prompt": True,
        "contract_implementation": "normalize_candidate_paths_and_validate_v0.2",
    }
    candidate = None
    try:
        raw = extract_json(response.get("content"))
        candidate = normalize_candidate(raw)
        if candidate.get("problem_id") != problem_id:
            raise ValueError("problem_id mismatch")
        validate_model(candidate)
        candidate, path_normalizations = normalize_candidate_paths(candidate)
        record["path_normalizations"] = path_normalizations
        validate_candidate_paths(candidate)
        (target / "candidate.json").write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
        record["normalization_applied"] = bool(isinstance(raw.get("variables"), list)
                                               or path_normalizations)
        errors = schema_errors(candidate, reference["model"]["variables"])
        if errors:
            record["status"] = "invalid_shared_schema"
            record["schema_errors"] = errors
            solution = None
        else:
            solved = solve_model(candidate, time_limit=60.0)
            record["solve"] = solved
            solution = solved.get("solution") if solved["status"] == "optimal" else None
            if solution is not None:
                (target / "solution.json").write_text(
                    json.dumps(solution, ensure_ascii=False, indent=2) + "\n")
            record["status"] = "initial_scored" if solution is not None else "solve_failed"
    except (ValueError, TypeError, AttributeError) as exc:
        record["status"] = "contract_invalid"
        record["error"] = str(exc)
        solution = None
    record["score"] = score_solution(reference, solution, answers[problem_id])
    record["contract_recovered"] = bool(original["status"] in {"invalid_candidate", "contract_invalid"}
                                        and record["status"] != "contract_invalid")
    record["old_status"] = original["status"]
    (target / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return record


def run_cohort(source_root: Path, ids: tuple[str, ...], outdir: Path,
               protocol_path: Path, schema_version: str, exposure: str) -> dict:
    answers = {row["id"]: float(row["answer"]) for row in load_rows("frozen")}
    initials = [process_initial(problem_id, answers, outdir, source_root) for problem_id in ids]
    cases = [load_case(problem_id, answers, initial_root=outdir) for problem_id in ids]
    results = []
    for case in cases:
        prepared = prepare_case(case)
        for policy in POLICIES:
            result = run_problem(prepared, policy, outdir)
            result["initial_generation_status"] = case["initial_generation_status"]
            write_json(outdir / case["id"] / policy / "result.json", result)
            results.append(result)
    negative = [{"id": row["problem_id"], "kind": "initial_contract_or_solve_failure",
                 "old_status": row["old_status"], "new_status": row["status"]}
                for row in initials if row["status"] != "initial_scored"]
    negative.extend({"id": row["id"], "policy": row["policy"], **row["negative_result"]}
                    for row in results if row["negative_result"] is not None)
    source_files = {}
    missing_sources = []
    for problem_id in ids:
        for name in ("result.json", "response.json", "prompt.txt"):
            path = source_root / problem_id / "initial" / name
            key = f"{problem_id}/{name}"
            source_files[key] = file_digest(path) if path.exists() else None
            if not path.exists():
                missing_sources.append(key)
    generation_manifest = source_root / "generation_manifest.json"
    analysis = {
        "run_config": {
            "schema_version": schema_version,
            "ids": list(ids), "policies": list(POLICIES), "max_repairs": 2,
            "source_generation_manifest_sha256": (file_digest(generation_manifest)
                                                  if generation_manifest.exists() else None),
            "source_files_sha256": source_files,
            "missing_source_artifacts": missing_sources,
            "protocol_sha256": file_digest(protocol_path),
            "implementation_sha256": {
                name: file_digest(ROOT / name) for name in (
                    "scripts/bwor_saved_contract_replay.py", "ora_agent/dvsa_model.py",
                    "scripts/frozen_scoped_evaluate.py", "scripts/bwor_scoped_loop.py")},
            "exposure": exposure,
            "new_llm_calls": 0,
        },
        "denominators": {
            "tasks": len(initials), "per_arm": len(initials),
            "legacy_business_labels_available": sum(isinstance(row["old_score"], dict) for row in initials),
            "legacy_initial_business_correct": sum(bool(row["old_score"] and row["old_score"].get("business_correct"))
                                                   for row in initials),
            "contract_recovered": sum(row["contract_recovered"] for row in initials),
            "contract_invalid": sum(row["status"] == "contract_invalid" for row in initials),
            "initial_scored": sum(row["status"] == "initial_scored" for row in initials),
            "initial_business_correct": sum(row["score"]["business_correct"] for row in initials),
            "business_recovered_after_normalization": sum(
                isinstance(row["old_score"], dict) and not row["old_score"].get("business_correct")
                and row["score"]["business_correct"] for row in initials),
            "initial_solver_runs_this_replay": sum((row.get("solve") or {}).get("solver_calls", 0)
                                                   for row in initials),
        },
        "initials": initials,
        "arms": {policy: summarize(results, policy) for policy in POLICIES},
        "results": results, "negative_results": negative,
        "cost": {
            "new_llm_calls": 0,
            "initial_solver_runs_this_replay": sum((row.get("solve") or {}).get("solver_calls", 0)
                                                   for row in initials),
            "repair_solver_runs_this_replay": sum(row["solver_runs_this_run"] for row in results),
        },
        "limitations": [
            "The saved responses are historical inputs, not newly generated candidates or a whole-system frozen test.",
            "Contract recovery is not a new natural generation, semantic repair, or controller improvement.",
            "Reference models are blind-authored and answer-checked, not expert gold labels.",
            "Reference-bound objective replacement is not autonomous modeling or memory evolution.",
        ],
    }
    write_json(outdir / "analysis.json", analysis)
    write_json(outdir / "negative_results.json", negative)
    print(json.dumps({"denominators": analysis["denominators"], "arms": analysis["arms"]}, indent=1))
    if any(analysis["arms"][policy]["harmed_win"]
           or analysis["arms"][policy]["accepted_but_reference_incorrect"]
           for policy in POLICIES):
        raise SystemExit(1)
    return analysis


def main() -> None:
    run_cohort(SOURCE, IDS, OUT, PROTOCOL, "bwor.saved_response.contract_replay.v0.2",
               "historical_saved_response_replay_not_frozen")


if __name__ == "__main__":
    main()

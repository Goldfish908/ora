#!/usr/bin/env python3
"""Evaluate saved repair responses under empty-data format normalization."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.dvsa_model import (extract_json, normalize_model, solve_model,  # noqa: E402
                                  validate_model)
from ora_agent.dvsa_repair import schema_errors, score_solution  # noqa: E402
from scripts.dvsa_bwor_reference import load_rows  # noqa: E402
from scripts.dvsa_reference_select import select_reference  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "validation"], default="dev")
    parser.add_argument("--ids", nargs="+", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    source = Path(args.run_dir)
    out = Path(args.out)
    if not source.is_absolute():
        source = ROOT / source
    if not out.is_absolute():
        out = ROOT / out
    shutil.copytree(source, out, dirs_exist_ok=True)
    answers = {row["id"]: float(row["answer"]) for row in load_rows(args.split)}
    for problem_id in args.ids:
        reference = select_reference(args.split, problem_id)
        for arm in ("no_memory", "text_memory", "dvsa"):
            target = out / problem_id / arm
            result = json.loads((target / "result.json").read_text())
            result["strict_original_status"] = result["status"]
            result["evaluation_status"] = "unchanged_existing_result"
            result["incremental_llm_calls"] = 0
            if result["status"] == "invalid_repair" and (target / "response.json").exists():
                candidate = extract_json(json.loads((target / "response.json").read_text())["content"])
                candidate, normalizations = normalize_model(candidate)
                validate_model(candidate)
                errors = schema_errors(candidate, reference["model"]["variables"])
                result["normalizations"] = normalizations
                (target / "candidate.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
                if not errors:
                    solved = solve_model(candidate)
                    result["solve"] = solved
                    if solved["status"] == "optimal":
                        (target / "solution.json").write_text(json.dumps(solved["solution"], indent=2) + "\n")
                        result["status"] = "repair_scored"
                    else:
                        result["status"] = "repair_solve_failed"
                else:
                    result["status"] = "invalid_shared_schema"
                    result["schema_errors"] = errors
                result["evaluation_status"] = "format_sensitivity_reuse_existing_response"
            solution_path = target / "solution.json"
            solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
            result["final_score"] = score_solution(reference, solution, answers[problem_id])
            result["improved"] = (not result["initial_score"]["business_correct"]
                                   and result["final_score"]["business_correct"])
            result["harmed_win"] = (result["initial_score"]["business_correct"]
                                     and not result["final_score"]["business_correct"])
            (target / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(f"{problem_id}/{arm}: {result['strict_original_status']} -> {result['status']} "
                  f"business={result['final_score']['business_correct']}")
        text_result = json.loads((out / problem_id / "text_memory/result.json").read_text())
        legacy = {**text_result, "arm": "direct_legacy_witness", "llm_calls": 0,
                  "equivalent_generation_llm_calls": text_result["llm_calls"],
                  "reused_from": "text_memory",
                  "legacy_witness": {"status": "UNKNOWN", "reason": "unknown_schema_retailopt"}}
        for name in ("candidate.json", "solution.json"):
            source_file = out / problem_id / "text_memory" / name
            if source_file.exists():
                shutil.copyfile(source_file, out / problem_id / "direct_legacy_witness" / name)
        (out / problem_id / "direct_legacy_witness/result.json").write_text(
            json.dumps(legacy, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()

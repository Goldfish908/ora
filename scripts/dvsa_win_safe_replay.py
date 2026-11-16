#!/usr/bin/env python3
"""Replay saved RetailOpt candidates with win-safe selection and no model calls."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dvsa_retail_core import business_score, select_win_safe_solution

ARMS = ("no_memory", "text_memory", "dvsa", "direct_legacy_witness")
DEFAULT_BASELINE = ROOT / "work/mem_evo/replay_gen1/m1_pilot_schema_sol_gen1.jsonl"
DEFAULT_SANDBOX = ROOT / "work/mem_evo/replay_gen1/sandbox"


def run_replay(split: str, outdir: Path, ids: list[str] | None = None,
               baseline_path: Path | None = None, sandbox_root: Path | None = None) -> dict:
    baseline_path = baseline_path or DEFAULT_BASELINE
    sandbox_root = sandbox_root or DEFAULT_SANDBOX
    source = ROOT / "work/dvsa/retailopt_repair" / split
    rows = [json.loads(line) for line in baseline_path.read_text().splitlines() if line.strip()]
    rows.sort(key=lambda row: row["scenario_id"])
    if ids:
        selected = set(ids)
        rows = [row for row in rows if row["scenario_id"] in selected]
    if not rows:
        raise ValueError("no replay scenarios")
    outdir.mkdir(parents=True, exist_ok=True)
    results = []
    for row in rows:
        scenario = row["scenario_id"]
        reference_objective = float(row["reference_objective"])
        initial_dir = sandbox_root / f"schema_sol__{scenario}__on"
        data = json.loads((initial_dir / "data.json").read_text())
        initial_solution_path = initial_dir / "solution.json"
        initial_solution = (json.loads(initial_solution_path.read_text())
                            if initial_solution_path.exists() else None)
        initial_score = business_score(data, reference_objective, initial_solution)
        for arm in ARMS:
            arm_dir = source / scenario / arm
            result_path = arm_dir / "result.json"
            if not result_path.exists():
                continue
            original = json.loads(result_path.read_text())
            recovery_path = arm_dir / "execution_recovery" / "result.json"
            recovery = json.loads(recovery_path.read_text()) if recovery_path.exists() else None
            candidate_path = (arm_dir / "execution_recovery" / "solution.json"
                              if recovery is not None else arm_dir / "solution.json")
            candidate = json.loads(candidate_path.read_text()) if candidate_path.exists() else None
            original_score = ((recovery or original).get("final_score") or business_score(
                data, reference_objective, candidate))
            selection = select_win_safe_solution(
                data, reference_objective, initial_solution, initial_score, candidate)
            safe_score = selection["score"]
            accepted = bool(safe_score["business_correct"])
            result = {
                "id": scenario, "arm": arm,
                "initial_score": initial_score,
                "original_final_score": original_score,
                "candidate_final_score": selection["candidate_score"],
                "safe_final_score": safe_score,
                "accepted": accepted,
                "acceptance_evidence": "legacy_business_score_after_win_safe_selection",
                "accepted_but_business_incorrect": accepted and not safe_score["business_correct"],
                "original_harmed_win": (initial_score["business_correct"]
                                        and not original_score["business_correct"]),
                "safe_harmed_win": initial_score["business_correct"] and not safe_score["business_correct"],
                "baseline_fallback": selection["baseline_fallback"],
                "llm_calls_this_replay": 0,
                "source_llm_calls": original.get("llm_calls", 0) + (recovery or {}).get("llm_calls", 0),
                "execution_recovery_used": recovery is not None,
                "original_status": original.get("status"),
            }
            target = outdir / scenario / arm
            target.mkdir(parents=True, exist_ok=True)
            if selection["baseline_fallback"] and initial_solution is not None:
                (target / "solution.json").write_text(
                    json.dumps(initial_solution, ensure_ascii=False, indent=2) + "\n")
            elif candidate is not None:
                (target / "solution.json").write_text(
                    json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
            result["solution_file"] = str(target / "solution.json") if (target / "solution.json").exists() else None
            (target / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
            results.append(result)
    summary = {}
    for arm in ARMS:
        rows = [row for row in results if row["arm"] == arm]
        summary[arm] = {
            "n": len(rows),
            "initial_business_correct": sum(row["initial_score"]["business_correct"] for row in rows),
            "original_final_business_correct": sum(row["original_final_score"]["business_correct"] for row in rows),
            "safe_final_business_correct": sum(row["safe_final_score"]["business_correct"] for row in rows),
            "original_harmed_win": sum(row["original_harmed_win"] for row in rows),
            "safe_harmed_win": sum(row["safe_harmed_win"] for row in rows),
            "accepted": sum(row["accepted"] for row in rows),
            "accepted_but_business_incorrect": sum(row["accepted_but_business_incorrect"] for row in rows),
            "baseline_fallback": sum(row["baseline_fallback"] for row in rows),
            "source_llm_calls": sum(row["source_llm_calls"] for row in rows),
            "replay_llm_calls": 0,
        }
    analysis = {"protocol": "retailopt_win_safe_candidate_selection_v0.1", "split": split,
                "source": str(source.relative_to(ROOT)),
                "baseline": str(baseline_path.relative_to(ROOT)),
                "sandbox_root": str(sandbox_root.relative_to(ROOT)),
                "independent_scorer": "the same legacy witness and reference objective as the source replay",
                "new_llm_calls": 0, "summary": summary, "results": results}
    (outdir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=1) + "\n")
    (outdir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "validation", "frozen"], default="dev")
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--out")
    parser.add_argument("--baseline")
    parser.add_argument("--sandbox-root")
    args = parser.parse_args()
    outdir = Path(args.out) if args.out else ROOT / "work/dvsa/retailopt_win_safe_v0.1"
    baseline = Path(args.baseline) if args.baseline else DEFAULT_BASELINE
    sandbox = Path(args.sandbox_root) if args.sandbox_root else DEFAULT_SANDBOX
    analysis = run_replay(args.split, outdir, args.ids, baseline, sandbox)
    print(json.dumps(analysis["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""One shared execution-only recovery stage after RetailOpt feedback repair."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from scripts.dvsa_retail_core import business_score  # noqa: E402
from scripts.dvsa_retail_repair import render_prompt, run_repair_code  # noqa: E402


def needs_recovery(result):
    return (result["final_score"]["status"] == "no_solution"
            and result.get("solver_calls", 0) > 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="work/mem_evo/replay_gen1/m1_pilot_schema_sol_gen1.jsonl")
    parser.add_argument("--run-dir", default="work/dvsa/retailopt_repair/dev")
    parser.add_argument("--sandbox-root", default="work/mem_evo/replay_gen1/sandbox")
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--shard", nargs=2, type=int, metavar=("INDEX", "COUNT"))
    parser.add_argument("--arms", nargs="+", default=["no_memory", "text_memory", "dvsa", "direct_legacy_witness"])
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    baseline = Path(args.baseline)
    run_dir = Path(args.run_dir)
    sandbox_root = Path(args.sandbox_root)
    if not baseline.is_absolute():
        baseline = ROOT / baseline
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    if not sandbox_root.is_absolute():
        sandbox_root = ROOT / sandbox_root
    rows = [json.loads(line) for line in baseline.read_text().splitlines() if line.strip()]
    rows.sort(key=lambda row: row["scenario_id"])
    if args.ids:
        selected = set(args.ids)
        rows = [row for row in rows if row["scenario_id"] in selected]
    if args.shard:
        index, count = args.shard
        if not 0 <= index < count:
            raise ValueError("shard requires 0 <= index < count")
        rows = rows[index::count]
    config = llm_mod.load_config()
    for row in rows:
        scenario = row["scenario_id"]
        problem = (ROOT / "work/dvsa/retailopt_repair/problems" / f"{scenario}.txt").read_text()
        initial_dir = sandbox_root / f"schema_sol__{scenario}__on"
        data = json.loads((initial_dir / "data.json").read_text())
        for arm in args.arms:
            parent_dir = run_dir / scenario / arm
            parent_path = parent_dir / "result.json"
            parent = json.loads(parent_path.read_text())
            target = parent_dir / "execution_recovery"
            result_path = target / "result.json"
            if args.resume and result_path.exists():
                print(f"{scenario}/{arm}: recovery_resume_skip", flush=True)
                continue
            if not needs_recovery(parent):
                print(f"{scenario}/{arm}: no_execution_recovery_needed", flush=True)
                continue
            target.mkdir(parents=True, exist_ok=True)
            code = (parent_dir / "gen.py").read_text()
            execution = json.dumps(parent.get("run", {"status": parent["status"]}), ensure_ascii=False)
            feedback = {"status": "EXECUTION_RECOVERY",
                        "detail": "Fix only execution, solver API and output-contract failures. Preserve the business equations. This is not a semantic-witness repair event."}
            prompt = render_prompt(problem, code, execution, "",
                                   json.dumps(feedback, ensure_ascii=False, indent=2))
            (target / "prompt.txt").write_text(prompt)
            response = llm_mod.chat([{"role": "user", "content": prompt}],
                                    max_tokens=32768, temperature=0.0,
                                    extra={"reasoning_effort": "medium"}, config=config)
            (target / "response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
            run = run_repair_code(response.get("content") or "", target, data, args.timeout)
            score = business_score(data, row["reference_objective"], run["solution"])
            result = {"scenario_id": scenario, "arm": arm,
                      "repair_trigger": "execution_recovery_after_feedback",
                      "parent_result_sha256": hashlib.sha256(parent_path.read_bytes()).hexdigest(),
                      "initial_score": parent["initial_score"],
                      "llm_calls": 1, "solver_calls": 1,
                      "usage": response.get("usage"), "llm_latency_s": response.get("latency_s"),
                      "run": {key: value for key, value in run.items() if key != "solution"},
                      "final_score": score,
                      "improved": not parent["initial_score"]["business_correct"] and score["business_correct"],
                      "harmed_win": parent["initial_score"]["business_correct"] and not score["business_correct"],
                      "reference_objective_used_for_feedback": False}
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(f"{scenario}/{arm}/execution: business={score['business_correct']} "
                  f"improved={result['improved']} harmed={result['harmed_win']}", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Shared-initial RetailOpt repair with text, DVSA and legacy witness feedback."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from scripts.dvsa_retail_core import (business_score, legacy_feedback,  # noqa: E402
                                      load_assets, semantic_feedback, select_win_safe_solution)
from scripts.m1_pilot import EXEC_PYTHON, SCHEMA_PRELUDE, extract_code  # noqa: E402

PROMPT = """Review and, only when needed, repair the shared initial PySCIPOpt optimization model.
You have NOT seen the reference objective, an independent reference solution, or another arm's feedback.
Preserve the business requirements and the existing solution.json schema. Use only the problem, current code, execution feedback and supplied semantic feedback.
If there is no concrete error, return the current code unchanged. Do not make arbitrary changes to an already reasonable model.

[BUSINESS PROBLEM]
{problem}

[CURRENT CODE]
{code}

[EXECUTION]
{execution}

[TEXT MEMORY]
{memory}

[SEMANTIC FEEDBACK]
{feedback}

[OUTPUT CONTRACT]
- Return ONLY complete executable Python code, without markdown fences.
- Use PySCIPOpt with open-source SCIP; read data.json and keep a solver time limit of at most 120 seconds.
- Print status and objective as before.
- On optimal status, write solution.json with objective and sparse tables Q, sales, I, W, lost, sub and X using the original pipe-separated keys. Include empty tables rather than omitting them.
- Do not print or use a reference objective to decide correctness.
"""


def render_prompt(problem, code, execution, memory, feedback):
    return PROMPT.replace("{problem}", problem).replace("{code}", code).replace(
        "{execution}", execution).replace("{memory}", memory).replace("{feedback}", feedback)


def run_repair_code(text, sandbox, data, timeout):
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "data.json").write_text(json.dumps(data))
    code = SCHEMA_PRELUDE + extract_code(text)
    (sandbox / "gen.py").write_text(code)
    started = time.monotonic()
    try:
        process = subprocess.run([EXEC_PYTHON, "gen.py"], cwd=sandbox,
                                 capture_output=True, text=True, timeout=timeout)
        stdout, stderr, return_code = process.stdout, process.stderr, process.returncode
        exec_status = "ok" if return_code == 0 else "crash"
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.stdout or "", exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        return_code, exec_status = None, "timeout"
    status = re.search(r"^status:\s*(\S+)", stdout, re.MULTILINE)
    objective = re.search(r"^objective:\s*([-+0-9.eE]+)", stdout, re.MULTILINE)
    solution_path = sandbox / "solution.json"
    solution, solution_error = None, None
    if solution_path.exists():
        try:
            solution = json.loads(solution_path.read_text())
        except (ValueError, TypeError) as exc:
            solution_error = str(exc)
    return {"exec_status": exec_status, "return_code": return_code,
            "solver_status": status.group(1) if status else None,
            "objective": float(objective.group(1)) if objective else None,
            "stderr_tail": stderr[-500:], "wall_s": round(time.monotonic() - started, 3),
            "solution": solution, "solution_error": solution_error}


def trigger(arm, feedback, has_solution):
    if arm in {"no_memory", "text_memory"}:
        return "scheduled_self_review"
    if feedback["status"] == "VIOLATED":
        return "dvsa_violation" if arm == "dvsa" else "legacy_witness_violation"
    if not has_solution:
        return "execution_failure_unknown_semantics"
    return "no_call"


def compact(feedback):
    result = dict(feedback)
    violations = []
    for item in feedback.get("violations", []):
        if "violations" in item:
            violations.append({**item, "violations": item["violations"][:8],
                               "truncated_to": 8})
        else:
            violations.append(item)
    result["violations"] = violations[:20]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="work/mem_evo/replay_gen1/m1_pilot_schema_sol_gen1.jsonl")
    parser.add_argument("--sandbox-root", default="work/mem_evo/replay_gen1/sandbox")
    parser.add_argument("--run-dir", default="work/dvsa/retailopt_repair/dev")
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--shard", nargs=2, type=int, metavar=("INDEX", "COUNT"))
    parser.add_argument("--arms", nargs="+", choices=["no_memory", "text_memory", "dvsa", "direct_legacy_witness"],
                        default=["no_memory", "text_memory", "dvsa", "direct_legacy_witness"])
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    baseline = Path(args.baseline)
    sandbox_root = Path(args.sandbox_root)
    run_dir = Path(args.run_dir)
    for path in (baseline, sandbox_root, run_dir):
        if not path.is_absolute():
            path = ROOT / path
    if not baseline.is_absolute():
        baseline = ROOT / baseline
    if not sandbox_root.is_absolute():
        sandbox_root = ROOT / sandbox_root
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
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
    assets, asset_hashes = load_assets()
    memory = "\n\n".join(asset["text"] for asset in assets)
    config = llm_mod.load_config()
    for row in rows:
        scenario = row["scenario_id"]
        initial_dir = sandbox_root / f"schema_sol__{scenario}__on"
        data = json.loads((initial_dir / "data.json").read_text())
        code = (initial_dir / "gen.py").read_text()
        solution_path = initial_dir / "solution.json"
        initial_solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
        initial_score = business_score(data, row["reference_objective"], initial_solution)
        problem_path = ROOT / "work/dvsa/retailopt_repair/problems" / f"{scenario}.txt"
        problem_path.parent.mkdir(parents=True, exist_ok=True)
        problem = next(json.loads(line)["prompt_schema"] for line in
                       (ROOT / "work/mem_evo/dev40_rows.jsonl").read_text().splitlines()
                       if json.loads(line)["scenario_id"] == scenario)
        if "reference_objective" in problem:
            raise ValueError("reference objective leaked into repair problem")
        problem_path.write_text(problem)
        execution = json.dumps({key: row.get(key) for key in
                                ("exec_status", "return_code", "solver_status", "objective",
                                 "stderr_tail", "wall_s")}, ensure_ascii=False)
        initial_hash = hashlib.sha256(code.encode()).hexdigest()
        for arm in args.arms:
            target = run_dir / scenario / arm
            target.mkdir(parents=True, exist_ok=True)
            result_path = target / "result.json"
            if args.resume and result_path.exists():
                print(f"{scenario}/{arm}: resume_skip", flush=True)
                continue
            if arm == "dvsa":
                feedback, _ = semantic_feedback(assets, data, initial_solution)
            elif arm == "direct_legacy_witness":
                feedback = legacy_feedback(data, initial_solution)
            else:
                feedback = {"status": "not_provided"}
            repair_trigger = trigger(arm, feedback, initial_solution is not None)
            record = {"scenario_id": scenario, "arm": arm,
                      "initial_code_sha256": initial_hash,
                      "initial_score": initial_score, "repair_trigger": repair_trigger,
                      "feedback": feedback, "asset_hashes": asset_hashes,
                      "llm_calls": 0, "solver_calls": 0,
                      "reference_objective_used_for_feedback": False}
            started = time.monotonic()
            if repair_trigger != "no_call":
                prompt = render_prompt(problem, code, execution,
                                       memory if arm in {"text_memory", "dvsa", "direct_legacy_witness"} else "",
                                       json.dumps(compact(feedback), ensure_ascii=False, indent=2))
                (target / "prompt.txt").write_text(prompt)
                response = llm_mod.chat([{"role": "user", "content": prompt}],
                                        max_tokens=32768, temperature=0.0,
                                        extra={"reasoning_effort": "medium"}, config=config)
                (target / "response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
                record.update(llm_calls=1, usage=response.get("usage"),
                              llm_latency_s=response.get("latency_s"))
                repair_code = response.get("content") or ""
            else:
                record["status"] = "accepted_without_repair_call"
            if repair_trigger != "no_call":
                run = run_repair_code(repair_code, target, data, args.timeout)
                record["run"] = {k: v for k, v in run.items() if k != "solution"}
                record["solver_calls"] = 1
                final_solution = run["solution"]
                record["status"] = "repair_executed"
            else:
                final_solution = initial_solution
                shutil.copyfile(initial_dir / "gen.py", target / "gen.py")
                if initial_solution is not None:
                    shutil.copyfile(solution_path, target / "solution.json")
            selection = select_win_safe_solution(data, row["reference_objective"],
                                                 initial_solution, initial_score, final_solution)
            final_solution = selection["solution"]
            if selection["baseline_fallback"] and initial_solution is not None:
                shutil.copyfile(solution_path, target / "solution.json")
            record["final_score"] = selection["score"]
            record["candidate_final_score"] = selection["candidate_score"]
            record["baseline_fallback"] = selection["baseline_fallback"]
            record["improved"] = not initial_score["business_correct"] and record["final_score"]["business_correct"]
            record["harmed_win"] = initial_score["business_correct"] and not record["final_score"]["business_correct"]
            record["wall_s"] = round(time.monotonic() - started, 3)
            result_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
            print(f"{scenario}/{arm}: {repair_trigger} calls={record['llm_calls']} "
                  f"business={record['final_score']['business_correct']} "
                  f"improved={record['improved']} harmed={record['harmed_win']}", flush=True)


if __name__ == "__main__":
    main()

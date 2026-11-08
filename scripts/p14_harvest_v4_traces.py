#!/usr/bin/env python3
"""P14: harvest FULL active-judge trajectories on F1-F4 factory cells (judge_v2).

Purpose: rejection-sampling seeds for judge v4 distillation. Unlike p10 (which
kept only tails for metrics), this saves the complete planner/decider
responses so correct trajectories can become SFT targets.

Hygiene: trains ONLY on F1-F4 factory cells (work/judge_data/judge_v2.jsonl,
the v3 training distribution). F5-F8 and IndustryOR stay untouched eval sets.

Per record:
  context  = JUDGE_PROMPT.format(...) (same as v3 sampling-time prompt)
  stage 1  = p10 v4 PLANNER_PROMPT -> check script
  stage 2  = sandbox execution (one repair round on crash)  [deterministic]
  stage 3  = p10 v4 DECIDER_TEMPLATE -> full reasoning + VERDICT

Artifacts are re-resolved from runs/p1_factory/sandbox (same logic as p4):
  inject      -> inject_a*/solution.json (objective-matched)
  repair_pass -> repair_r*/solution.json (objective-matched)

Usage: same ORA_LLM_* env as p10.  --limit N for smoke.
Output: work/judge_data/harvest_v4.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.p10_active_judge import (  # noqa: E402
    DECIDER_TEMPLATE, PLANNER_PROMPT, REPAIR_TEMPLATE, call, extract_code,
    run_check)
from scripts.p5_judge_rs import JUDGE_PROMPT, parse_verdict  # noqa: E402

FACTORY = ROOT / "runs" / "p1_factory"
JUDGE_DATA = ROOT / "work" / "judge_data" / "judge_v2.jsonl"
SCENARIOS = ROOT / "data" / "m1_retailopt" / "f1f4_all100.jsonl"


def find_inject_solution(sb_root: Path, objective):
    for d in sorted(sb_root.glob("inject_a*")):
        sp = d / "solution.json"
        if not sp.exists():
            continue
        try:
            sol = json.loads(sp.read_text())
        except Exception:
            continue
        if objective is not None and sol.get("objective") is not None and \
                abs(sol["objective"] - objective) <= 1e-6 * max(1, abs(objective)):
            return sol
        return sol
    return None


def find_repair_solution(sb_root: Path, objective):
    for d in sorted(sb_root.glob("repair_r*")):
        sp = d / "solution.json"
        if not sp.exists():
            continue
        try:
            sol = json.loads(sp.read_text())
        except Exception:
            continue
        if objective is None or sol.get("objective") is None:
            return sol
        if abs(sol["objective"] - objective) <= 1e-4 * max(1, abs(objective)):
            return sol
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "work" / "judge_data" / "harvest_v4.jsonl"))
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--max-tokens", type=int, default=12288)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    scen = {}
    for line in SCENARIOS.read_text().splitlines():
        r = json.loads(line)
        d = r.get("data")
        scen[r["scenario_id"]] = {
            "prompt_full": r.get("prompt_full") or "",
            "data": json.loads(d) if isinstance(d, str) else d,
        }

    records = [json.loads(l) for l in JUDGE_DATA.read_text().splitlines()]
    out_path = Path(args.out)
    done = set()
    if out_path.exists():
        done = {json.loads(l)["key"] for l in out_path.read_text().splitlines()
                if not json.loads(l).get("error")}

    base_url = os.environ["ORA_LLM_BASE_URL"]
    api_key = os.environ["ORA_LLM_API_KEY"]
    model = os.environ.get("ORA_LLM_MODEL", "Qwen3_8-27B")
    insecure = os.environ.get("ORA_LLM_INSECURE") == "1"

    def one(rec):
        sid = rec["scenario_id"]
        key = f"{sid}|{rec.get('mutant')}|{rec.get('seed_tag')}|{rec['label']}"
        if key in done:
            return None
        s = scen.get(sid)
        sb_root = FACTORY / "sandbox" / f"{sid}__{rec['mutant']}{rec.get('seed_tag') or ''}"
        if s is None:
            return {"key": key, "wrong": rec["label"] == "wrong",
                    "verdict": None, "error": "missing_scenario"}
        if rec["source"] == "inject":
            sol = find_inject_solution(sb_root, rec.get("objective"))
        else:
            sol = find_repair_solution(sb_root, rec.get("objective"))
        if sol is None:
            return {"key": key, "wrong": rec["label"] == "wrong",
                    "verdict": None, "error": "missing_solution"}
        user = JUDGE_PROMPT.format(
            prompt=s["prompt_full"][:4000],
            data_digest=json.dumps(rec["data_digest"], ensure_ascii=False),
            code=rec["code"][:4000],
            solution_digest=json.dumps(rec["solution_digest"], ensure_ascii=False))
        def _shape(x, depth=0):
            if isinstance(x, dict):
                if not x or depth >= 3:
                    return "dict"
                k0 = next(iter(x))
                return "{<%s>: %s}" % (k0, _shape(x[k0], depth + 1))
            if isinstance(x, list):
                return "list[%d] of %s" % (len(x), _shape(x[0], depth + 1) if x else "?")
            return type(x).__name__
        dkeys = "; ".join(f"{k}: {_shape(v)}" for k, v in s["data"].items())
        # stage 1: plan checks
        planner_user = PLANNER_PROMPT.format(context=user, schema=dkeys)
        r1 = call(planner_user,
                  model=model, base_url=base_url, api_key=api_key,
                  insecure=insecure, max_tokens=args.max_tokens, thinking=False)
        script0 = extract_code(r1["content"])
        if not script0:
            return {"key": key, "wrong": rec["label"] == "wrong", "verdict": None,
                    "error": "no_script", "user": user,
                    "planner_full": r1["content"]}
        # stage 2: deterministic execution (one repair round on crash)
        script, repaired = script0, False
        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            (wd / "solution.json").write_text(json.dumps(sol, ensure_ascii=False))
            (wd / "data.json").write_text(json.dumps(s["data"], ensure_ascii=False))
            output = run_check(script, wd)
            if "[stderr]" in output or "[EXEC ERROR]" in output or "[TIMEOUT" in output:
                fix = call(REPAIR_TEMPLATE.format(script=script, output=output),
                           model=model, base_url=base_url, api_key=api_key,
                           insecure=insecure, max_tokens=args.max_tokens, thinking=False)
                fixed = extract_code(fix["content"])
                if fixed:
                    script, repaired = fixed, True
                    output = run_check(script, wd)
        # stage 3: decide
        decider_user = DECIDER_TEMPLATE.format(context=user, script=script,
                                               output=output)
        r2 = call(decider_user, model=model, base_url=base_url, api_key=api_key,
                  insecure=insecure, max_tokens=args.max_tokens, thinking=False)
        return {"key": key, "wrong": rec["label"] == "wrong",
                "split": rec.get("split"), "mutant": rec.get("mutant"),
                "source": rec.get("source"),
                "user": user, "planner_user": planner_user,
                "planner_full": r1["content"], "script_initial": script0,
                "script": script, "repaired": repaired,
                "check_output": output,
                "decider_user": decider_user, "decider_full": r2["content"],
                "verdict": parse_verdict(r2["content"]),
                "finish_reason": r2.get("finish_reason"),
                "latency_s": r1["latency_s"] + r2["latency_s"]}

    todo = records[: args.limit] if args.limit else records
    n, t0 = 0, time.time()
    with out_path.open("a") as out, ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(one, c) for c in todo]
        for fut in as_completed(futs):
            r = fut.result()
            if r is None:
                continue
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            out.flush()
            n += 1
            if n % 16 == 0 or n == len(todo):
                print(f"[{n}/{len(todo)}] {time.time()-t0:.0f}s", flush=True)

    rows = [json.loads(l) for l in out_path.read_text().splitlines()]
    tp = sum(1 for r in rows if r["wrong"] and r.get("verdict") == "INVALID")
    fn = sum(1 for r in rows if r["wrong"] and r.get("verdict") != "INVALID")
    fp = sum(1 for r in rows if not r["wrong"] and r.get("verdict") == "INVALID")
    tn = sum(1 for r in rows if not r["wrong"] and r.get("verdict") != "INVALID")
    print(json.dumps({"n": len(rows), "tp": tp, "fn": fn, "fp": fp, "tn": tn,
                      "detection": round(tp / max(tp + fn, 1), 4),
                      "false_positive": round(fp / max(fp + tn, 1), 4)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Counterfactual repair replay from fixed MAMO baseline code."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod
from scripts.m1_pilot import extract_code, run_code
from scripts.m3_industryor import (SCIP_CONTRACT, countable_witness_feedback,
                                   feedback_msg)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--baseline-tag", default="z2_mamo_base4")
    ap.add_argument("--data", required=True)
    ap.add_argument("--witness-config", required=True)
    ap.add_argument("--extra-priors", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    rows = {r["id"]: r for r in json.loads(Path(args.data).read_text())}
    config = json.loads(Path(args.witness_config).read_text())
    priors = Path(args.extra_priors).read_text().strip()
    baseline = [json.loads(l) for l in Path(args.baseline).read_text().splitlines() if l.strip()]
    last = {}
    for r in baseline:
        if r["id"] not in last or r["round"] > last[r["id"]]["round"]:
            last[r["id"]] = r
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = llm_mod.load_config()
    done = set()
    if args.resume and out_path.exists():
        done = {json.loads(l)["id"] for l in out_path.read_text().splitlines() if l.strip()}

    for pid, prev in sorted(last.items()):
        if pid in done:
            print(pid, "resume_skip", flush=True)
            continue
        question = rows[pid]["en_question"]
        prompt = priors + "\n\n" + SCIP_CONTRACT + question
        sandbox0 = (ROOT / "runs/industryor/sandbox"
                    / f"{args.baseline_tag}__{pid}__r{prev['round']}")
        code = (sandbox0 / "gen.py").read_text()
        for rnd in range(1, args.max_rounds + 1):
            sandbox = out_path.parent / "sandbox" / f"{pid}__r{rnd}"
            feedback = countable_witness_feedback(config, pid, code)
            if feedback:
                rec = {"id": pid, "round": rnd, "exec_status": "witness_block",
                       "guard_rule": "COUNTABLE_INTEGER", "guard_feedback": feedback,
                       "reference": prev["reference"]}
                print(f"[{pid}][r{rnd}] witness_block", flush=True)
            else:
                rec = {"id": pid, "round": rnd, "reference": prev["reference"]}
                rec.update(run_code(code, sandbox))
                print(f"[{pid}][r{rnd}] exec={rec.get('exec_status')} "
                      f"obj={rec.get('objective')}", flush=True)
            with out_path.open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if not feedback and rec.get("objective") is not None:
                break
            if not feedback:
                feedback = feedback_msg(rec)
            if feedback is None:
                break
            t0 = time.time()
            extra = {"reasoning_effort": "medium"}
            if args.seed is not None:
                extra["seed"] = args.seed
            resp = llm_mod.chat(
                [{"role": "user", "content": prompt},
                 {"role": "assistant", "content": code},
                 {"role": "user", "content": feedback}],
                max_tokens=32768, temperature=0.0,
                extra=extra, config=cfg)
            latency = time.time() - t0
            call_rec = {"id": pid, "round": rnd, "seed": args.seed,
                        "llm_latency_s": round(latency, 1),
                        "usage": resp.get("usage"),
                        "finish_reason": resp.get("finish_reason")}
            with out_path.with_suffix(".calls.jsonl").open("a") as f:
                f.write(json.dumps(call_rec, ensure_ascii=False) + "\n")
            code = extract_code(resp.get("content") or "")
            print(f"[{pid}][r{rnd}] repair_llm={latency:.1f}s", flush=True)


if __name__ == "__main__":
    main()

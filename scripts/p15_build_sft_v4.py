#!/usr/bin/env python3
"""P15: build judge v4 SFT data from harvested active-judge trajectories.

Input : work/judge_data/harvest_v4.jsonl  (from scripts/p14_harvest_v4_traces.py)
Output: work/judge_data/sft_v4/{train_v4,eval_v4}.jsonl + stats_v4.json

What v4 learns (two program-level skills, not family rules):
  planner  : problem context -> executable check script (judge-writes-checks)
  decider  : context + script + sandbox output -> classified reasoning + VERDICT

Rejection sampling: keep a stage's sample only from cells whose FINAL verdict
matches the witness-derived label (wrong->INVALID, correct->VALID). Planner
additionally requires a clean run (no exec error/timeout, >=1 CHECK line).
Decider additionally requires finish_reason == "stop" (no truncation).

Split: judge_v2's deterministic split column (train -> train_v4, dev -> eval_v4).
Record shape matches the J1 pipeline ({key, wrong, weight, system, user,
target}) so the remote training tooling runs unchanged; key is prefixed with
the stage name so per-stage metrics stay separable.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARVEST = ROOT / "work" / "judge_data" / "harvest_v4.jsonl"
OUT_DIR = ROOT / "work" / "judge_data" / "sft_v4"


def verdict_correct(r) -> bool:
    v = r.get("verdict")
    return v == "INVALID" if r.get("wrong") else v == "VALID"


def planner_ok(r) -> bool:
    out = r.get("check_output") or ""
    if "[EXEC ERROR]" in out or "[TIMEOUT" in out:
        return False
    return "CHECK " in out


def decider_ok(r) -> bool:
    return (r.get("finish_reason") == "stop"
            and bool(r.get("decider_full"))
            and "VERDICT:" in r["decider_full"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--harvest", default=str(HARVEST))
    args = ap.parse_args()

    traces = [json.loads(l) for l in Path(args.harvest).read_text().splitlines()]
    train, dev = [], []
    skipped = Counter()
    for r in traces:
        if r.get("error"):
            skipped["error"] += 1
            continue
        if not verdict_correct(r):
            skipped["verdict_mismatch"] += 1
            continue
        sink = dev if r.get("split") == "dev" else train
        base = {"wrong": bool(r.get("wrong")), "weight": 1.0, "system": ""}
        if planner_ok(r) and r.get("planner_user") and r.get("script"):
            sink.append({"key": f"planner|{r['key']}", "user": r["planner_user"],
                         "target": f"```python\n{r['script']}\n```", **base})
        else:
            skipped["planner_reject"] += 1
        if decider_ok(r) and r.get("decider_user"):
            sink.append({"key": f"decider|{r['key']}", "user": r["decider_user"],
                         "target": r["decider_full"], **base})
        else:
            skipped["decider_reject"] += 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "train_v4.jsonl").open("w") as f:
        for r in train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (OUT_DIR / "eval_v4.jsonl").open("w") as f:
        for r in dev:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_valid = sum(1 for r in traces if not r.get("error"))
    stats = {
        "traces": len(traces),
        "train": len(train), "eval": len(dev),
        "train_by_stage": Counter(r["key"].split("|")[0] for r in train),
        "train_by_label": Counter(r["wrong"] for r in train),
        "eval_by_stage": Counter(r["key"].split("|")[0] for r in dev),
        "skipped": dict(skipped),
        "verdict_acc_on_harvest": round(
            sum(1 for r in traces if not r.get("error") and verdict_correct(r))
            / max(1, n_valid), 4),
    }
    (OUT_DIR / "stats_v4.json").write_text(json.dumps(stats, ensure_ascii=False,
                                                      indent=1, default=dict))
    print(json.dumps(stats, ensure_ascii=False, default=dict))


if __name__ == "__main__":
    main()

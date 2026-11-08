#!/usr/bin/env python3
"""Final three-way judge comparison on IndustryOR (and F5-F8 recap).

Arms:
  - trained judge v3 (remote GPU gen eval: logs/gen_eval_industryor.jsonl, fetched)
  - zero-shot Qwen27B direct (work/judge_data/zeroshot_industryor.jsonl)
  - active-perception judge (work/judge_data/active_industryor.jsonl)
Labels: cell-level `wrong` from industryor_judge_cells.jsonl.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def metrics(rows, label_key="wrong"):
    tp = sum(1 for r in rows if r[label_key] and r["verdict"] == "INVALID")
    fn = sum(1 for r in rows if r[label_key] and r["verdict"] != "INVALID")
    fp = sum(1 for r in rows if not r[label_key] and r["verdict"] == "INVALID")
    tn = sum(1 for r in rows if not r[label_key] and r["verdict"] != "INVALID")
    unp = sum(1 for r in rows if r["verdict"] is None)
    return {"n": len(rows), "tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "unparsed": unp,
            "detection": tp / max(tp + fn, 1),
            "fpr": fp / max(fp + tn, 1),
            "acc": (tp + tn) / max(len(rows), 1)}


def per_arm(rows):
    out = {}
    for arm in ("z0", "z1", "z2"):
        sub = [r for r in rows if f"_{arm}_" in r["key"]]
        if sub:
            out[arm] = metrics(sub)
    return out


def main() -> None:
    arms = {}
    p = ROOT / "work/judge_data/zeroshot_industryor.jsonl"
    if p.exists():
        arms["zero_shot_direct"] = [json.loads(l) for l in p.read_text().splitlines()]
    p = ROOT / "work/judge_data/active_industryor.jsonl"
    if p.exists():
        arms["active_rederive"] = [json.loads(l) for l in p.read_text().splitlines()]
    p = ROOT / "work/judge_data/active_ior2.jsonl"
    if p.exists():
        arms["active_instrumented"] = [json.loads(l) for l in p.read_text().splitlines()]
    p = ROOT / "work/judge_data/gen_eval_industryor.jsonl"
    if p.exists():  # fetched from remote; key format: industryor_<arm>_<id>|...
        arms["trained_v3"] = [json.loads(l) for l in p.read_text().splitlines()]

    for name, rows in arms.items():
        m = metrics(rows)
        print(f"\n== {name} ==  n={m['n']} unparsed={m['unparsed']}")
        print(f"   detection {m['tp']}/{m['tp']+m['fn']} = {m['detection']:.1%}   "
              f"FP {m['fp']}/{m['fp']+m['tn']} = {m['fpr']:.1%}   acc {m['acc']:.1%}")
        for arm, mm in per_arm(rows).items():
            print(f"   [{arm}] det {mm['detection']:.1%} ({mm['tp']}/{mm['tp']+mm['fn']})  "
                  f"fp {mm['fpr']:.1%}")


if __name__ == "__main__":
    main()

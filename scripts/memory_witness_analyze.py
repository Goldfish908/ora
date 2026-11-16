#!/usr/bin/env python3
"""Paired analysis for frozen-memory vs no-memory witness authoring."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def exact_p(a: int, b: int) -> float:
    n = a + b
    if not n:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(a, b) + 1)) / 2**n)


def load(run_dir: Path, cells: list[dict]) -> dict:
    evaluations = {}
    for path in run_dir.glob("*/final.json"):
        final = json.loads(path.read_text())
        evaluations[final["id"]] = final["evaluation"]
    records = []
    for cell in cells:
        base = evaluations.get(cell["id"], {})
        by_key = {r["key"]: r for r in base.get("records", [])}
        rec = by_key.get(cell["key"], {"status": "error", "fired": False,
                                      "error": "missing_evaluation"})
        records.append({**cell, **rec})
    return {"evaluations": evaluations, "records": records}


def metrics(records: list[dict]) -> dict:
    wrong = [r for r in records if r["wrong"]]
    clean = [r for r in records if not r["wrong"]]
    tp = sum(r["fired"] for r in wrong)
    fn = len(wrong) - tp
    fp = sum(r["fired"] for r in clean)
    tn = len(clean) - fp
    unknown = sum(r["status"] != "ok" for r in records)
    problems = {}
    for r in records:
        problems.setdefault(r["id"], []).append(r)
    gate = 0
    for rs in problems.values():
        w = [r for r in rs if r["wrong"]]
        c = [r for r in rs if not r["wrong"]]
        det = sum(r["fired"] for r in w) / max(len(w), 1)
        fpr = sum(r["fired"] for r in c) / max(len(c), 1)
        problem_unknown = sum(r["status"] != "ok" for r in rs)
        gate += det >= 0.6 and fpr == 0 and problem_unknown == 0
    return {"n": len(records), "wrong": len(wrong), "clean": len(clean),
            "tp": tp, "fn": fn, "fp": fp, "tn": tn, "unknown": unknown,
            "detection": tp / max(tp + fn, 1), "false_positive": fp / max(fp + tn, 1),
            "unknown_rate": unknown / max(len(records), 1),
            "problem_gate": gate, "n_problems": len(problems),
            "problem_gate_rate": gate / max(len(problems), 1)}


def paired(base: list[dict], other: list[dict]) -> dict:
    b = {r["key"]: r for r in base}
    o = {r["key"]: r for r in other}
    keys = sorted(set(b) & set(o))
    other_only_det = sum(o[k]["wrong"] and o[k]["fired"] and not b[k]["fired"] for k in keys)
    base_only_det = sum(b[k]["wrong"] and b[k]["fired"] and not o[k]["fired"] for k in keys)
    other_only_fp = sum(not o[k]["wrong"] and o[k]["fired"] and not b[k]["fired"] for k in keys)
    base_only_fp = sum(not b[k]["wrong"] and b[k]["fired"] and not o[k]["fired"] for k in keys)
    return {"n_paired": len(keys),
            "memory_only_detection": other_only_det,
            "baseline_only_detection": base_only_det,
            "detection_mcnemar_p": exact_p(other_only_det, base_only_det),
            "memory_only_false_positive": other_only_fp,
            "baseline_only_false_positive": base_only_fp,
            "false_positive_mcnemar_p": exact_p(other_only_fp, base_only_fp),
            "unknown_baseline": sum(b[k]["status"] != "ok" for k in keys),
            "unknown_memory": sum(o[k]["status"] != "ok" for k in keys)}


def figure(path: Path, arms: dict, title: str) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    labels = ["No memory", "Frozen dev memory"]
    names = ["baseline", "memory"]
    metrics_to_plot = [("detection", "Error detection"),
                       ("false_positive", "Clean-solution false positives"),
                       ("unknown_rate", "UNKNOWN rate"),
                       ("problem_gate_rate", "Per-problem gate pass")]
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.8))
    colors = ["#8c9bab", "#2374ab"]
    for ax, (key, title) in zip(axes, metrics_to_plot):
        vals = [100 * arms[name]["metrics"][key] for name in names]
        bars = ax.bar(labels, vals, color=colors, width=0.62)
        ax.set_title(title, fontsize=10)
        ax.set_ylim(0, 112)
        ax.set_ylabel("%")
        ax.tick_params(axis="x", rotation=12)
        ax.grid(axis="y", alpha=0.2)
        for bar, val in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, val + 2, f"{val:.1f}%",
                    ha="center", fontsize=9)
    fig.suptitle(title)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--baseline-dir", required=True)
    ap.add_argument("--memory-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--figure")
    ap.add_argument("--title", default="Frozen development memory vs no memory — NLP4LP validation")
    ap.add_argument("--ids", nargs="*")
    args = ap.parse_args()
    cells = [json.loads(l) for l in (Path(args.artifacts) / "cells.jsonl").read_text().splitlines() if l.strip()]
    if args.ids:
        cells = [c for c in cells if c["id"] in args.ids]
    baseline = load(Path(args.baseline_dir), cells)
    memory = load(Path(args.memory_dir), cells)
    result = {"baseline": {"run_dir": args.baseline_dir,
                           "metrics": metrics(baseline["records"])},
              "memory": {"run_dir": args.memory_dir,
                         "metrics": metrics(memory["records"])},
              "paired": paired(baseline["records"], memory["records"])}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if args.figure:
        figure(Path(args.figure), result, args.title)


if __name__ == "__main__":
    main()

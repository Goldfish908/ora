#!/usr/bin/env python3
"""Aggregate paired results from procedural-memory pilot arms."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.memory_witness_analyze import metrics, paired
from scripts.memory_witness_cegis import evaluate

ARMS = ("zero", "text", "procedure", "combined", "procedure_cegis", "scoped_ir")


def accepted_precision(records: list[dict]) -> float:
    accepted = [r for r in records if not r["fired"]]
    clean = sum(not r["wrong"] for r in accepted)
    return clean / max(len(accepted), 1)


def load_arm(run_dir: Path, arm: str, cells: list[dict], rescore: bool = False) -> dict:
    evaluations = {}
    grouped = {}
    if rescore:
        for cell in cells:
            grouped.setdefault(cell["id"], []).append(cell)
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    latency = 0.0
    rejected_count = 0
    valid_invariant_count = 0
    for path in (run_dir / arm).glob("*/final.json"):
        final = json.loads(path.read_text())
        if rescore and final["id"] not in grouped:
            continue
        if rescore and arm != "scoped_ir":
            evaluations[final["id"]] = evaluate(final.get("script") or "",
                                                grouped[final["id"]])
        else:
            evaluations[final["id"]] = final["evaluation"]
        rejected_count += final["evaluation"].get("rejected_count", 0) or 0
        valid_invariant_count += final["evaluation"].get("valid_invariant_count", 0) or 0
        for key in usage:
            usage[key] += (final.get("usage") or {}).get(key, 0) or 0
        latency += final.get("latency_s", 0) or 0
    records = []
    for cell in cells:
        base = evaluations.get(cell["id"], {})
        by_key = {r["key"]: r for r in base.get("records", [])}
        rec = by_key.get(cell["key"], {"status": "error", "fired": False,
                                      "error": "missing_evaluation"})
        records.append({**cell, **rec})
    result = metrics(records)
    result["accepted_precision"] = accepted_precision(records)
    result["usage"] = usage
    result["latency_s"] = latency
    result["rejected_count"] = rejected_count
    result["valid_invariant_count"] = valid_invariant_count
    return {"metrics": result, "records": records}


def figure(path: Path, arms: dict, figure_title: str = "Procedural vs declarative audit memory — NLP4LP dev pilot") -> None:
    import matplotlib.pyplot as plt

    names = [a for a in ARMS if a in arms]
    labels = ["No memory", "Text", "Procedure", "Combined", "Proc.+dev CEGIS", "Scoped IR"]
    label_map = dict(zip(ARMS, labels))
    plots = [("detection", "Error detection"),
             ("false_positive", "Clean false positives"),
             ("unknown_rate", "UNKNOWN rate"),
             ("problem_gate_rate", "Per-problem gate"),
             ("accepted_precision", "Accepted-solution precision")]
    colors = ["#8c9bab", "#d99a38", "#2374ab", "#4d9a6a", "#8054a2", "#bb4c9c"]
    fig, axes = plt.subplots(1, len(plots), figsize=(18, 4.2))
    for ax, (key, title) in zip(axes, plots):
        vals = [100 * arms[a]["metrics"][key] for a in names]
        bars = ax.bar([label_map[a] for a in names], vals,
                      color=colors[:len(names)], width=0.62)
        ax.set_title(title, fontsize=10)
        ax.set_ylim(0, 112)
        ax.set_ylabel("%")
        ax.tick_params(axis="x", rotation=18)
        ax.grid(axis="y", alpha=0.2)
        for bar, val in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, val + 2, f"{val:.1f}%",
                    ha="center", fontsize=8)
    fig.suptitle(figure_title)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--figure")
    ap.add_argument("--rescore", action="store_true")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--exclude-ids", nargs="*")
    ap.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    ap.add_argument("--title", default="Procedural vs declarative audit memory — NLP4LP dev pilot")
    args = ap.parse_args()
    run_dir = Path(args.run_dir)
    cells = [json.loads(line) for line in
             (Path(args.artifacts) / "cells.jsonl").read_text().splitlines()
             if line.strip()]
    if args.ids:
        cells = [c for c in cells if c["id"] in args.ids]
    if args.exclude_ids:
        cells = [c for c in cells if c["id"] not in args.exclude_ids]
    arms = {}
    for arm in args.arms:
        if (run_dir / arm).is_dir():
            arms[arm] = load_arm(run_dir, arm, cells, rescore=args.rescore)
    comparisons = {}
    for baseline, treatment in (("text", "procedure"), ("text", "combined"),
                                ("zero", "procedure"), ("procedure", "procedure_cegis"),
                                ("text", "procedure_cegis"), ("text", "scoped_ir"),
                                ("zero", "scoped_ir")):
        if baseline in arms and treatment in arms:
            comparisons[f"{treatment}_vs_{baseline}"] = paired(
                arms[baseline]["records"], arms[treatment]["records"])
    result = {"arms": arms, "comparisons": comparisons, "rescore": args.rescore}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    summary = {a: v["metrics"] for a, v in arms.items()}
    print(json.dumps({"arms": summary, "comparisons": comparisons},
                     ensure_ascii=False, indent=1))
    if args.figure:
        figure(Path(args.figure), arms, figure_title=args.title)


if __name__ == "__main__":
    main()

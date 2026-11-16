#!/usr/bin/env python3
"""Aggregate four-arm RetailOpt fixed-artifact semantic detection."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dvsa_fixed_arm_analyze import mcnemar_exact, metrics  # noqa: E402
from scripts.dvsa_retail_core import legacy_feedback, load_assets, semantic_feedback  # noqa: E402
from scripts.dvsa_retail_llm_judge import eligible_artifacts  # noqa: E402

ARMS = ["no_memory", "text_memory", "dvsa", "direct_legacy_witness"]


def deterministic_cells(artifacts, assets):
    output = {"dvsa": [], "direct_legacy_witness": []}
    for artifact in artifacts:
        feedback, _ = semantic_feedback(assets, artifact["data"], artifact["solution"])
        old = legacy_feedback(artifact["data"], artifact["solution"])
        for arm, item in (("dvsa", feedback), ("direct_legacy_witness", old)):
            detected = item["status"] == "VIOLATED"
            unknown = item["status"] == "UNKNOWN"
            output[arm].append({"artifact_id": artifact["artifact_id"], "original_key": artifact["original_key"],
                                "wrong": artifact["wrong"], "expected_rule": artifact["expected_rule"],
                                "detected": detected, "false_positive": not artifact["wrong"] and detected,
                                "unknown": unknown, "verdict": item["status"]})
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="work/mem_evo/replay_gen1/m1_pilot_schema_sol_gen1.jsonl")
    parser.add_argument("--sandbox-root", default="work/mem_evo/replay_gen1/sandbox")
    parser.add_argument("--judge-dir", default="work/dvsa/retailopt_llm_judge_bounded")
    parser.add_argument("--out", default="work/dvsa/retailopt_fixed_arms_analysis")
    parser.add_argument("--figure", default="/home/hewj13/paper_icml2027/figures/dvsa_retailopt_dev_fixed_arms.png")
    args = parser.parse_args()
    baseline = Path(args.baseline)
    sandbox_root = Path(args.sandbox_root)
    judge_dir = Path(args.judge_dir)
    for path in (baseline, sandbox_root, judge_dir):
        if not path.is_absolute():
            path = ROOT / path
    if not baseline.is_absolute():
        baseline = ROOT / baseline
    if not sandbox_root.is_absolute():
        sandbox_root = ROOT / sandbox_root
    if not judge_dir.is_absolute():
        judge_dir = ROOT / judge_dir
    artifacts = eligible_artifacts(baseline, sandbox_root)
    assets, asset_hashes = load_assets()
    cells = deterministic_cells(artifacts, assets)
    costs = {"dvsa": {"llm_calls": 0, "total_tokens": 0, "latency_s": 0},
             "direct_legacy_witness": {"llm_calls": 0, "total_tokens": 0, "latency_s": 0}}
    for arm in ("no_memory", "text_memory"):
        cells[arm] = []
        costs[arm] = {"llm_calls": 0, "total_tokens": 0, "latency_s": 0}
    for artifact in artifacts:
        for arm in ("no_memory", "text_memory"):
            directory = judge_dir / artifact["original_key"] / arm
            result = json.loads((directory / "result.json").read_text())
            rows = [json.loads(line) for line in (directory / "cells.jsonl").read_text().splitlines() if line.strip()]
            if rows:
                cells[arm].extend(rows)
            else:
                cells[arm].append({"artifact_id": artifact["artifact_id"], "original_key": artifact["original_key"],
                                   "wrong": artifact["wrong"], "expected_rule": artifact["expected_rule"],
                                   "detected": False, "false_positive": False, "unknown": True,
                                   "verdict": "UNKNOWN"})
            costs[arm]["llm_calls"] += result["llm_calls"]
            costs[arm]["total_tokens"] += (result.get("usage") or {}).get("total_tokens", 0)
            costs[arm]["latency_s"] += result.get("llm_latency_s", 0) or 0
    arm_metrics = {arm: metrics(cells[arm]) for arm in ARMS}
    comparisons = {}
    for other in ("no_memory", "text_memory", "direct_legacy_witness"):
        dvsa_only = sum(a["detected"] and not b["detected"]
                        for a, b in zip(cells["dvsa"], cells[other]))
        other_only = sum(b["detected"] and not a["detected"]
                         for a, b in zip(cells["dvsa"], cells[other]))
        dvsa_fp = sum(a["false_positive"] and not b["false_positive"]
                      for a, b in zip(cells["dvsa"], cells[other]))
        other_fp = sum(b["false_positive"] and not a["false_positive"]
                       for a, b in zip(cells["dvsa"], cells[other]))
        comparisons[f"dvsa_vs_{other}"] = {"dvsa_only": dvsa_only, "other_only": other_only,
                                           "mcnemar_exact_p": mcnemar_exact(dvsa_only, other_only),
                                           "dvsa_false_positive_only": dvsa_fp,
                                           "other_false_positive_only": other_fp,
                                           "false_positive_mcnemar_exact_p": mcnemar_exact(dvsa_fp, other_fp)}
    result = {"protocol": "retailopt-fixed-artifact-dvsa-four-arm-v0.1",
              "scope": "16 saved solutions with independent reference-qualified labels: 10 semantic violations and 6 business-correct; excludes one objective-only failure and three no-solution cases.",
              "artifact_ids": [row["artifact_id"] for row in artifacts],
              "asset_hashes": asset_hashes, "arms": arm_metrics,
              "comparisons": comparisons, "costs": costs, "cells": cells,
              "scoring_note": "Legacy witness supplies both A3 feedback and reference-qualified labels; A3 agreement is not independent proof of zero false positives.",
              "judge_decoding": "enable_thinking=false; max_tokens=8192",
              "failed_medium_judge_archive": "work/dvsa/retailopt_llm_judge/ (reasoning exhausted output budget; excluded)",
              "sota_started": False}
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    labels = ["No\nmemory", "Text\nmemory", "DVSA", "Legacy\nwitness"]
    colors = ["#94a3b8", "#f59e0b", "#0f766e", "#cbd5e1"]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2))
    for axis, metric, title in zip(axes, ("detection", "false_positive", "unknown"),
                                   ("Semantic error detection", "Clean false positive", "UNKNOWN / artifacts")):
        values = [arm_metrics[arm][metric] * 100 for arm in ARMS]
        axis.bar(labels, values, color=colors)
        axis.set_title(title)
        axis.set_ylim(0, 105)
        axis.set_ylabel("%")
        for index, value in enumerate(values):
            axis.text(index, value + 2, f"{value:.1f}", ha="center", fontsize=9)
    fig.suptitle("RetailOpt fixed-artifact detection: 16 reference-qualified dev solutions")
    fig.subplots_adjust(left=0.07, right=0.98, bottom=0.18, top=0.82, wspace=0.32)
    figure = Path(args.figure)
    figure.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure, dpi=180)
    plt.close(fig)
    print(json.dumps({"arms": arm_metrics, "comparisons": comparisons, "costs": costs}, indent=2))
    print(f"figure={figure}")


if __name__ == "__main__":
    main()

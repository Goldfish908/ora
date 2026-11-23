#!/usr/bin/env python3
"""Render the five-arm GEPA-inspired federated comparison."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARMS = ["direct-full", "single", "old-population", "pareto-only", "pareto+compatible+merge"]
LABELS = {
    "direct-full": "Direct full",
    "single": "Single chain",
    "old-population": "Old population",
    "pareto-only": "Pareto only",
    "pareto+compatible+merge": "Pareto + merge",
}
COLORS = {
    "direct-full": "#187a68",
    "single": "#2c5d9f",
    "old-population": "#8c6d5d",
    "pareto-only": "#d5a03c",
    "pareto+compatible+merge": "#7b5aa6",
}
SCENARIOS = {"duplicate_client": "Duplicate\nclient", "stream_minimums": "Stream\nminimums", "all_budgets": "All\nbudgets"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    audit = json.loads((ROOT / args.audit).read_text())
    rows = audit["scenarios"]
    x = np.arange(len(rows))
    width = 0.15

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 8.5,
        "axes.titlesize": 10, "axes.labelsize": 9,
        "axes.spines.top": False, "axes.spines.right": False,
        "figure.dpi": 150,
    })
    figure, axes = plt.subplots(1, 2, figsize=(11.2, 4.0))

    for index, arm in enumerate(ARMS):
        values = [row["arms"][arm]["official"]["objective"] for row in rows]
        axes[0].bar(x + (index - 2) * width, values, width, label=LABELS[arm], color=COLORS[arm])
    axes[0].set_xticks(x, [SCENARIOS[row["scenario"]] for row in rows])
    axes[0].set_ylabel("Official objective (maximize)")
    axes[0].set_title("A  Official objective; all 15 runs true correct")
    axes[0].set_ylim(6000, 6030)

    for index, arm in enumerate(ARMS):
        values = [row["arms"][arm]["total_search_seconds"] for row in rows]
        axes[1].bar(x + (index - 2) * width, values, width, label=LABELS[arm], color=COLORS[arm])
    axes[1].set_xticks(x, [SCENARIOS[row["scenario"]] for row in rows])
    axes[1].set_ylabel("Search time (seconds)")
    axes[1].set_title("B  Search cost; official scoring excluded")
    axes[1].set_ylim(0, 10)

    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[arm]) for arm in ARMS]
    figure.legend(handles=handles, labels=[LABELS[arm] for arm in ARMS],
                  loc="lower center", ncol=5, frameon=False, bbox_to_anchor=(0.5, 0.035))
    figure.suptitle("GEPA-inspired repair: Pareto recovers the single-chain objective", fontsize=12, y=1.02)
    figure.text(0.01, 0.005,
                "Pareto-only vs old population: +0.544 on all_budgets and ties elsewhere. "
                "No compatible merge was tested; development scenarios only. Zero LLM calls.",
                fontsize=8, color="#4d5560")
    figure.tight_layout(rect=(0, 0.19, 1, 1))
    output = ROOT / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, bbox_inches="tight")
    plt.close(figure)
    print(output)


if __name__ == "__main__":
    main()

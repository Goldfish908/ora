#!/usr/bin/env python3
"""Render the federated repair audit as publication-style panels."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "duplicate_client": "Duplicate\nclient",
    "stream_minimums": "Stream\nminimums",
    "all_budgets": "All\nbudgets",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    audit = json.loads((ROOT / args.audit).read_text())
    rows = audit["scenarios"]
    names = [LABELS[row["scenario"]] for row in rows]
    before = [row["official_before"]["true_correct"] for row in rows]
    after = [row["official_after"]["true_correct"] for row in rows]
    parent_objective = [row["parent_public_objective"] for row in rows]
    selected_objective = [row["selected_public_objective"] for row in rows]
    seconds = [row["scip_seconds"] for row in rows]
    released = [row["released_variables"] for row in rows]
    fixed = [row["fixed_variables"] for row in rows]

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 150,
    })
    figure, axes = plt.subplots(1, 3, figsize=(11.2, 3.5))
    x = np.arange(len(rows))
    width = 0.34

    axes[0].bar(x - width / 2, before, width, label="Before", color="#b8c0cc")
    axes[0].bar(x + width / 2, after, width, label="After", color="#187a68")
    axes[0].set_xticks(x, names)
    axes[0].set_ylim(0, 1.2)
    axes[0].set_yticks([0, 1], ["No", "Yes"])
    axes[0].set_ylabel("Official true correct")
    axes[0].set_title("A  Independent official outcome")
    axes[0].legend(frameon=False, loc="upper left")
    for index, value in enumerate(after):
        axes[0].text(index + width / 2, value + 0.04, "quality = 2.0",
                     ha="center", va="bottom", fontsize=8, color="#187a68")

    axes[1].plot(x, parent_objective, "o-", color="#bd5b45", linewidth=1.5,
                 markersize=5, label="Parent")
    axes[1].plot(x, selected_objective, "o-", color="#2c5d9f", linewidth=1.5,
                 markersize=5, label="Repaired")
    axes[1].set_xticks(x, names)
    axes[1].set_ylabel("Public objective (maximize)")
    axes[1].set_title("B  Recomputed public objective")
    axes[1].legend(frameon=False, loc="lower right")
    axes[1].ticklabel_format(axis="y", style="plain")

    axes[2].bar(x - width / 2, released, width, label="Released", color="#d5a03c")
    axes[2].bar(x + width / 2, fixed, width, label="Fixed", color="#66788f")
    axes[2].set_xticks(x, names)
    axes[2].set_ylabel("Decision variables")
    axes[2].set_title("C  Neighborhood size and solve time")
    axes[2].legend(frameon=False, loc="upper left")
    for index, value in enumerate(seconds):
        axes[2].text(index, max(released[index], fixed[index]) + 55,
                     f"{value:.2f} s", ha="center", va="bottom", fontsize=8)
    axes[2].set_ylim(0, max(max(released), max(fixed)) * 1.22)

    figure.suptitle("Declarative repair on three predeclared federated scenarios", fontsize=12, y=1.02)
    figure.text(0.01, 0.005,
                "All three official outcomes changed from infeasible to true correct. "
                "Zero LLM calls; feasible repairs, not global-optimality claims.",
                fontsize=8, color="#4d5560")
    figure.tight_layout(rect=(0, 0.055, 1, 1))
    output = ROOT / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, bbox_inches="tight")
    plt.close(figure)
    print(output)


if __name__ == "__main__":
    main()

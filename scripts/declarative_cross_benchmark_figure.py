#!/usr/bin/env python3
"""Plot verified declarative-repair cases without pooling benchmark metrics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--federated", required=True)
    parser.add_argument("--industryor", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    federated = json.loads((ROOT / args.federated).read_text())
    industry = json.loads((ROOT / args.industryor).read_text())
    fed_rows = federated["scenarios"]
    ind_rows = industry["problems"][0]["roots"]

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 9,
        "axes.titlesize": 10, "axes.labelsize": 9,
        "axes.spines.top": False, "axes.spines.right": False,
        "figure.dpi": 150,
    })
    figure, axes = plt.subplots(1, 2, figsize=(8.6, 3.6))
    width = 0.34
    gray, green = "#b8c0cc", "#187a68"

    x = np.arange(len(fed_rows))
    before = [row["official_before"]["true_correct"] for row in fed_rows]
    after = [row["official_after"]["true_correct"] for row in fed_rows]
    axes[0].bar(x - width / 2, before, width, color=gray, label="Parent")
    axes[0].bar(x + width / 2, after, width, color=green, label="Repaired")
    axes[0].set_xticks(x, ["Duplicate\nclient", "Stream\nminimums", "All\nbudgets"])
    axes[0].set_yticks([0, 1], ["No", "Yes"])
    axes[0].set_ylim(0, 1.25)
    axes[0].set_ylabel("Official true correct")
    axes[0].set_title("A  ORAgentBench: federated scenarios")
    axes[0].legend(frameon=False, loc="upper left", bbox_to_anchor=(0.0, -0.18), ncol=2)

    x = np.arange(len(ind_rows))
    before = [row["parent_business"]["business_correct"] for row in ind_rows]
    after = [row["selected_business"]["business_correct"] for row in ind_rows]
    axes[1].bar(x - width / 2, before, width, color=gray, label="Parent")
    axes[1].bar(x + width / 2, after, width, color=green, label="Repaired")
    axes[1].set_xticks(x, ["Narrow failure", "Correct control"])
    axes[1].set_yticks([0, 1], ["No", "Yes"])
    axes[1].set_ylim(0, 1.25)
    axes[1].set_ylabel("Registered business correct")
    axes[1].set_title("B  IndustryOR: registered ID9")
    axes[1].legend(frameon=False, loc="upper left", bbox_to_anchor=(0.0, -0.18), ncol=2)

    figure.suptitle("Declarative neighborhood repair: independently verified cases", fontsize=12, y=1.02)
    figure.text(0.01, 0.005,
                "Separate metrics and repair-only roots; no pooled accuracy, cross-benchmark ranking or global-optimality claim. Zero LLM calls.",
                fontsize=8, color="#4d5560")
    figure.tight_layout(rect=(0, 0.15, 1, 1))
    output = ROOT / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, bbox_inches="tight")
    plt.close(figure)
    print(output)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Plot same-root population, single-chain and direct-full outcomes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ("single_chain", "population", "direct_full")
COLORS = {"single_chain": "#2c5d9f", "population": "#d5a03c", "direct_full": "#187a68"}
LABELS = {"single_chain": "Single chain", "population": "Population", "direct_full": "Direct full"}
SCENARIOS = {"duplicate_client": "Duplicate\nclient", "stream_minimums": "Stream\nminimums", "all_budgets": "All\nbudgets"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    audit = json.loads((ROOT / args.audit).read_text())
    rows = audit["scenarios"]
    x = np.arange(len(rows))
    width = 0.25

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 9,
        "axes.titlesize": 10, "axes.labelsize": 9,
        "axes.spines.top": False, "axes.spines.right": False,
        "figure.dpi": 150,
    })
    figure, axes = plt.subplots(1, 2, figsize=(9.4, 3.8))

    for index, strategy in enumerate(STRATEGIES):
        values = [row["arms"][strategy]["official"]["objective"] for row in rows]
        axes[0].bar(x + (index - 1) * width, values, width,
                    color=COLORS[strategy], label=LABELS[strategy])
    axes[0].set_xticks(x, [SCENARIOS[row["scenario"]] for row in rows])
    axes[0].set_ylabel("Official objective (maximize)")
    axes[0].set_title("A  Official objective; all true correct")
    axes[0].set_ylim(6000, 6030)
    axes[0].legend(frameon=False, loc="upper left", bbox_to_anchor=(0.0, -0.18), ncol=3)

    for index, strategy in enumerate(STRATEGIES):
        values = [row["arms"][strategy]["total_search_seconds"] for row in rows]
        axes[1].bar(x + (index - 1) * width, values, width,
                    color=COLORS[strategy], label=LABELS[strategy])
    axes[1].set_xticks(x, [SCENARIOS[row["scenario"]] for row in rows])
    axes[1].set_ylabel("Total search time (seconds)")
    axes[1].set_title("B  Search cost; lower is better")
    axes[1].set_ylim(0, 58)
    axes[1].legend(frameon=False, loc="upper left", bbox_to_anchor=(0.0, -0.18), ncol=3)

    figure.suptitle("Same-root repair: population does not outperform single chain", fontsize=12, y=1.02)
    figure.text(0.01, 0.005,
                "All 9 strategy-scenario outcomes are official true correct with quality 2.0. "
                "Population: 2 ties and 1 worse vs single; direct-full is cheapest. Zero LLM calls.",
                fontsize=8, color="#4d5560")
    figure.tight_layout(rect=(0, 0.15, 1, 1))
    output = ROOT / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, bbox_inches="tight")
    plt.close(figure)
    print(output)


if __name__ == "__main__":
    main()

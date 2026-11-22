#!/usr/bin/env python3
"""Plot direct and repaired official outcomes for two clean-room batches."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from ora_agent.oragentbench import read_json

ROOT = Path(__file__).resolve().parents[1]
ARMS = ("B0_empty_specification", "B1_gepa_specification", "B2_gepa_residual_dag", "B3_verified_memory")


def draw(summary: dict, axis, title: str) -> None:
    by_arm = {arm["arm"]: arm for arm in summary["arms"]}
    x = np.arange(len(ARMS))
    width = 0.19
    metrics = (("true_correct", "direct", "Direct true", "#3569a8"),
               ("true_correct", "final", "Final true", "#4b9b74"),
               ("phantom_proxy", "final", "Phantom proxy", "#d28b36"),
               ("unknown", "final", "UNKNOWN", "#8b8f98"))
    for index, (key, section, label, color) in enumerate(metrics):
        values = [by_arm[arm].get(section, {}).get(key, 0) if "final" in by_arm[arm] else 0
                  for arm in ARMS]
        bars = axis.bar(x + (index - 1.5) * width, values, width, label=label, color=color)
        axis.bar_label(bars, labels=[str(value) if value else "" for value in values], padding=2, fontsize=8)
    for index, arm in enumerate(ARMS):
        if "final" not in by_arm[arm]:
            axis.text(index, 0.06, "not_run", ha="center", va="bottom", fontsize=8, color="#666666")
        else:
            final = by_arm[arm]["final"]
            axis.text(index, 0.98, f"n={final['n']}/{by_arm[arm]['n_expected']}",
                      transform=axis.get_xaxis_transform(), ha="center", va="top",
                      fontsize=7, color="#555555")
    axis.set_xticks(x, ("B0", "B1", "B2", "B3"))
    axis.set_ylabel("Tasks")
    axis.set_title(title)
    axis.set_ylim(0, max(1, max(arm.get("n_expected", 0) for arm in by_arm.values())) * 1.2)
    axis.grid(axis="x", visible=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True)
    parser.add_argument("--transfer", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    audit = read_json((ROOT / args.audit).resolve())
    transfer = read_json((ROOT / args.transfer).resolve())
    plt.rcParams.update({"font.family": "serif", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.2})
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.4), sharey=False)
    draw(audit, axes[0], f"Independent audit (n={len(audit['expected_tasks'])})")
    draw(transfer, axes[1], f"Subsequent transfer pilot (n={len(transfer['expected_tasks'])})")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=8, loc="upper center",
               bbox_to_anchor=(0.5, 0.94), ncol=4)
    fig.suptitle("Official outcomes after bounded residual repair")
    safety = (f"True: official feasible && quality > 0.4; end-to-end B0→B2 win-safe: "
              f"audit={audit['b0_to_b2'].get('win_safe')}, transfer={transfer['b0_to_b2'].get('win_safe')}")
    fig.text(0.5, 0.01, safety, ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.06, 1, 0.86))
    out = (ROOT / args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=220, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()

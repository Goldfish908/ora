#!/usr/bin/env python3
"""Layered-verification ablation figure: arms A / B / B' on RetailOpt-190 (on-mode).

A  = post-hoc witness feedback only
B  = A + pre-solve gate (requirement-ledger diff)
B' = B + crash guard v0.1 (static API-misuse rewrite)
Numbers are final full-run results (190 cells/arm, shared round-1 pilot).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ARMS = ["A\n(witness)", "B\n(+gate)", "B'\n(+guard)"]
SUCCESS = [84, 87, 90]
RESIDUAL = {
    "crash": [18, 37, 19],
    "witness_infeasible": [75, 50, 70],
    "timelimit_no_incumbent": [10, 12, 5],   # A: derived 190-84-18-75-3
    "suboptimal+declared": [3, 4, 6],
}
SOLVES = [249, 184, 235]

fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.6))

# (a) true success
ax = axes[0]
bars = ax.bar(ARMS, SUCCESS, color=["#8fb8de", "#5b8fc9", "#2f6db3"])
for b, v in zip(bars, SUCCESS):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.8, f"{v}/190\n({v/190:.1%})",
            ha="center", fontsize=9)
ax.axhline(13, color="#c0392b", linestyle="--", linewidth=1.2)
ax.text(2.42, 14.5, "no loop (pass@1)\n13/190 (6.8%)", color="#c0392b",
        fontsize=8, ha="right")
ax.set_ylim(0, 105)
ax.set_title("(a) true success (witness + ref-objective)")
ax.set_ylabel("cells")

# (b) residual structure (stacked)
ax = axes[1]
bottom = np.zeros(3)
colors = {"crash": "#d9534f", "witness_infeasible": "#f0ad4e",
          "timelimit_no_incumbent": "#7f7f7f", "suboptimal+declared": "#bcbcbc"}
for k, vals in RESIDUAL.items():
    vals = np.array(vals)
    ax.bar(ARMS, vals, bottom=bottom, label=k, color=colors[k])
    for i, v in enumerate(vals):
        if v >= 8:
            ax.text(i, bottom[i] + v / 2, str(v), ha="center", va="center",
                    fontsize=9, color="white" if k == "crash" else "black")
    bottom += vals
ax.set_title("(b) residual failure structure")
ax.set_ylabel("cells")
ax.legend(fontsize=8, loc="center left", bbox_to_anchor=(1.02, 0.5))

# (c) solver invocations
ax = axes[2]
bars = ax.bar(ARMS, SOLVES, color=["#8fb8de", "#5b8fc9", "#2f6db3"])
for b, v in zip(bars, SOLVES):
    ax.text(b.get_x() + b.get_width() / 2, v + 4, str(v), ha="center", fontsize=9)
ax.set_ylim(0, 290)
ax.set_title("(c) solver invocations (loop phase)")

fig.suptitle("Layered verification ablation — RetailOpt-190, Qwen3_8-27B, "
             "max 3 rounds, shared round-1 pilot", fontsize=11)
fig.tight_layout(rect=[0, 0, 1, 0.94])
out = "docs/paper/figs/layered_ablation_v0.1.png"
fig.savefig(out, dpi=160)
print("saved", out)

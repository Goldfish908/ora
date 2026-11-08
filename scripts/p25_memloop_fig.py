#!/usr/bin/env python3
"""P25: memory × loop composition (arm C) figure.

Question: does generation-side semantic memory (P3 conventions) compose with
the full repair loop (pre-solve gate + crash guard + witness feedback), or is
it redundant/conflicting?

Arms (RetailOpt-190, Qwen3_8-27B, thinking on, max 3 rounds):
  baseline  pass@1, no memory, no loop      (runs/m1_pilot)
  P3        pass@1, memory, no loop         (runs/m1_pilot_priors3)
  B''       no memory + full loop           (m1_presolve_guard3_*)
  C         memory + full loop              (m1_presolve_memloop_*)

Panels:
  (a) cumulative true success by round (lines) + pass@1 baselines (h-lines)
  (b) final true success (bars, labeled) 
  (c) residual failure structure (stacked bars)
  (d) loop-phase budget: solver invocations + LLM calls

Usage: python3 scripts/p25_memloop_fig.py
Output: docs/paper/figures/memory_loop_composition.png
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.psv_online_analysis import (  # noqa: E402
    load_r1, final_states, summarize, load_loop_records, budget,
    per_round_curve)

P3 = ROOT / "runs" / "m1_pilot_priors3"
MODE = "on"

plt.rcParams["font.family"] = "WenQuanYi Zen Hei"
plt.rcParams["axes.unicode_minus"] = False


def main() -> None:
    r1_base = load_r1()
    r1_p3 = load_r1(P3, "m1_pilot_schema_sol_p3_v*.jsonl")
    st_base = summarize(final_states("runs/none", r1_base), MODE)
    st_p3 = summarize(final_states("runs/none", r1_p3), MODE)
    st_bpp = summarize(final_states(
        "runs/m1_presolve/m1_presolve_guard3_*.jsonl", r1_base), MODE)
    st_c = summarize(final_states(
        "runs/m1_presolve/m1_presolve_memloop_*.jsonl", r1_p3), MODE)
    rec_bpp = load_loop_records("runs/m1_presolve/m1_presolve_guard3_*.jsonl")
    rec_c = load_loop_records("runs/m1_presolve/m1_presolve_memloop_*.jsonl")
    cur_bpp = per_round_curve(rec_bpp, r1_base, MODE)
    cur_c = per_round_curve(rec_c, r1_p3, MODE)
    bud_bpp = budget(rec_bpp, MODE, gated_skips_solve=True)
    bud_c = budget(rec_c, MODE, gated_skips_solve=True)

    names = ["基线\n单发", "P3\nmemory 单发", "B''\n环路(无 memory)", "C\n环路+memory"]
    stats = [st_base, st_p3, st_bpp, st_c]
    colors = ["#b8b8b8", "#e0a458", "#5b8fc9", "#2f7d5b"]

    fig, axes = plt.subplots(1, 4, figsize=(19.5, 4.6))
    fig.suptitle("语义 memory × 修复环路 组合实验:RetailOpt-190 · Qwen3.8-27B · thinking 开 · 最多 3 轮",
                 fontsize=13)

    # (a) cumulative success by round
    ax = axes[0]
    rounds = [1, 2, 3]
    ax.plot(rounds, [cur_bpp[r] for r in rounds], "o-", color="#5b8fc9",
            lw=2, label="B'' 环路(无 memory)")
    ax.plot(rounds, [cur_c[r] for r in rounds], "s-", color="#2f7d5b",
            lw=2, label="C 环路+memory")
    ax.axhline(st_base["success"], ls="--", color="#b8b8b8", lw=1.2)
    ax.axhline(st_p3["success"], ls="--", color="#e0a458", lw=1.2)
    ax.text(3.05, st_base["success"], f"基线 {st_base['success']}",
            va="center", fontsize=9, color="#888")
    ax.text(3.05, st_p3["success"], f"P3 单发 {st_p3['success']}",
            va="center", fontsize=9, color="#b07830")
    for r in rounds:
        ax.text(r, cur_bpp[r] + 2, str(cur_bpp[r]), ha="center", fontsize=9,
                color="#5b8fc9")
        ax.text(r, cur_c[r] - 5, str(cur_c[r]), ha="center", fontsize=9,
                color="#2f7d5b")
    ax.set_xticks(rounds)
    ax.set_xlabel("轮次")
    ax.set_ylabel("累计真成功(/190)")
    ax.set_title("(a) 逐轮累计真成功")
    ax.legend(fontsize=9, loc="lower right")
    ax.set_xlim(0.8, 3.7)

    # (b) final success bars
    ax = axes[1]
    vals = [s["success"] for s in stats]
    bars = ax.bar(names, vals, color=colors)
    for b, v, s in zip(bars, vals, stats):
        ax.text(b.get_x() + b.get_width() / 2, v + 1.5,
                f"{v}/190\n({v/190*100:.1f}%)", ha="center", fontsize=9)
    ax.set_ylabel("真成功(witness+目标值双判)")
    ax.set_title("(b) 最终真成功")
    ax.set_ylim(0, max(vals) * 1.28)
    ax.tick_params(axis="x", labelsize=8.5)

    # (c) residual failure structure
    ax = axes[2]
    cats = ["crash", "witness_infeasible", "timelimit_no_incumbent",
            "suboptimal", "no_solution_dump", "declared_infeasible"]
    clabel = {"crash": "崩溃", "witness_infeasible": "语义违例",
              "timelimit_no_incumbent": "超时无解", "suboptimal": "次优",
              "no_solution_dump": "无解转储", "declared_infeasible": "声明不可行"}
    ccolor = {"crash": "#c0504d", "witness_infeasible": "#e0a458",
              "timelimit_no_incumbent": "#9b7bb8", "suboptimal": "#8fa8bf",
              "no_solution_dump": "#d9c9a3", "declared_infeasible": "#b8b8b8"}
    bottoms = np.zeros(4)
    x = np.arange(4)
    for cname in cats:
        vals_c = [s["residual"].get(cname, 0) for s in stats]
        if sum(vals_c) == 0:
            continue
        ax.bar(x, vals_c, bottom=bottoms, color=ccolor[cname],
               label=clabel[cname])
        for xi, (v, b) in enumerate(zip(vals_c, bottoms)):
            if v >= 5:
                ax.text(xi, b + v / 2, str(v), ha="center", va="center",
                        fontsize=9, color="white")
        bottoms += np.array(vals_c)
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=8.5)
    ax.set_ylabel("残留失败数")
    ax.set_title("(c) 残留失败结构")
    ax.legend(fontsize=8.5)

    # (d) loop budget
    ax = axes[3]
    blabels = ["B'' 环路", "C 环路+memory"]
    solves = [bud_bpp.get("solves", 0), bud_c.get("solves", 0)]
    llm = [bud_bpp.get("llm_calls", 0), bud_c.get("llm_calls", 0)]
    x = np.arange(2)
    b1 = ax.bar(x - 0.19, solves, width=0.36, color="#5b8fc9",
                label="求解器调用")
    b2 = ax.bar(x + 0.19, llm, width=0.36, color="#e0a458",
                label="LLM 调用(修复+闸门+guard)")
    for xi, v in zip(x - 0.19, solves):
        ax.text(xi, v + 3, str(v), ha="center", fontsize=10)
    for xi, v in zip(x + 0.19, llm):
        ax.text(xi, v + 3, str(v), ha="center", fontsize=10)
    ax.set_xticks(x)
    ax.set_xticklabels(blabels, fontsize=9.5)
    ax.set_title("(d) 环内预算消耗")
    ax.legend(fontsize=9)

    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out = ROOT / "docs" / "paper" / "figures" / "memory_loop_composition.png"
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

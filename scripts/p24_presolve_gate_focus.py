#!/usr/bin/env python3
"""P24: standalone pre-solve gate comparison (isolate gate contribution).

Arms (RetailOpt-190, Qwen3_8-27B, thinking on, max 3 rounds, shared R1 pilot):
  A   witness-only        (no pre-solve gate)
  B   +gate               (requirement-ledger diff before every solve)
  B'' +gate+guard0.3      (gate + static crash-rewrite rules)

Panels:
  (a) solve budget: solver invocations + solver wall-clock (loop phase)
  (b) quality: true success % + residual failure structure
  (c) cost efficiency: E2E seconds per true success + exec-success rate

Data: work/supp_compare/supp_tables.json (final full-run aggregates).
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
plt.rcParams["font.family"] = "WenQuanYi Zen Hei"
plt.rcParams["axes.unicode_minus"] = False

d = json.loads((ROOT / "work" / "supp_compare" / "supp_tables.json").read_text())
ARMS = ["A witness-only", "B +gate", "B'' +guard0.3"]
LABELS = ["A 仅事后见证\n(无预求解闸门)", "B +预求解闸门\n(台账 diff)", "B'' 闸门+静态规则\n(guard0.3)"]
G = [d["gate_arms"][a] for a in ARMS]

solves = [g["budget"]["solves"] for g in G]
solve_s = [g["budget"]["solve_s"] / 3600 for g in G]
succ = [g["rate"] for g in G]
nsucc = [g["success"] for g in G]
e2e = [g["e2e_s_per_success"] for g in G]
crashes = [g["loop_crashes"] for g in G]
exec_rate = [s / (s + c) * 100 for s, c in zip(solves, crashes)]
winf = [g["residual"].get("witness_infeasible", 0) for g in G]
rcrash = [g["residual"].get("crash", 0) for g in G]
gate_turns = [g["budget"]["gate_turns"] for g in G]

C = ["#8fa8bf", "#5b8fc9", "#2f6db3"]
fig, axes = plt.subplots(1, 3, figsize=(15.8, 5.0))
fig.suptitle("预求解闸门单独对照:RetailOpt-190 · Qwen3.8-27B · thinking 开 · 最多 3 轮修复(共享第 1 轮)",
             fontsize=13)

# (a) solve budget
ax = axes[0]
x = np.arange(3)
b1 = ax.bar(x - 0.19, solves, width=0.36, color=C, label="求解器调用次数")
ax2 = ax.twinx()
b2 = ax2.bar(x + 0.19, solve_s, width=0.36, color="#e0a458", label="求解器墙钟(小时)")
for xi, v in zip(x - 0.19, solves):
    ax.text(xi, v + 4, str(v), ha="center", fontsize=10)
for xi, v in zip(x + 0.19, solve_s):
    ax2.text(xi, v + 0.08, f"{v:.1f}h", ha="center", fontsize=10)
ax.set_xticks(x); ax.set_xticklabels(LABELS, fontsize=9)
ax.set_ylabel("环内求解器调用次数")
ax2.set_ylabel("环内求解器墙钟(小时)", color="#b07818")
ax2.set_ylim(0, 6.4); ax.set_ylim(0, 285)
ax.set_title("(a) 求解预算:闸门省掉 26% 调用、16% 求解时间", fontsize=11)
ax.annotate("-26.1%", xy=(1 - 0.19, 184), xytext=(0.45, 255),
            fontsize=11, color="#c0392b", fontweight="bold",
            arrowprops=dict(arrowstyle="->", color="#c0392b"))
ax.annotate("-16.4%", xy=(1 + 0.19, 4.03), xytext=(0.72, 5.6),
            fontsize=11, color="#b07818", fontweight="bold",
            arrowprops=dict(arrowstyle="->", color="#b07818"))

# (b) quality
ax = axes[1]
b = ax.bar(x - 0.19, succ, width=0.36, color=C, label="真成功率 %(见证+目标值双判)")
b2 = ax.bar(x + 0.19, winf, width=0.36, color="#c0392b", alpha=0.75,
            label="残留:见证判不可行/190")
for xi, v, n in zip(x - 0.19, succ, nsucc):
    ax.text(xi, v + 1.2, f"{v:.1f}%\n({n}/190)", ha="center", fontsize=9.5)
for xi, v in zip(x + 0.19, winf):
    ax.text(xi, v + 1.2, str(v), ha="center", fontsize=10)
ax.axhline(6.8, color="#888888", ls="--", lw=1)
ax.text(-0.42, 9.5, "无修复环 pass@1 = 6.8%", fontsize=8, color="#666666")
ax.set_xticks(x); ax.set_xticklabels(LABELS, fontsize=9)
ax.set_ylabel("% / 细胞数"); ax.set_ylim(0, 92)
ax.set_title("(b) 质量:真成功 +1.6pp,语义卡死 -33%(75→50)", fontsize=11)
ax.legend(fontsize=8.5, loc="upper right")

# (c) efficiency + executability
ax = axes[2]
b = ax.bar(x - 0.19, e2e, width=0.36, color=C, label="每真成功 E2E 秒")
ax2 = ax.twinx()
ax2.plot(x + 0.19, exec_rate, "o-", color="#c0392b", lw=2, label="执行可运行率 %")
for xi, v in zip(x - 0.19, e2e):
    ax.text(xi, v + 12, f"{v:.0f}s", ha="center", fontsize=10)
for xi, v in zip(x + 0.19, exec_rate):
    ax2.text(xi, v + 2.0, f"{v:.0f}%", ha="center", fontsize=10, color="#c0392b")
ax.set_xticks(x); ax.set_xticklabels(LABELS, fontsize=9)
ax.set_ylabel("端到端秒 / 每个真成功"); ax2.set_ylabel("环内执行可运行率 %", color="#c0392b")
ax.set_ylim(0, 900); ax2.set_ylim(0, 100)
ax.set_title("(c) 效率:每真成功成本 -10%;可运行率 guard 修复", fontsize=11)
ax2.legend(fontsize=8.5, loc="lower right")

fig.text(0.5, 0.012,
         "机制:闸门 44 次台账核查几乎不硬拦(仅 1 次 block),而是在求解前把「数据键缺失/读错」清单直接交给 LLM 重写——"
         "用便宜的快速重写换掉「求解→见证判死→再修」的昂贵循环;B 臂崩溃暂升(+69)是这一置换的副产品,guard0.3 静态规则将其压回(-79)。",
         ha="center", fontsize=9, color="#444444")
fig.tight_layout(rect=[0, 0.05, 1, 0.94])
out = ROOT / "docs" / "paper" / "figures" / "presolve_gate_focus.png"
fig.savefig(out, dpi=150)
print("saved", out)
print("\narm | solves | solve_h | succ | winf | e2e/succ | exec_rate | gate_turns")
for a, g, er in zip(ARMS, G, exec_rate):
    print(f"{a:16s} | {g['budget']['solves']:4d} | {g['budget']['solve_s']/3600:4.2f}h | "
          f"{g['rate']:4.1f}% | {g['residual'].get('witness_infeasible',0):3d} | "
          f"{g['e2e_s_per_success']:6.1f}s | {er:5.1f}% | {g['budget']['gate_turns']}")

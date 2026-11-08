#!/usr/bin/env python3
"""P24b: pre-solve gate ablation, arms A vs B only (no guard).

A = witness-only feedback; B = +pre-solve gate (requirement-ledger diff).
RetailOpt-190, Qwen3_8-27B, thinking on, max 3 rounds, shared round-1 pilot.
Data: work/supp_compare/supp_tables.json.
Output: docs/paper/figures/presolve_gate_AB_only.png
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
ARMS = ["A witness-only", "B +gate"]
LABELS = ["A 仅事后见证\n(无预求解闸门)", "B +预求解闸门\n(台账 diff)"]
G = [d["gate_arms"][a] for a in ARMS]

solves = [g["budget"]["solves"] for g in G]
solve_h = [g["budget"]["solve_s"] / 3600 for g in G]
succ = [g["rate"] for g in G]
nsucc = [g["success"] for g in G]
e2e = [g["e2e_s_per_success"] for g in G]
crashes = [g["loop_crashes"] for g in G]
exec_rate = [s / (s + c) * 100 for s, c in zip(solves, crashes)]
winf = [g["residual"].get("witness_infeasible", 0) for g in G]

C = ["#8fa8bf", "#2f6db3"]
fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.9))
fig.suptitle("预求解闸门消融(仅 A vs B):RetailOpt-190 · Qwen3.8-27B · thinking 开 · 最多 3 轮修复(共享第 1 轮)",
             fontsize=12.5)
x = np.arange(2)
w = 0.36

# (a) solve budget
ax = axes[0]
ax.bar(x - 0.19, solves, width=w, color=C, label="求解器调用次数")
ax2 = ax.twinx()
ax2.bar(x + 0.19, solve_h, width=w, color="#e0a458", label="求解器墙钟(小时)")
for xi, v in zip(x - 0.19, solves):
    ax.text(xi, v + 4, str(v), ha="center", fontsize=11)
for xi, v in zip(x + 0.19, solve_h):
    ax2.text(xi, v + 0.1, f"{v:.2f}h", ha="center", fontsize=11)
ax.set_xticks(x)
ax.set_xticklabels(LABELS, fontsize=10)
ax.set_ylabel("环内求解器调用次数")
ax2.set_ylabel("环内求解器墙钟(小时)", color="#b07818")
ax.set_ylim(0, 300)
ax2.set_ylim(0, 6.0)
ax.set_title("(a) 求解预算\n调用 -26.1% · 求解时间 -16.4%", fontsize=11)

# (b) quality
ax = axes[1]
ax.bar(x - 0.19, succ, width=w, color=C, label="真成功率 %(见证+目标值双判)")
ax.bar(x + 0.19, winf, width=w, color="#c0392b", alpha=0.75,
       label="残留:见证判不可行(/190)")
for xi, v, n in zip(x - 0.19, succ, nsucc):
    ax.text(xi, v + 1.5, f"{v:.1f}%\n({n}/190)", ha="center", fontsize=10)
for xi, v in zip(x + 0.19, winf):
    ax.text(xi, v + 1.5, str(v), ha="center", fontsize=11)
ax.axhline(6.8, color="#888888", ls="--", lw=1)
ax.text(-0.45, 9.8, "无修复环 pass@1 = 6.8%", fontsize=8.5, color="#666666")
ax.set_xticks(x)
ax.set_xticklabels(LABELS, fontsize=10)
ax.set_ylabel("% / 细胞数")
ax.set_ylim(0, 95)
ax.set_title("(b) 质量\n真成功 +1.6pp · 语义卡死 -33%(75→50)", fontsize=11)
ax.legend(fontsize=8.5, loc="upper right")

# (c) efficiency
ax = axes[2]
ax.bar(x - 0.19, e2e, width=w, color=C, label="每真成功端到端秒")
ax2 = ax.twinx()
ax2.plot(x + 0.19, exec_rate, "o-", color="#c0392b", lw=2, ms=7,
         label="环内执行可运行率 %")
for xi, v in zip(x - 0.19, e2e):
    ax.text(xi, v + 14, f"{v:.0f}s", ha="center", fontsize=11)
for xi, v in zip(x + 0.19, exec_rate):
    ax2.text(xi, v + 2.5, f"{v:.0f}%", ha="center", fontsize=11, color="#c0392b")
ax.set_xticks(x)
ax.set_xticklabels(LABELS, fontsize=10)
ax.set_ylabel("端到端秒 / 每个真成功")
ax2.set_ylabel("环内执行可运行率 %", color="#c0392b")
ax.set_ylim(0, 920)
ax2.set_ylim(0, 100)
ax.set_title("(c) 效率\n每真成功成本 -10.1%(776→698s)", fontsize=11)
ax2.legend(fontsize=8.5, loc="lower left")

fig.text(0.5, 0.012,
         "机制:44 次台账核查仅 1 次硬拦——闸门在求解前把「数据键缺失/读错」清单交给模型重写,"
         "用便宜的快速重写换掉「求解→见证判死→再修」的昂贵循环。",
         ha="center", fontsize=9, color="#444444")
fig.tight_layout(rect=[0, 0.05, 1, 0.93])
out = ROOT / "docs" / "paper" / "figures" / "presolve_gate_AB_only.png"
fig.savefig(out, dpi=150)
print("saved", out)

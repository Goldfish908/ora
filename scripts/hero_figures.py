#!/usr/bin/env python3
"""Hero figures for third-party presentation (2026-11-06).

1. hero_phantom_funnel.png — the motivation hook: naive "ran + objective looks
   right" protocol overestimates success 4.7x on RetailOpt-190 (on mode).
   Data: motivation_findings_v0.1.md / E2 main table (frozen numbers).
2. hero_judge_comparison.png — judge line: off-the-shelf judges collapse on
   phantom cells; domain-trained judge (v3 LoRA) recovers discrimination.
   (a) phantom false-clear rate on the SAME 316 witness-labeled cells
       (P0 Qwen27B zero-shot vs Open-Jev-27B off-the-shelf);
   (b) AUC: Open-Jev on RetailOpt-316 / IndustryOR-240 vs judge-v3 epochs
       on dev70 (NOTE: different eval set, dev70 includes synthetic mutations;
       paired re-eval is pending).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
from matplotlib.patches import FancyArrowPatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs" / "paper" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

# ---------- figure 1: phantom funnel ----------
stages = [
    ("输入题目", 190, "#95a5a6"),
    ("代码跑通\n(exec ok)", 69, "#7fb3d5"),
    ("目标值看似合理\n(传统评测在此停止)", 61, "#f0b27a"),
    ("通过确定性语义审计\n(witness)", 15, "#85c1e9"),
    ("真成功\n(审计通过 + 目标值正确)", 13, "#2471a3"),
]
fig, ax = plt.subplots(figsize=(11, 5.2))
y = list(range(len(stages)))[::-1]
for (lab, v, c), yi in zip(stages, y):
    ax.barh(yi, v, color=c, height=0.62)
    ax.text(v + 3, yi, f"{v}  ({v/190*100:.1f}%)", va="center", fontsize=11)
    ax.text(-4, yi, lab, va="center", ha="right", fontsize=11)
# phantom band between stage 2 and 3
ax.annotate("", xy=(61, y[3] + 0.55), xytext=(61, y[2] - 0.55),
            arrowprops=dict(arrowstyle="-[, widthB=1.2", color="#c0392b", lw=1.6))
ax.text(66, (y[2] + y[3]) / 2, "幻影 46 题 (75%):\n能跑、目标值好看、\n但解违反题面语义",
        fontsize=11, color="#c0392b", va="center")
ax.text(120, y[1], '传统口径会报告 32.1% (61/190)\n真实只有 6.8% (13/190)\n→ 高估 4.7 倍',
        fontsize=12, color="#c0392b", va="center",
        bbox=dict(boxstyle="round,pad=0.5", fc="#fdedec", ec="#c0392b"))
ax.set_xlim(0, 210)
ax.set_ylim(-0.6, len(stages) - 0.4)
ax.set_yticks([])
ax.set_xlabel("细胞数(n = 190 题, Qwen3.8-27B 单发, thinking on)", fontsize=11)
ax.set_title("测量纪律:为什么需要独立语义审计 —— RetailOpt-190 幻影漏斗", fontsize=13)
ax.spines[["top", "right", "left"]].set_visible(False)
fig.tight_layout()
fig.savefig(FIG / "hero_phantom_funnel.png", dpi=150)
print("saved", FIG / "hero_phantom_funnel.png")

# ---------- figure 2: judge comparison ----------
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.8))

# (a) phantom false-clear rate on the same 316 cells
judges = ["Qwen27B 零样本判官\n(P0 替身)", "Open-Jev-27B\n现成权重"]
fc = [45.3, 99.6]
bars = ax1.bar(judges, fc, color=["#5d6d7e", "#c0392b"], width=0.5)
for b, v in zip(bars, fc):
    ax1.text(b.get_x() + b.get_width() / 2, v + 2, f"{v}%", ha="center", fontsize=12)
ax1.axhline(5, color="#52be80", ls="--", lw=1.2)
ax1.text(1.28, 7, "witness 级可用线 <5%", color="#1e8449", fontsize=9, ha="right")
ax1.set_ylabel("幻影误放行率 %(越低越好)", fontsize=11)
ax1.set_ylim(0, 112)
ax1.set_title("(a) 同一批 316 个 witness 标注细胞:\n现成判官几乎全放行幻影", fontsize=11)

# (b) AUC
names = ["Open-Jev\nRetailOpt-316", "Open-Jev\nIndustryOR-240",
         "自训判官 v3\nep1 (dev70†)", "自训判官 v3\nep2 (dev70†)"]
aucs = [0.534, 0.662, 0.682, 0.808]
cols = ["#c0392b", "#c0392b", "#48c9b0", "#16a085"]
bars = ax2.bar(names, aucs, color=cols, width=0.55)
for b, v in zip(bars, aucs):
    ax2.text(b.get_x() + b.get_width() / 2, v + 0.012, f"{v:.3f}", ha="center", fontsize=11)
ax2.axhline(0.5, color="gray", ls=":", lw=1)
ax2.text(3.4, 0.505, "随机", fontsize=9, color="gray", ha="right")
ax2.set_ylabel("AUC(错误/正确可分性)", fontsize=11)
ax2.set_ylim(0.4, 0.9)
ax2.set_title("(b) 判官必须训练于本域:\n现成 System-One ≈ 随机,自训 2 epoch 到 0.81", fontsize=11)
ax2.tick_params(axis="x", labelsize=9)
fig.text(0.5, -0.02, "† dev70 与 316 细胞集不同(含合成变异样本),配对复测待判官 v3 终评补齐",
         ha="center", fontsize=8.5, color="gray")
fig.suptitle("判官路线校准:RetailOpt / IndustryOR 实测", fontsize=12.5)
fig.tight_layout()
fig.savefig(FIG / "hero_judge_comparison.png", dpi=150, bbox_inches="tight")
print("saved", FIG / "hero_judge_comparison.png")

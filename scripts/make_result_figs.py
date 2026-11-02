#!/usr/bin/env python3
"""Generate presentation figures for the pre-solve verifier results (F10-F14).

Output: docs/paper/figs/f14_summary.png (2x3 panel) + f14_headline.png.
Run: /home/hewj13/planbb/miniforge3/envs/rl/bin/python scripts/make_result_figs.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "paper" / "figs"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams["font.family"] = "WenQuanYi Zen Hei"
plt.rcParams["axes.unicode_minus"] = False

C_A = "#8c8c8c"   # arm A grey
C_B = "#2c7fb0"   # arm B blue
C_ACC = "#d95f02" # accent orange


def panel_success(ax):
    stages = ["零样本\n(F10)", "事后反馈环\nA 臂 (F12)", "+预求解闸门\nB 臂 (F14)"]
    vals = [13 / 190, 84 / 190, 87 / 190]
    bars = ax.bar(stages, [v * 100 for v in vals],
                  color=["#c7c7c7", C_A, C_B], width=0.55)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v * 100 + 1,
                f"{v*100:.1f}%", ha="center", fontsize=11, fontweight="bold")
    ax.set_ylabel("真成功率 (%)")
    ax.set_ylim(0, 55)
    ax.set_title("① 真成功率：三阶段演进 (n=190)", fontsize=12)


def panel_flips(ax):
    bars = ax.bar(["B 独有成功", "A 独有成功"], [14, 11],
                  color=[C_B, C_A], width=0.45)
    for b, v in zip(bars, [14, 11]):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.3, str(v),
                ha="center", fontsize=12, fontweight="bold")
    ax.set_ylabel("配对翻转 cell 数")
    ax.set_ylim(0, 17)
    ax.set_title("② 配对翻转 (+14/-11)\nB 独有中 12/14 由闸门反馈触发", fontsize=12)


def panel_budget(ax):
    cats = ["实际求解调用\n(次)", "执行墙钟\n(百秒)", "LLM 修复耗时\n(百秒)"]
    a = [249, 173.7, 190.0]
    b = [184, 145.5, 173.8]
    x = range(len(cats))
    w = 0.35
    ax.bar([i - w / 2 for i in x], a, w, label="A 臂", color=C_A)
    ax.bar([i + w / 2 for i in x], b, w, label="B 臂", color=C_B)
    for i in x:
        ax.text(i - w / 2, a[i] + 4, str(a[i]), ha="center", fontsize=9)
        ax.text(i + w / 2, b[i] + 4, str(b[i]), ha="center", fontsize=9,
                fontweight="bold")
    ax.text(0, 290, "-26.1%", ha="center", color=C_ACC, fontsize=11,
            fontweight="bold")
    ax.text(1, 290, "-16.3%", ha="center", color=C_ACC, fontsize=11,
            fontweight="bold")
    ax.set_xticks(list(x))
    ax.set_xticklabels(cats, fontsize=9)
    ax.set_ylim(0, 320)
    ax.legend(fontsize=9)
    ax.set_title("③ 预算对比 (环内, 177 cell)\n闸门核查另花 61.9 百秒", fontsize=12)


def panel_residual(ax):
    cats = ["witness\n不可行", "代码\n崩溃", "次优", "时限无解", "自报\n不可行"]
    a = [75, 18, 6, 6, 1]
    b = [50, 37, 3, 12, 1]
    x = range(len(cats))
    w = 0.35
    ax.bar([i - w / 2 for i in x], a, w, label="A 臂", color=C_A)
    ax.bar([i + w / 2 for i in x], b, w, label="B 臂", color=C_B)
    for i in x:
        ax.text(i - w / 2, a[i] + 1.5, str(a[i]), ha="center", fontsize=9)
        ax.text(i + w / 2, b[i] + 1.5, str(b[i]), ha="center", fontsize=9,
                fontweight="bold")
    ax.annotate("-33%", xy=(0, 56), ha="center", color=C_ACC,
                fontsize=11, fontweight="bold")
    ax.set_xticks(list(x))
    ax.set_xticklabels(cats, fontsize=9)
    ax.set_ylabel("残余失败 cell 数")
    ax.set_ylim(0, 88)
    ax.legend(fontsize=9)
    ax.set_title("④ 残余错误结构：语义层 -33%\n瓶颈转向代码健壮性", fontsize=12)


def panel_offline(ax):
    cats = ["幻影召回\non 模式", "幻影召回\noff 模式", "成功样本\n通过率"]
    vals = [87.5, 100.0, 84.6]
    bars = ax.bar(cats, vals, color=[C_B, C_B, C_ACC], width=0.5)
    for b_, v in zip(bars, vals):
        ax.text(b_.get_x() + b_.get_width() / 2, v + 2, f"{v}%",
                ha="center", fontsize=11, fontweight="bold")
    ax.axhline(90, ls="--", c="red", lw=1)
    ax.text(2.45, 91, "过闸门槛 90%", fontsize=8, color="red", ha="right")
    ax.set_ylabel("%")
    ax.set_ylim(0, 118)
    ax.set_title("⑤ 离线评测 (F13, 380 cell)\n通过 fail-open 放行", fontsize=12)


def panel_convention(ax):
    cats = ["C-INIT\n(库存初始化)", "C-DEMAND\n(需求满足)"]
    post = [14, 3]   # 事后 witness 反馈修复率
    pre = [99, 89]   # 事前闸门捕获率
    x = range(len(cats))
    w = 0.35
    ax.bar([i - w / 2 for i in x], post, w, label="事后反馈修复率 (F12)",
           color=C_A)
    ax.bar([i + w / 2 for i in x], pre, w, label="事前闸门捕获率 (F13)",
           color=C_B)
    for i in x:
        ax.text(i - w / 2, post[i] + 2, f"{post[i]}%", ha="center", fontsize=10)
        ax.text(i + w / 2, pre[i] + 2, f"{pre[i]}%", ha="center", fontsize=10,
                fontweight="bold")
    ax.set_xticks(list(x))
    ax.set_xticklabels(cats, fontsize=9)
    ax.set_ylabel("%")
    ax.set_ylim(0, 118)
    ax.legend(fontsize=9, loc="upper right")
    ax.set_title("⑥ 隐藏约定的不对称性\n事后教不会 ≠ 事前拦不住", fontsize=12)


fig, axes = plt.subplots(2, 3, figsize=(16, 8.5))
for ax, fn in zip(axes.flat, [panel_success, panel_flips, panel_budget,
                              panel_residual, panel_offline, panel_convention]):
    fn(ax)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

fig.suptitle("预求解验证器：对照实验总览 (RetailOpt-190 × Qwen3_8-27B, on 模式)",
             fontsize=14, fontweight="bold")
fig.tight_layout(rect=[0, 0, 1, 0.95])
fig.savefig(OUT / "f14_summary.png", dpi=160)
print("wrote", OUT / "f14_summary.png")

# headline single figure: success evolution + key numbers
fig2, ax = plt.subplots(figsize=(7.5, 4.5))
panel_success(ax)
ax.set_title("预求解验证器：真成功率演进\nRetailOpt-190 × Qwen3_8-27B (on 模式, n=190)",
             fontsize=12)
fig2.tight_layout()
fig2.savefig(OUT / "f14_headline.png", dpi=160)
print("wrote", OUT / "f14_headline.png")

#!/usr/bin/env python3
"""Hero figure: memory self-evolution made visible (2026-11-06).

Three panels:
(a) the self-evolution loop schematic: failure ledger -> attribution ->
    distilled rule/card -> offline validation (false-alarm gate) -> library ->
    next batch (non-parametric; weights never touched);
(b) guard rulebook detection rate on the frozen 263-crash ledger across
    generations v0.1 -> v0.2 -> +G6 -> v0.3, annotated with what each
    generation added (data: crash_guard_mining_v0.1.md);
(c) playbook rescue rate on 507 mutation cells, per mutation class,
    baseline vs with-card (data: p2_repair_playbook_v1.0.md addendum).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs" / "paper" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

fig = plt.figure(figsize=(14.5, 7.6))
gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.5], hspace=0.32, wspace=0.25)

# ---------- (a) loop schematic ----------
axa = fig.add_subplot(gs[0, :])
axa.set_xlim(0, 10); axa.set_ylim(0, 2.2); axa.axis("off")
axa.set_title("(a) memory 自进化循环:每一代都是一次完整的「失败 → 知识」转化(非参数,权重不动)",
              fontsize=12, loc="left")
boxes = [
    (0.2, "跑批失败台账\n263 条崩溃", "#f5b7b1"),
    (2.2, "归因聚类\n(同构失败归一族)", "#f9e797"),
    (4.2, "蒸馏规则/卡片\nG0–G8 · 修复剧本", "#abebc6"),
    (6.2, "离线验证门槛\n误报 1.9%/0% 才入库", "#aed6f1"),
    (8.2, "规则库/记忆\n注入生成与回路", "#d2b4de"),
]
for x, txt, c in boxes:
    axa.add_patch(FancyBboxPatch((x, 0.7), 1.6, 1.0, boxstyle="round,pad=0.08",
                                 fc=c, ec="#566573", lw=1.2))
    axa.text(x + 0.8, 1.2, txt, ha="center", va="center", fontsize=10)
for i in range(len(boxes) - 1):
    axa.add_patch(FancyArrowPatch((boxes[i][0] + 1.72, 1.2), (boxes[i + 1][0] - 0.12, 1.2),
                                  arrowstyle="-|>", mutation_scale=16, color="#566573", lw=1.4))
# feedback arrow from last box back to first (next batch)
axa.add_patch(FancyArrowPatch((9.0, 0.62), (1.0, 0.30),
                              arrowstyle="-|>", mutation_scale=16, color="#566573",
                              lw=1.4, connectionstyle="arc3,rad=0.15"))
axa.text(5.0, 0.02, "下一批失败(跨题、跨族积累,只进不出)", ha="center", fontsize=9.5, color="#566573")

# ---------- (b) guard rulebook evolution ----------
axb = fig.add_subplot(gs[1, 0])
gens = ["v0.1\nG0–G5 初版", "v0.2\n+G2 数据流", "+G6\ndata=None 遮蔽", "v0.3\n+G7/G8/G4 等"]
det = [73.8, 91.6, 93.9, 97.0]
ns = ["194/263", "241/263", "247/263", "255/263"]
axb.plot(range(4), det, "o-", color="#2471a3", lw=2, markersize=7)
for i, (v, n) in enumerate(zip(det, ns)):
    axb.text(i, v + 1.5, f"{v}%", ha="center", fontsize=11, color="#2471a3")
    axb.text(i, v - 4.5, n, ha="center", fontsize=8.5, color="gray")
axb.axhline(73.8, color="gray", ls=":", lw=0.8)
axb.set_xticks(range(4))
axb.set_xticklabels(gens, fontsize=9)
axb.set_ylabel("历史崩溃检出率 %", fontsize=10.5)
axb.set_ylim(60, 104)
axb.set_title("(b) 检出率逐代进化(冻结的 263 条崩溃台账)\n每代新增规则 = 一次失败归因的沉淀",
              fontsize=11)
axb.annotate("误报全程恒定:\n幻影 1.9% / 成功样本 0%", xy=(0.35, 66), fontsize=9,
             color="#1e8449", bbox=dict(boxstyle="round,pad=0.35", fc="#eafaf1", ec="#1e8449"))

# ---------- (c) playbook rescue by mutation class ----------
axc = fig.add_subplot(gs[1, 1])
classes = ["幻影库存\n(200)", "错常数\n(140)", "删约束\n(167)", "合计\n(507)"]
base = [24.5, 73.6, 61.7, 50.3]
card = [95.5, 97.1, 79.0, 90.5]
x = range(4)
w = 0.36
b1 = axc.bar([xi - w / 2 for xi in x], base, width=w, color="#b2babb", label="无卡片(基线修复环)")
b2 = axc.bar([xi + w / 2 for xi in x], card, width=w, color="#48c9b0", label="按类配修复卡片")
for xi, v in zip(x, base):
    axc.text(xi - w / 2, v + 2, f"{v:.1f}", ha="center", fontsize=9.5)
for xi, v in zip(x, card):
    axc.text(xi + w / 2, v + 2, f"{v:.1f}", ha="center", fontsize=9.5)
axc.set_xticks(list(x))
axc.set_xticklabels(classes, fontsize=9.5)
axc.set_ylabel("修复成功率 %", fontsize=10.5)
axc.set_ylim(0, 112)
axc.legend(fontsize=9, loc="lower right")
axc.set_title("(c) 修复剧本的兑现:507 个变异细胞营救\n50.3% → 90.5%(删约束类是已知短板,需细分卡)",
              fontsize=11)

fig.suptitle("memory 如何自进化:从失败台账到可验证的规则与剧本(RetailOpt, Qwen3.8-27B)",
             fontsize=13.5)
fig.tight_layout()
out = FIG / "hero_memory_selfevolution.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print("saved", out)

#!/usr/bin/env python3
"""P23: channel complementarity figure (UpSet-style, wrong-cell captures only).

Panel (a) F5-F8 34 wrong cells: 主动判官v4 / 零样本直判 / 静态摘要v3
Panel (b) IndustryOR 61 wrong cells: 零样本直判 / 主动·重推导 / 主动·插桩

Each bar = cells captured by exactly that channel combination (exclusive
signature). Message: complementarity scales with domain unfamiliarity.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

ROOT = Path(__file__).resolve().parent.parent
JD = ROOT / "work" / "judge_data"
plt.rcParams["font.family"] = "WenQuanYi Zen Hei"
plt.rcParams["axes.unicode_minus"] = False


def load_verdicts(fname):
    out = {}
    for l in (JD / fname).read_text().splitlines():
        r = json.loads(l)
        out[r["key"].split("|")[0]] = r.get("verdict") == "INVALID"
    return out


def signatures(cells, maps):
    sig = Counter()
    for cl in cells:
        k = cl["key"].split("|")[0]
        s = tuple(1 if m.get(k) else 0 for m in maps)
        sig[s] += 1
    return sig


def panel(ax, sig, names, title, total):
    # all combos sorted: singles first, then pairs, then triple
    combos = [c for c in sig if any(c) ]
    combos.sort(key=lambda c: (sum(c), c))
    xs = list(range(len(combos)))
    vals = [sig[c] for c in combos]
    colors = []
    base = [(0.22, 0.47, 0.72), (0.89, 0.47, 0.20), (0.30, 0.69, 0.44)]
    for c in combos:
        idx = [i for i, b in enumerate(c) if b]
        col = tuple(sum(base[i][k] for i in idx) / len(idx) for k in range(3))
        colors.append(col)
    ax.bar(xs, vals, color=colors, width=0.62)
    for x, v in zip(xs, vals):
        ax.text(x, v + 0.15, str(v), ha="center", fontsize=11)
    # channel dot matrix below
    for x, c in zip(xs, combos):
        for i, b in enumerate(c):
            y = -1.1 - i * 0.85
            if b:
                ax.add_patch(Circle((x, y), 0.16, color=base[i], clip_on=False,
                                    transform=ax.transData))
            else:
                ax.add_patch(Circle((x, y), 0.16, facecolor="white",
                                    edgecolor="#bbbbbb", lw=1.0, clip_on=False))
        on = [i for i, b in enumerate(c) if b]
        if len(on) > 1:
            ax.plot([x, x], [-1.1 - on[0] * 0.85, -1.1 - on[-1] * 0.85],
                    color="#555555", lw=1.4, zorder=0)
    for i, n in enumerate(names):
        ax.text(-0.62, -1.1 - i * 0.85, n, ha="right", va="center", fontsize=10)
    det = sum(sig[c] for c in sig if any(c))
    ax.set_title(f"{title}\n(并集检出 {det}/{total} = {det/total:.0%},"
                 f" 独有捕获 {sum(sig[c] for c in sig if sum(c)==1)}/{det})",
                 fontsize=12)
    ax.set_xticks(xs)
    ax.set_xticklabels([""] * len(combos))
    ax.set_ylim(0, max(vals) * 1.22)
    ax.set_ylabel("该组合独有捕获的错误细胞数", fontsize=10)
    ax.set_xlim(-2.2 if len(names[0]) > 4 else -1.2, len(combos) - 0.4)
    ax.spines[["top", "right"]].set_visible(False)


def main():
    # F5-F8
    v4 = load_verdicts("active_f5f8_v4.jsonl")
    dz = load_verdicts("zeroshot_f5f8.jsonl")
    sv3 = load_verdicts("gen_eval_f5f8.jsonl")
    cells_f = [json.loads(l) for l in (JD / "eval_f5f8.jsonl").read_text().splitlines()]
    wrong_f = [c for c in cells_f if c["wrong"]]
    sig_f = signatures(wrong_f, (v4, dz, sv3))

    # IndustryOR
    u = json.loads((JD / "p22_union_ior.json").read_text())
    wrong_i = [r for r in u if r["wrong"]]
    sig_i = Counter()
    for r in wrong_f if False else wrong_i:
        sig_i[(1 if r["D_direct"] else 0, 1 if r["R_rederive"] else 0,
               1 if r["I_instr"] else 0)] += 1

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.2, 5.4))
    fig.suptitle("感知通道互补性:各通道组合独有捕获的错误细胞(UpSet 视图)",
                 fontsize=14)
    panel(a1, sig_f, ["主动判官v4", "零样本直判", "静态摘要v3"],
          "(a) F5–F8 留出族(RetailOpt 宇宙内,34 错)", len(wrong_f))
    panel(a2, sig_i, ["零样本直判", "主动·重推导", "主动·插桩"],
          "(b) IndustryOR(未见域零迭代,61 错)", len(wrong_i))
    fig.text(0.5, 0.015,
             "读法:实心点=该通道参与;连线=多通道共同捕获。单点柱越高=通道视野越不重叠。"
             "族内(a)主动判官吸收了其它通道视野(独有 9/16);"
             "未见域(b)55% 的捕获只属于单一通道——集成价值随域陌生度上升。",
             ha="center", fontsize=9.5, color="#444444")
    fig.tight_layout(rect=[0, 0.06, 1, 0.94])
    out = ROOT / "docs" / "paper" / "figs" / "channel_complementarity.png"
    fig.savefig(out, dpi=150)
    print("saved", out)


if __name__ == "__main__":
    main()

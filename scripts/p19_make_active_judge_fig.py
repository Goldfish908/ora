#!/usr/bin/env python3
"""P19: active-perception judge comparison figure (two panels).

(a) F5-F8 48 cells: static-summary judge v3 vs zero-shot direct vs
    active judge v1-v4 (zero-shot) vs distilled v4 epochs (when fetched).
(b) IndustryOR: zero-shot direct vs active rederive vs active instrumented
    vs trained v3 (when fetched) vs distilled v4 best epoch (when fetched).

Each arm shows detection rate (bar) and FP rate (red diamond marker).
Missing files are skipped so the script can run before/after remote fetch.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parent.parent
JD = ROOT / "work" / "judge_data"
FIG = ROOT / "docs" / "paper" / "figs"


def metrics(rows):
    tp = sum(1 for r in rows if r["wrong"] and r.get("verdict") == "INVALID")
    fn = sum(1 for r in rows if r["wrong"] and r.get("verdict") != "INVALID")
    fp = sum(1 for r in rows if not r["wrong"] and r.get("verdict") == "INVALID")
    tn = sum(1 for r in rows if not r["wrong"] and r.get("verdict") != "INVALID")
    return tp / max(tp + fn, 1), fp / max(fp + tn, 1), len(rows)


def load(name):
    p = JD / name
    if not p.exists():
        return None
    return [json.loads(l) for l in p.read_text().splitlines()]


def panel(ax, arms, title):
    """arms: list of (label, rows_or_None)."""
    arms = [(lb, rows) for lb, rows in arms if rows]
    labels = [lb for lb, _ in arms]
    det, fpr, ns = zip(*[metrics(rows) for _, rows in arms])
    x = np.arange(len(labels))
    colors = ["#5d6d7e" if ("静态摘要" in lb or "直判" in lb) else "#2e86c1"
              for lb in labels]
    bars = ax.bar(x, [d * 100 for d in det], color=colors, width=0.62)
    for xi, b, d, n in zip(x, bars, det, ns):
        ax.text(xi, b.get_height() + 1.2, f"{d*100:.1f}%\n(n={n})",
                ha="center", fontsize=8.5)
    ax.scatter(x, [f * 100 for f in fpr], marker="D", color="#c0392b",
               zorder=5, s=42, label="误报率(菱形)")
    for xi, f in zip(x, fpr):
        ax.annotate(f"{f*100:.1f}", (xi + 0.16, f * 100 + 0.6), fontsize=8,
                    color="#c0392b", zorder=6,
                    bbox=dict(boxstyle="round,pad=0.12", fc="white",
                              ec="none", alpha=0.75))
    ax.axhline(10, ls="--", lw=1, color="#c0392b", alpha=0.5)
    ax.text(len(labels) - 0.4, 10.6, "误报阈值 10%", fontsize=8,
            color="#c0392b", ha="right")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("检出率 % (柱) / 误报率 % (菱形)", fontsize=9.5)
    ax.set_ylim(0, max(62, max(det) * 115))
    ax.set_title(title, fontsize=11)
    ax.legend(fontsize=8, loc="upper right")


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    fig, (axa, axb) = plt.subplots(1, 2, figsize=(15, 5.2))

    panel(axa, [
        ("静态摘要判官 v3\n(已训练)", load("gen_eval_f5f8.jsonl")),
        ("零样本直判", load("zeroshot_f5f8.jsonl")),
        ("主动判官 v1", load("active_f5f8.jsonl")),
        ("主动判官 v2", load("active_f5f8_v2.jsonl")),
        ("主动判官 v3", load("active_f5f8_v3.jsonl")),
        ("主动判官 v4\n(零样本)", load("active_f5f8_v4.jsonl")),
        ("蒸馏 v4 ep1", load("v4_eval_f5f8_ep1.jsonl")),
        ("蒸馏 v4 ep2", load("v4_eval_f5f8_ep2.jsonl")),
        ("蒸馏 v4 ep3", load("v4_eval_f5f8_ep3.jsonl")),
    ], "(a) F5–F8 48 细胞(RetailOpt 宇宙内跨族)")

    panel(axb, [
        ("零样本直判", load("zeroshot_industryor.jsonl")),
        ("主动·重推导", load("active_industryor.jsonl")),
        ("主动·插桩", load("active_ior2.jsonl")),
        ("静态摘要判官 v3\n(已训练)", load("gen_eval_industryor.jsonl")),
        ("蒸馏 v4\n(最优epoch)", load("v4_eval_ior.jsonl")),
    ], "(b) IndustryOR(零迭代终验集)")

    fig.suptitle("主动感知判官:架构验证与蒸馏迁移(检出率越高越好,误报率越低越好)",
                 fontsize=12.5)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out = FIG / "active_judge_comparison.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print("saved", out)


if __name__ == "__main__":
    main()

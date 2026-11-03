#!/usr/bin/env python3
"""Evolution gen0-3 figure -> docs/figs/evo_gen0123_v0.1.png

Reads evo/ledger.jsonl (kinds: dev40, gapcheck60, full190) and renders:
  Panel A: dev40 fitness of every genome per generation (jittered dots,
           champion circled), with the in-batch g0_seed reference line.
  Panel B: per-generation champion dev40 vs gapcheck60 (overfit gap).
Re-run after each generation; the figure extends itself as the ledger grows.
"""
import json, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIGS = os.path.join(ROOT, "docs", "figs")
os.makedirs(FIGS, exist_ok=True)
LEDGER = os.path.join(ROOT, "evo", "ledger.jsonl")
SEED_GID = "g0_seed"


def load_records():
    recs, seen = [], set()
    with open(LEDGER) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            key = (r.get("kind"), r.get("gen"), r.get("gid"))
            if key in seen:      # keep first, matching ledger_fitness
                continue
            seen.add(key)
            recs.append(r)
    return recs


def pct(r):
    return 100.0 * r["success"] / r["n"] if r.get("n") else None


def main():
    recs = load_records()
    dev40 = {(r["gen"], r["gid"]): r for r in recs if r.get("kind") == "dev40"}
    gap60 = {(r["gen"], r["gid"]): r for r in recs
             if r.get("kind") == "gapcheck60"}
    gens = sorted({g for g, _ in dev40})
    champs = {}  # gen -> (gid, gap_record); gap60 rows exist only for champions
    for (g, gid), r in sorted(gap60.items()):
        champs.setdefault(g, (gid, r))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

    # --- Panel A: all genomes per generation
    seed_pct = pct(dev40[(0, SEED_GID)]) if (0, SEED_GID) in dev40 else None
    for g in gens:
        rows = [(gid, pct(r)) for (gg, gid), r in dev40.items() if gg == g]
        xs = np.full(len(rows), g) + np.linspace(-0.22, 0.22, len(rows))
        ys = [v for _, v in rows]
        ax1.scatter(xs, ys, s=42, color="#4C72B0", zorder=3,
                    label="genome" if g == gens[0] else None)
        for (gid, v), x in zip(rows, xs):
            if g in champs and champs[g][0] == gid:
                ax1.scatter([x], [v], s=210, facecolors="none",
                            edgecolors="#C44E52", linewidths=2.2, zorder=4)
                ax1.annotate(gid.replace(SEED_GID, "seed"), (x, v),
                             textcoords="offset points", xytext=(0, 10),
                             ha="center", fontsize=7.5, color="#C44E52")
    if seed_pct is not None:
        ax1.axhline(seed_pct, ls="--", lw=1.2, color="#888888",
                    label=f"in-batch seed ({seed_pct:.1f}%)")
    ax1.set_xticks(gens)
    ax1.set_xticklabels([f"gen {g}" for g in gens])
    ax1.set_ylabel("dev40 single-shot success (%)")
    ax1.set_title("A. Fitness per genome (circle = generation champion)")
    ax1.set_ylim(0, 60)
    ax1.grid(axis="y", alpha=0.3)
    ax1.legend(fontsize=8, loc="upper right")

    # --- Panel B: champion dev40 vs gapcheck60
    cg = sorted(champs)
    if cg:
        x = np.arange(len(cg))
        d = [pct(dev40[(g, champs[g][0])]) for g in cg]
        s = [pct(champs[g][1]) for g in cg]
        w = 0.36
        ax2.bar(x - w / 2, d, w, label="dev40 (seen variants)",
                color="#4C72B0")
        ax2.bar(x + w / 2, s, w, label="gapcheck60 (held-out variants)",
                color="#DD8452")
        for xi, (dv, sv) in enumerate(zip(d, s)):
            ax2.annotate(f"{dv:.1f}", (xi - w / 2, dv), ha="center",
                         va="bottom", fontsize=8)
            ax2.annotate(f"{sv:.1f}", (xi + w / 2, sv), ha="center",
                         va="bottom", fontsize=8)
            ax2.annotate(f"gap {dv - sv:+.1f}pp", (xi, max(dv, sv) + 4),
                         ha="center", fontsize=8, color="#555555")
        ax2.set_xticks(x)
        ax2.set_xticklabels([f"gen {g}\n{champs[g][0]}" for g in cg],
                            fontsize=8)
        ax2.legend(fontsize=8)
    ax2.set_ylabel("single-shot success (%)")
    ax2.set_title("B. Champion generalization gap")
    ax2.set_ylim(0, 60)
    ax2.grid(axis="y", alpha=0.3)

    fig.suptitle("Prompt-genome evolution on RetailOpt dev40/gapcheck60 "
                 "(Qwen3.8-27B intranet)", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out = os.path.join(FIGS, "evo_gen0123_v0.1.png")
    fig.savefig(out, dpi=160)
    print("wrote", out)


if __name__ == "__main__":
    main()

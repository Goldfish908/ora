#!/usr/bin/env python3
"""Generate Round 2 result figures into docs/figs/."""
import json, os, glob
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIGS = os.path.join(ROOT, "docs", "figs")
os.makedirs(FIGS, exist_ok=True)

SHORT = {
    "airport_gate_assignment": "airport",
    "bike_share_rebalancing": "bike_share",
    "carbon_aware_compute_scheduling": "carbon",
    "cell_tower_coverage_expansion": "cell_tower",
    "circular_packaging_replenishment": "circular",
    "dynamic_supply_disruption_replan": "dynamic",
}
ORDER = ["airport_gate_assignment", "bike_share_rebalancing",
         "carbon_aware_compute_scheduling", "cell_tower_coverage_expansion",
         "circular_packaging_replenishment", "dynamic_supply_disruption_replan"]


def load_arm(arm):
    """-> {task: dict(feas, qual, status, steps, llm_s, wall_s, wcalls)}"""
    out = {}
    for d in sorted(glob.glob(os.path.join(ROOT, "runs", arm, "*__*/"))):
        task = os.path.basename(d.rstrip("/")).split("__")[0]
        rec = {"feas": None, "qual": None, "status": None, "steps": None,
               "llm_s": 0.0, "wall_s": None, "wcalls": 0}
        rp = os.path.join(d, "result.json")
        if os.path.exists(rp):
            v = (json.load(open(rp)).get("verifier_result") or {}).get("rewards") or {}
            rec["feas"] = v.get("feasibility")
            rec["qual"] = v.get("quality")
        sp = os.path.join(d, "agent", "ora", "run_summary.json")
        if os.path.exists(sp):
            s = json.load(open(sp))
            rec["status"] = s.get("status")
            rec["steps"] = s.get("n_steps")
            au = s.get("actor_usage") or {}
            wu = s.get("worker_usage") or {}
            rec["llm_s"] = (au.get("latency_s") or 0) + (wu.get("latency_s") or 0)
            rec["wcalls"] = wu.get("calls") or 0
            t0, t1 = s.get("ts_started"), s.get("ts_updated")
            if t0 and t1:
                from datetime import datetime
                rec["wall_s"] = (datetime.fromisoformat(t1) - datetime.fromisoformat(t0)).total_seconds()
        out[task] = rec
    return out


def fig_b0_vs_b2():
    b0, b2 = load_arm("b0_round2"), load_arm("b2_round2")
    tasks = [t for t in ORDER if t in b0 or t in b2]
    x = np.arange(len(tasks)); w = 0.36
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=False)
    for ax, key, title in [(axes[0], "feas", "Feasibility"), (axes[1], "qual", "Quality")]:
        for i, (arm, dd, c) in enumerate([("B0 (actor only)", b0, "#8da0cb"),
                                          ("B2 (+audit/repair workers)", b2, "#66c2a5")]):
            vals, labels = [], []
            for t in tasks:
                r = dd.get(t, {})
                v = r.get(key)
                if v is None:
                    vals.append(0); labels.append("n/a")
                else:
                    vals.append(v if key == "feas" else (v or 0)); labels.append("")
            bars = ax.bar(x + (i - 0.5) * w, vals, w, label=arm, color=c)
            for xi, (lab, v) in enumerate(zip(labels, vals)):
                if lab == "n/a":
                    ax.text(xi + (i - 0.5) * w, 0.02, "n/a", ha="center", fontsize=8, rotation=90)
                elif key == "qual" and v > 0:
                    ax.text(xi + (i - 0.5) * w + (0.03 if i else -0.03), v + 0.008,
                            f"{v:.3f}", ha="center", fontsize=8)
        ax.set_xticks(x); ax.set_xticklabels([SHORT[t] for t in tasks], rotation=20, ha="right")
        ax.set_title(title); ax.set_ylim(0, 1.1 if key == "feas" else 0.32)
        ax.grid(axis="y", alpha=0.3)
    axes[0].legend(fontsize=9, loc="upper right")
    fig.suptitle("ORAgentBench Round 2: B0 vs B2 per-task verifier rewards", y=1.0)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "b0_vs_b2_rewards.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


def fig_controlled():
    p = os.path.join(ROOT, "runs", "controlled_eval", "summary.json")
    s = json.load(open(p))
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6))
    # detection
    ax = axes[0]
    m = s["mutants"]
    ax.bar(["full-info", "blind"], [m["detected_full"], m["detected_blind"]],
           color=["#66c2a5", "#fc8d62"])
    ax.axhline(m["n"], ls="--", c="gray", lw=1)
    ax.text(1.35, m["n"] - 0.15, f"total mutants = {m['n']}", fontsize=8)
    for i, v in enumerate([m["detected_full"], m["detected_blind"]]):
        ax.text(i, v + 0.08, f"{v}/{m['n']}", ha="center", fontsize=10)
    ax.set_ylim(0, m["n"] + 1); ax.set_title("Mutation detection (audit)")
    # repair
    ax = axes[1]
    r = s["repairs"]
    ax.bar(["succeeded", "failed"], [r["succeeded"], r["attempted"] - r["succeeded"]],
           color=["#66c2a5", "#e78ac3"])
    for i, v in enumerate([r["succeeded"], r["attempted"] - r["succeeded"]]):
        ax.text(i, v + 0.08, str(v), ha="center", fontsize=10)
    ax.set_ylim(0, r["attempted"] + 1); ax.set_title(f"Repairs (of {r['attempted']} attempted)")
    # false positives
    ax = axes[2]
    n = s["negatives"]
    ax.bar(["FP confirmed", "FP suspected", "clean"], 
           [n["false_positives_confirmed"], n["false_positives_suspected"],
            n["n"] - n["false_positives_confirmed"] - n["false_positives_suspected"]],
           color=["#e78ac3", "#ffd92f", "#66c2a5"])
    for i, v in enumerate([n["false_positives_confirmed"], n["false_positives_suspected"],
                           n["n"] - n["false_positives_confirmed"] - n["false_positives_suspected"]]):
        ax.text(i, v + 0.06, str(v), ha="center", fontsize=10)
    ax.set_ylim(0, n["n"] + 1); ax.set_title(f"Negatives / clean artifacts (n={n['n']})")
    fig.suptitle("Controlled defect set: audit & repair workers (13 artifacts, 61 LLM calls)")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "controlled_eval.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


def fig_calibration():
    buckets = [("0.00-0.33", 2, 29.0, 50.0), ("0.34-0.66", 18, 56.6, 88.9),
               ("0.67-1.00", 33, 85.5, 93.9)]
    fig, ax = plt.subplots(figsize=(6.2, 4))
    labels = [b[0] for b in buckets]
    pred = [b[2] for b in buckets]; act = [b[3] for b in buckets]; ns = [b[1] for b in buckets]
    ax.plot([0, 100], [0, 100], ls="--", c="gray", lw=1, label="perfect calibration")
    for (lab, n, p, a) in buckets:
        ax.scatter(p, a, s=60 + 18 * n, c="#66c2a5", zorder=3)
        ax.annotate(f"n={n}", (p, a), textcoords="offset points", xytext=(8, -12), fontsize=9)
    ax.plot(pred, act, c="#66c2a5", lw=1.5, zorder=2)
    ax.set_xlabel("Mean predicted success probability (%)")
    ax.set_ylabel("Actual success rate (%)")
    ax.set_xlim(15, 105); ax.set_ylim(35, 105)
    ax.set_title("Predictor calibration (53 shadow pairs, Round 1 pilot)")
    ax.grid(alpha=0.3); ax.legend(fontsize=9, loc="lower right")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "prediction_calibration.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


def fig_latency():
    arms = []
    for arm, lab in [("b0_round2", "B0"), ("b2_round2", "B2")]:
        dd = load_arm(arm)
        for t in ORDER:
            r = dd.get(t)
            if r and r.get("wall_s"):
                arms.append((f"{lab}\n{SHORT[t]}", r["wall_s"], r["llm_s"]))
    if not arms:
        return
    fig, ax = plt.subplots(figsize=(10.5, 4))
    x = np.arange(len(arms))
    wall = [a[1] for a in arms]; llm = [a[2] for a in arms]
    other = [max(w - l, 0) for w, l in zip(wall, llm)]
    ax.bar(x, llm, 0.6, label="LLM wait (actor+worker)", color="#fc8d62")
    ax.bar(x, other, 0.6, bottom=llm, label="other (env/solve/verify)", color="#8da0cb")
    for i, (w, l) in enumerate(zip(wall, llm)):
        ax.text(i, w + 30, f"{int(l/w*100)}%", ha="center", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels([a[0] for a in arms], fontsize=8)
    ax.set_ylabel("seconds"); ax.set_title("Wall-clock decomposition per trial (label = % of time in LLM wait)")
    ax.legend(fontsize=9); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "latency_breakdown.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    fig_b0_vs_b2(); fig_controlled(); fig_calibration(); fig_latency()
    print("wrote:", *sorted(os.listdir(FIGS)), sep="\n  ")

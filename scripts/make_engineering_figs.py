#!/usr/bin/env python3
"""Engineering-stage figures (taskbook v1.1 path E): B0 / E-B1 / E-B2 /
E-B1-off / E-B1-off-big comparison.

Reads verifier rewards + trajectories from the runs dirs, writes PNGs to
docs/figs/engineering/. Re-runnable: picks up whatever runs exist.

Run with the matplotlib-capable interpreter:
    ~/.venv/bin/python scripts/make_engineering_figs.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIGS = ROOT / "docs" / "figs" / "engineering"

RUNS = [
    ("B0", ROOT / "runs" / "b0_round2"),
    ("E-B1\n(worker off)", ROOT / "runs" / "engineering" / "e_b1"),
    ("E-B2\n(+triggers)", ROOT / "runs" / "engineering" / "e_b2"),
    ("E-B1-off\n(thinking off)", ROOT / "runs" / "engineering" / "e_b1_off"),
    ("E-B1-off-big\n(off, big budget)", ROOT / "runs" / "engineering" / "e_b1_off_big"),
]

TASKS = ["airport_gate_assignment", "carbon_aware_compute_scheduling",
         "bike_share_rebalancing", "cell_tower_coverage_expansion",
         "circular_packaging_replenishment",
         "dynamic_supply_disruption_replan"]
TASK_SHORT = ["airport", "carbon", "bike_share", "cell_tower",
              "circular", "dynamic"]


def load_rewards(run_dir: Path) -> dict:
    out = {}
    if not run_dir.exists():
        return out
    for f in run_dir.glob("*/verifier/reward.json"):
        task = f.parent.parent.name.split("__")[0]
        d = json.loads(f.read_text())
        out[task] = (d.get("feasibility", 0.0), d.get("quality", 0.0))
    return out


def load_latency(run_dir: Path) -> dict:
    out = {}
    if not run_dir.exists():
        return out
    for f in run_dir.glob("*/agent/ora/trajectory.jsonl"):
        task = f.parent.parent.parent.name.split("__")[0]
        lats = [json.loads(l)["latency_s"] for l in f.read_text().splitlines()
                if l.strip()
                and json.loads(l).get("event") == "llm_response"
                and "latency_s" in json.loads(l)]
        if lats:
            out[task] = sum(lats) / len(lats)
    return out


def run_is_complete(run_dir: Path) -> bool:
    rj = run_dir / "result.json"
    if not rj.exists():
        return False
    try:
        s = json.loads(rj.read_text()).get("stats", {})
    except json.JSONDecodeError:
        return False
    return s.get("n_running_trials", 1) == 0 \
        and s.get("n_pending_trials", 1) == 0


def load_final_status(run_dir: Path) -> dict:
    out = {}
    if not run_dir.exists():
        return out
    for f in run_dir.glob("*/agent/ora/trajectory.jsonl"):
        task = f.parent.parent.parent.name.split("__")[0]
        finals = [json.loads(l) for l in f.read_text().splitlines()
                  if l.strip() and json.loads(l).get("event") == "budget"
                  and json.loads(l).get("kind") == "final"]
        if finals:
            out[task] = finals[-1].get("status", "?")
        else:
            out[task] = "gated"   # e.g. dynamic killed by benchmark gate
    # tasks with no trajectory at all were stopped by the benchmark's own
    # gate (dynamic's initial_plan min_reward), not by our budgets
    for t in TASKS:
        out.setdefault(t, "gated")
    return out


def fig_scores():
    runs = [(n, load_rewards(d)) for n, d in RUNS if run_is_complete(d)]
    runs = [(n, r) for n, r in runs if r]
    x = np.arange(len(TASKS))
    w = 0.8 / len(runs)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for i, (name, rewards) in enumerate(runs):
        feas = [rewards.get(t, (0, 0))[0] for t in TASKS]
        qual = [rewards.get(t, (0, 0))[1] for t in TASKS]
        ax1.bar(x + i * w, feas, w, label=name.replace("\n", " "))
        ax2.bar(x + i * w, qual, w, label=name.replace("\n", " "))
    ax1.set_ylabel("feasibility"); ax1.set_ylim(0, 1.15)
    ax2.set_ylabel("quality"); ax2.set_ylim(0, 2.2)
    ax2.set_xticks(x + 0.4 - w / 2)
    ax2.set_xticklabels(TASK_SHORT)
    ax1.legend(fontsize=8, ncol=len(runs))
    ax1.set_title("ORAgentBench 6-task dev set: single-run scores per arm "
                  "(sampling variance NOT controlled)")
    fig.tight_layout()
    fig.savefig(FIGS / "arms_scores.png", dpi=150)
    plt.close(fig)


def fig_latency():
    on = load_latency(ROOT / "runs" / "engineering" / "e_b1")
    off = load_latency(ROOT / "runs" / "engineering" / "e_b1_off")
    offb = load_latency(ROOT / "runs" / "engineering" / "e_b1_off_big")
    tasks = [t for t in TASKS if t in on or t in off or t in offb]
    x = np.arange(len(tasks))
    w = 0.27
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for i, (name, d) in enumerate([("thinking on (E-B1)", on),
                                   ("thinking off", off),
                                   ("thinking off, big budget", offb)]):
        vals = [d.get(t, 0) for t in tasks]
        ax.bar(x + i * w, vals, w, label=name)
    ax.set_ylabel("avg LLM call latency (s)")
    ax.set_xticks(x + w)
    ax.set_xticklabels([TASK_SHORT[TASKS.index(t)] for t in tasks])
    ax.legend()
    ax.set_title("Thinking on/off: per-call latency (qwen3.8-27B via MaaS)")
    fig.tight_layout()
    fig.savefig(FIGS / "thinking_latency.png", dpi=150)
    plt.close(fig)


def fig_attribution():
    runs = [(n, d) for n, d in RUNS if run_is_complete(d)]
    cats = ["finished", "timeout/cancelled", "max_steps",
            "token_budget_exceeded", "gated", "other"]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    bottoms = np.zeros(len(runs))
    data = {c: [] for c in cats}
    for name, d in runs:
        status = load_final_status(d)
        counts = {c: 0 for c in cats}
        for t in TASKS:
            s = status.get(t, "other")
            if s == "finished":
                counts["finished"] += 1
            elif s == "error":
                counts["timeout/cancelled"] += 1
            elif s == "max_steps":
                counts["max_steps"] += 1
            elif s == "token_budget_exceeded":
                counts["token_budget_exceeded"] += 1
            elif s == "gated":
                counts["gated"] += 1
            else:
                counts["other"] += 1
        for c in cats:
            data[c].append(counts[c])
    for c in cats:
        vals = np.array(data[c])
        ax.bar([n.replace("\n", " ") for n, _ in runs], vals,
               bottom=bottoms, label=c)
        bottoms += vals
    ax.set_ylabel("# tasks (of 6)")
    ax.set_title("How each arm ended: final status attribution")
    ax.legend(fontsize=8)
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right", fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGS / "final_status_attribution.png", dpi=150)
    plt.close(fig)


def main():
    FIGS.mkdir(parents=True, exist_ok=True)
    fig_scores()
    fig_latency()
    fig_attribution()
    print("wrote:", *[str(p) for p in sorted(FIGS.glob('*.png'))], sep="\n  ")


if __name__ == "__main__":
    main()

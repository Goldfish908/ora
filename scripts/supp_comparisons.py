#!/usr/bin/env python3
"""Supplementary comparisons (2026-11-06), two parts:

Part B — memory self-evolution stages (single-shot, pass@1 population):
  baseline -> P1 (tool-knowledge priors) -> P2 (+scaffold) -> P3 (+semantic memory)
  metrics: executability, crash, solved, witness-feasible, phantom, true success,
           cost (wall_s, llm_latency_s, tokens) per cell.

Part A (pre-solve gate savings) — loop-phase budget across arms:
  A (witness-only feedback) / B (+gate) / B' (+guard v0.1) / B'' (+guard v0.3)
  / combo (E10 full stack) / combo3.
  metrics: solves, LLM repair calls/seconds, gate checks/blocks, wall time,
  final true success /190, savings vs A, counterfactual blocked-cost estimate.

Outputs: docs/paper/figures/supp_memory_evolution.png,
         docs/paper/figures/supp_gate_savings.png,
         work/supp_compare/supp_tables.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from scripts.m1_feedback import failure_type  # noqa: E402
from scripts.psv_online_analysis import (  # noqa: E402
    load_r1, final_states, load_loop_records, budget, per_round_curve)

OUT = ROOT / "work" / "supp_compare"
OUT.mkdir(parents=True, exist_ok=True)
FIG = ROOT / "docs" / "paper" / "figures"
FIG.mkdir(parents=True, exist_ok=True)


def load_shards(pat: str, thinking: str | None = None):
    rows = []
    for f in sorted(ROOT.glob(pat)):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if thinking and r.get("thinking") != thinking:
                continue
            rows.append(r)
    return rows


# ---------------- Part B: memory evolution ----------------

def stage_stats(rows):
    n = len(rows)
    exec_ok = sum(1 for r in rows if r.get("exec_status") == "ok")
    crash = sum(1 for r in rows if r.get("exec_status") == "crash")
    solved = sum(1 for r in rows
                 if r.get("solver_status") in ("optimal", "timelimit", "inforunbd"))
    wfeas = sum(1 for r in rows if r.get("witness") == "feasible")
    phantom = sum(1 for r in rows
                  if r.get("witness") == "infeasible" and r.get("objective") is not None)
    ts = sum(1 for r in rows
             if r.get("witness") == "feasible"
             and r.get("grade") in ("match", "better_than_reference"))
    wall = sum(r.get("wall_s") or 0.0 for r in rows)
    llm = sum(r.get("llm_latency_s") or 0.0 for r in rows)
    tok = sum(r.get("completion_tokens") or 0 for r in rows)
    rtok = sum(r.get("reasoning_tokens") or 0 for r in rows)
    return {
        "n": n, "exec_ok": exec_ok, "crash": crash, "solved": solved,
        "witness_feasible": wfeas, "phantom": phantom, "true_success": ts,
        "wall_total_s": round(wall, 1), "llm_total_s": round(llm, 1),
        "wall_per_cell_s": round(wall / n, 1), "llm_per_cell_s": round(llm / n, 1),
        "completion_tokens": tok, "reasoning_tokens": rtok,
    }


STAGES = [
    ("baseline", "runs/m1_pilot/m1_pilot_schema_sol*.jsonl", "on"),
    ("P1 priors", "runs/m1_pilot_priors/m1_pilot_schema_sol_priors_v*.jsonl", None),
    ("P2 +scaffold", "runs/m1_pilot_priors2/m1_pilot_schema_sol_p2_v*.jsonl", None),
    ("P3 +semantic", "runs/m1_pilot_priors3/m1_pilot_schema_sol_p3_v*.jsonl", None),
]

mem = {}
for name, pat, th in STAGES:
    rows = load_shards(pat, th)
    mem[name] = stage_stats(rows)
    print(f"[memory] {name}: {mem[name]}")

# figure 1
labels = list(mem.keys())
pct = lambda k, key: mem[k][key] / mem[k]["n"] * 100
metrics = [("exec_ok", "executable"), ("solved", "solver returned a solution"),
           ("witness_feasible", "witness feasible"), ("phantom", "phantom (solved but infeasible)"),
           ("true_success", "true success")]
colors = ["#7fb3d5", "#85c1e9", "#52be80", "#e59866", "#2471a3"]
x = range(len(labels))
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.6))
w = 0.16
for i, (key, lab) in enumerate(metrics):
    vals = [pct(k, key) for k in labels]
    ax1.bar([xi + i * w for xi in x], vals, width=w, label=lab, color=colors[i])
    for xi, v in zip(x, vals):
        ax1.text(xi + i * w, v + 1, f"{v:.0f}", ha="center", fontsize=7)
ax1.set_xticks([xi + 2 * w for xi in x])
ax1.set_xticklabels(labels, fontsize=9)
ax1.set_ylabel("% of 190 cells")
ax1.set_title("(a) memory self-evolution: capability vs failure structure")
ax1.legend(fontsize=7, loc="upper left")
ax1.set_ylim(0, 105)
wall = [mem[k]["wall_per_cell_s"] for k in labels]
llm = [mem[k]["llm_per_cell_s"] for k in labels]
ax2.bar([xi - 0.2 for xi in x], wall, width=0.38, label="exec wall s/cell", color="#af7aa1")
ax2.bar([xi + 0.2 for xi in x], llm, width=0.38, label="LLM s/cell", color="#48c9b0")
for xi, v in zip(x, wall):
    ax2.text(xi - 0.2, v + 0.5, f"{v:.0f}", ha="center", fontsize=8)
for xi, v in zip(x, llm):
    ax2.text(xi + 0.2, v + 0.5, f"{v:.0f}", ha="center", fontsize=8)
ax2.set_xticks(list(x))
ax2.set_xticklabels(labels, fontsize=9)
ax2.set_ylabel("seconds per cell")
ax2.set_title("(b) cost per cell (single-shot)")
ax2.legend(fontsize=8)
fig.suptitle("RetailOpt-190, Qwen3_8-27B, thinking on, pass@1 population", fontsize=10)
fig.tight_layout()
fig.savefig(FIG / "supp_memory_evolution.png", dpi=150)
print("figure:", FIG / "supp_memory_evolution.png")


# ---------------- Part A: gate arms ----------------

ARMS = [
    ("A witness-only", "runs/m1_feedback/m1_feedback*.jsonl", "plain"),
    ("B +gate", "runs/m1_presolve/m1_presolve_v*.jsonl", "gated"),
    ("B' +guard0.1", "runs/m1_presolve/m1_presolve_guard_v*.jsonl", "gated"),
    ("B'' +guard0.3", "runs/m1_presolve/m1_presolve_guard3_v*.jsonl", "gated"),
    # combo/combo3 excluded: they used a different round-1 pilot (P2 generation),
    # so loop budgets are not comparable under shared-pilot accounting.
]

# round-1 pilot cost (shared by all four arms, thinking=on): added back for E2E view
R1 = stage_stats(load_shards("runs/m1_pilot/m1_pilot_schema_sol*.jsonl", "on"))
R1_WALL, R1_LLM = R1["wall_total_s"], R1["llm_total_s"]

r1 = load_r1()
gate = {}
for label, g, flag in ARMS:
    states = final_states(g, r1)
    recs = load_loop_records(g)
    sel = {k: v for k, v in states.items() if k[1] == "on"}
    succ = sum(1 for v in sel.values() if failure_type(v) is None)
    resid = Counter()
    for v in sel.values():
        ft = failure_type(v)
        if ft is not None:
            resid[ft] += 1
    bud = budget(recs, "on", gated_skips_solve=(flag == "gated"))
    crashes = sum(1 for rounds in recs.values() for r in rounds
                  if r.get("exec_status") == "crash" and r.get("thinking", "on") == "on")
    blocks = sum(1 for rounds in recs.values() for r in rounds
                 if r.get("presolve_final") == "block"
                 and r.get("thinking", "on") == "on")
    loop_s = bud["llm_s"] + bud["solve_s"]
    e2e_s = loop_s + R1_WALL + R1_LLM
    curve = per_round_curve(recs, r1, "on")
    gate[label] = {"success": succ, "rate": round(succ / 190 * 100, 1),
                   "residual": dict(resid), "budget": bud, "blocks": blocks,
                   "loop_crashes": crashes,
                   "loop_total_s": round(loop_s, 1),
                   "e2e_total_s": round(e2e_s, 1),
                   "loop_s_per_success": round(loop_s / max(succ, 1), 1),
                   "e2e_s_per_success": round(e2e_s / max(succ, 1), 1),
                   "curve": {str(k): v for k, v in curve.items()}}
    print(f"[gate] {label}: success={succ}/190 crashes={crashes} "
          f"loop_s/succ={gate[label]['loop_s_per_success']} "
          f"e2e_s/succ={gate[label]['e2e_s_per_success']}")

# savings vs A
a = gate["A witness-only"]["budget"]
sav = {}
for label, _, _ in ARMS[1:]:
    b = gate[label]["budget"]
    if not b:
        continue
    sav[label] = {
        "solves_saved_pct": round((a["solves"] - b["solves"]) / a["solves"] * 100, 1),
        "solve_s_saved_pct": round((a["solve_s"] - b["solve_s"]) / a["solve_s"] * 100, 1),
        "llm_s_delta_pct": round((b["llm_s"] - a["llm_s"]) / a["llm_s"] * 100, 1),
        "e2e_per_success_delta_pct": round(
            (gate[label]["e2e_s_per_success"] - gate["A witness-only"]["e2e_s_per_success"])
            / gate["A witness-only"]["e2e_s_per_success"] * 100, 1),
        "loop_crash_delta": gate[label]["loop_crashes"] - gate["A witness-only"]["loop_crashes"],
        "gate_turns": b["gate_turns"],
        "hard_blocks": gate[label]["blocks"],
    }
    print(f"[savings] {label}: {sav[label]}")

# figure 2
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.6))
names = [l for l, _, _ in ARMS]
x = range(len(names))
solves = [gate[l]["budget"].get("solves", 0) for l in names]
crashes = [gate[l]["loop_crashes"] for l in names]
checks = [gate[l]["budget"].get("gate_turns", 0) for l in names]
w = 0.27
ax1.bar([xi - w for xi in x], solves, width=w, label="solves executed", color="#5d6d7e")
ax1.bar(list(x), crashes, width=w, label="crash execs", color="#cd6155")
ax1.bar([xi + w for xi in x], checks, width=w, label="gate checks", color="#f0b27a")
for xi, v in zip(x, solves):
    ax1.text(xi - w, v + 2, str(v), ha="center", fontsize=8)
for xi, v in zip(x, crashes):
    ax1.text(xi, v + 2, str(v), ha="center", fontsize=8)
for xi, v in zip(x, checks):
    ax1.text(xi + w, v + 2, str(v), ha="center", fontsize=8)
ax1.set_xticks(list(x)); ax1.set_xticklabels(names, fontsize=8, rotation=12)
ax1.set_ylabel("count (loop phase)")
ax1.set_title("(a) loop-phase work mix: gate trades solves for cheap failures")
ax1.legend(fontsize=8)
e2e = [gate[l]["e2e_s_per_success"] for l in names]
ax2.bar(list(x), e2e, width=0.5, color="#7fb3d5", label="E2E sec per true success")
for xi, v in zip(x, e2e):
    ax2.text(xi, v + 6, f"{v:.0f}s", ha="center", fontsize=8)
ax2.axhline(e2e[0], color="#7fb3d5", ls="--", lw=0.8)
ax3 = ax2.twinx()
rates = [gate[l]["rate"] for l in names]
ax3.plot(list(x), rates, "o-", color="#c0392b", label="true success %")
for xi, v in zip(x, rates):
    ax3.text(xi, v + 1.5, f"{v:.1f}%", ha="center", fontsize=9, color="#c0392b")
ax3.set_ylabel("true success %", color="#c0392b")
ax3.set_ylim(0, 70)
ax2.set_xticks(list(x)); ax2.set_xticklabels(names, fontsize=8, rotation=12)
ax2.set_ylabel("E2E seconds per true success (incl. shared round-1)")
ax2.set_title("(b) cost efficiency vs success")
ax2.legend(fontsize=8, loc="lower left")
fig.suptitle("RetailOpt-190, Qwen3_8-27B, thinking on, max 3 rounds, shared round-1 pilot", fontsize=10)
fig.tight_layout()
fig.savefig(FIG / "supp_gate_savings.png", dpi=150)
print("figure:", FIG / "supp_gate_savings.png")

with (OUT / "supp_tables.json").open("w") as f:
    json.dump({"memory_evolution": mem, "gate_arms": gate, "savings_vs_A": sav},
              f, ensure_ascii=False, indent=2)
print("tables:", OUT / "supp_tables.json")

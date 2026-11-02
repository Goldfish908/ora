#!/usr/bin/env python3
"""Online controlled experiment analysis: arm B (pre-solve gate,
runs/m1_presolve/m1_presolve*.jsonl) vs arm A (F12 Route-B,
runs/m1_feedback/m1_feedback*.jsonl).

Metrics per arm (on-mode):
- true success /190 (final state per cell)
- solver invocations actually consumed (arm B skips solves on gated BLOCKs)
- LLM calls consumed (generation + gate checks)
- residual failure-class distribution

Usage: python3 scripts/psv_online_analysis.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.m1_feedback import failure_type  # noqa: E402

PILOT = ROOT / "runs" / "m1_pilot"
FB = ROOT / "runs" / "m1_feedback"
PSV = ROOT / "runs" / "m1_presolve"


def load_r1(pilot_dir=PILOT, pattern="m1_pilot_schema_sol*.jsonl") -> dict:
    r1 = {}
    for f in sorted(pilot_dir.glob(pattern)):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                r1[(r["scenario_id"], r["thinking"])] = r
    return r1


def final_states(path_glob, r1):
    """Return per-cell final record (round-1 pilot + best/last loop round)."""
    last = {}
    for f in sorted(ROOT.glob(path_glob)):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            key = (r["scenario_id"], r["thinking"])
            if key not in last or r["round"] > last[key]["round"]:
                last[key] = r
    out = {}
    for key, base in r1.items():
        out[key] = last.get(key, base)
    return out


def summarize(states: dict, mode: str) -> dict:
    sel = {k: v for k, v in states.items() if k[1] == mode}
    succ = sum(1 for v in sel.values() if failure_type(v) is None)
    resid = Counter()
    for v in sel.values():
        ft = failure_type(v)
        if ft is not None:
            resid[ft] += 1
    return {"n": len(sel), "success": succ, "residual": dict(resid)}


def load_loop_records(path_glob):
    """All loop records keyed by cell (excluding round-1 pilot)."""
    recs = {}
    for f in sorted(ROOT.glob(path_glob)):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            recs.setdefault((r["scenario_id"], r["thinking"]), []).append(r)
    for v in recs.values():
        v.sort(key=lambda r: r["round"])
    return recs


def budget(recs, mode, gated_skips_solve):
    n = 0
    solves = llm_calls = gate_turns = 0
    guard_rounds = guard_rules = guard_turns = 0
    llm_t = solve_t = 0.0
    for (sid, th), rounds in recs.items():
        if th != mode:
            continue
        n += 1
        for r in rounds:
            llm_calls += 1  # one repair/generation call per loop round
            llm_t += r.get("llm_latency_s", 0.0)
            gate_turns += r.get("presolve_gate_turns", 0)
            gc = r.get("guard_checks")
            if gc:
                guard_rounds += 1
                guard_rules += sum(len(g["hits"]) for g in gc)
                guard_turns += r.get("guard_turns", 0)
            blocked = gated_skips_solve and r.get("presolve_final") == "block"
            if r["exec_status"] == "ok" and not blocked:
                solves += 1
                solve_t += r.get("wall_s", 0.0)
    if n == 0:
        return {}
    return {
        "cells": n,
        "llm_calls": llm_calls,
        "gate_turns": gate_turns,
        "guard_rounds": guard_rounds,
        "guard_rules": guard_rules,
        "guard_turns": guard_turns,
        "solves": solves,
        "llm_s": llm_t,
        "solve_s": solve_t,
    }


def per_round_curve(recs, r1, mode, max_round=3):
    """Cumulative true success after each round. Round 1 = pass@1 (shared pilot)."""
    cells = [k for k in r1 if k[1] == mode]
    curve = {}
    for rnd in range(1, max_round + 1):
        n = 0
        for key in cells:
            if failure_type(r1[key]) is None:
                n += 1
                continue
            for r in recs.get(key, []):
                if r["round"] <= rnd and failure_type(r) is None:
                    n += 1
                    break
        curve[rnd] = n
    return curve


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", action="append", metavar="LABEL=GLOB[:gated|plain]",
                    help="repeatable; first arm is the baseline for paired flips")
    ap.add_argument("--out", default=str(PSV / "online_comparison.md"))
    args = ap.parse_args()

    specs = args.arm or [
        "A (Route-B only)=runs/m1_feedback/m1_feedback*.jsonl:plain",
        "B (+ pre-solve gate)=runs/m1_presolve/m1_presolve_v*.jsonl:gated",
    ]
    arms = []
    for s in specs:
        label, _, rest = s.partition("=")
        glob, _, flag = rest.partition(":")
        # optional pilot override: ...:gated;PILOT_DIR;PILOT_GLOB
        pilot_dir, pilot_glob = None, None
        if ";" in flag:
            flag, pilot_dir, pilot_glob = flag.split(";")
        arms.append({"label": label, "glob": glob, "gated": flag == "gated",
                     "pilot_dir": pilot_dir, "pilot_glob": pilot_glob})

    r1 = load_r1()
    for a in arms:
        if a["pilot_dir"]:
            a["r1"] = load_r1(Path(a["pilot_dir"]), a["pilot_glob"])
        else:
            a["r1"] = r1
        a["states"] = final_states(a["glob"], a["r1"])
        a["recs"] = load_loop_records(a["glob"])

    lines = ["# Online controlled experiment: " + " vs ".join(a["label"] for a in arms), ""]
    for mode in ("on",):
        for a in arms:
            a["sum"] = summarize(a["states"], mode)
        lines.append(f"## mode={mode}")
        lines.append("")
        lines.append("| arm | n | true success | rate |")
        lines.append("|---|---|---|---|")
        for a in arms:
            s = a["sum"]
            lines.append(f"| {a['label']} | {s['n']} | {s['success']} | {s['success']/s['n']:.1%} |")
        lines.append("")
        for a in arms:
            lines.append(f"- {a['label']} residual: {a['sum']['residual']}")
        lines.append("")

        # paired per-cell flips vs baseline (first arm)
        base = arms[0]
        for a in arms[1:]:
            flips_better, flips_worse = [], []
            for key in base["states"]:
                if key[1] != mode:
                    continue
                w0 = failure_type(base["states"][key]) is None
                w1 = failure_type(a["states"][key]) is None
                if w1 and not w0:
                    flips_better.append(key[0])
                elif w0 and not w1:
                    flips_worse.append(key[0])
            lines.append(f"paired flips vs {base['label']}: {a['label']}-only success "
                         f"{len(flips_better)}, {base['label']}-only success {len(flips_worse)}")
            if flips_better:
                lines.append(f"  {a['label']}-only: {sorted(flips_better)}")
            if flips_worse:
                lines.append(f"  {base['label']}-only: {sorted(flips_worse)}")
            lines.append("")

        # budget (loop phase only, excludes round-1 pilot)
        lines.append("## budget (loop phase only, on-mode)")
        lines.append("")
        lines.append("| arm | cells in loop | LLM repair calls | gate turns | "
                     "guard rounds | guard rules | solves | LLM s/cell | solve s/cell |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for a in arms:
            x = budget(a["recs"], mode, gated_skips_solve=a["gated"])
            a["bud"] = x
            if not x:
                continue
            lines.append(
                f"| {a['label']} | {x['cells']} | {x['llm_calls']} | {x['gate_turns']} | "
                f"{x['guard_rounds']} | {x['guard_rules']} | {x['solves']} | "
                f"{x['llm_s']/x['cells']:.1f} | {x['solve_s']/x['cells']:.1f} |")
        lines.append("")
        if len(arms) >= 2:
            b0, b1 = arms[0].get("bud"), arms[1].get("bud")
            if b0 and b1 and b0["solves"] and b1["solves"]:
                lines.append(f"solve invocations {arms[1]['label']} vs {arms[0]['label']}: "
                             f"{b1['solves']} vs {b0['solves']} "
                             f"({(b0['solves']-b1['solves'])/b0['solves']:.1%} saved)")
                lines.append("")

        # pass@1 (= round-1 pilot, shared) and per-round cumulative success
        lines.append("## pass@1 and per-round cumulative true success (on-mode, /190)")
        lines.append("")
        lines.append("| arm | pass@1 (r1) | after r2 | after r3 |")
        lines.append("|---|---|---|---|")
        for a in arms:
            c = per_round_curve(a["recs"], a["r1"], mode)
            lines.append(f"| {a['label']} | {c[1]} ({c[1]/190:.1%}) | "
                         f"{c[2]} ({c[2]/190:.1%}) | {c[3]} ({c[3]/190:.1%}) |")
        lines.append("")
        lines.append("pass@1 为各臂自身 round-1 pilot 的记录；逐轮曲线记录修复环的边际贡献，"
                     "供自进化代数间对比（pass@1 不是唯一指标）。")
    out = "\n".join(lines) + "\n"
    Path(args.out).write_text(out)
    print(out)


if __name__ == "__main__":
    main()

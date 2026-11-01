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


def load_r1() -> dict:
    r1 = {}
    for f in sorted(PILOT.glob("m1_pilot_schema_sol*.jsonl")):
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


def main() -> None:
    r1 = load_r1()
    armA = final_states("runs/m1_feedback/m1_feedback*.jsonl", r1)
    armB = final_states("runs/m1_presolve/m1_presolve_v*.jsonl", r1)

    lines = ["# Online controlled experiment: pre-solve gate (B) vs Route-B only (A)", ""]
    for mode in ("on",):
        a = summarize(armA, mode)
        b = summarize(armB, mode)
        lines.append(f"## mode={mode}")
        lines.append("")
        lines.append("| arm | n | true success | rate |")
        lines.append("|---|---|---|---|")
        lines.append(f"| A (Route-B only) | {a['n']} | {a['success']} | {a['success']/a['n']:.1%} |")
        lines.append(f"| B (+ pre-solve gate) | {b['n']} | {b['success']} | {b['success']/b['n']:.1%} |")
        lines.append("")
        lines.append(f"- A residual: {a['residual']}")
        lines.append(f"- B residual: {b['residual']}")

        # budget accounting for arm B from records
        gate_turns = 0
        checks = 0
        for key, last in armB.items():
            if key[1] != mode:
                continue
            # count all loop records for this cell
        lines.append("")
        lines.append("Budget note: see per-record presolve_checks/n_solves_so_far "
                     "fields in runs/m1_presolve/m1_presolve_v*.jsonl")
    out = "\n".join(lines) + "\n"
    (PSV / "online_comparison.md").write_text(out)
    print(out)


if __name__ == "__main__":
    main()

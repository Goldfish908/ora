#!/usr/bin/env python3
"""Arm-C analysis: does semantic memory (P3 conventions) compose with the
full loop (pre-solve gate + crash guard v0.3 whitelist + witness feedback)?

Four-way comparison (on-mode, RetailOpt-190):
  baseline  : shared round-1 pilot, no loop            (runs/m1_pilot)
  P3        : memory pilot, no loop                    (runs/m1_pilot_priors3)
  B''       : no-memory pilot + full loop              (m1_presolve_guard3_*)
  C         : memory pilot + full loop                 (m1_presolve_memloop_*)

Metrics: true success /190, residual failure structure, per-round curve,
loop-phase budget (solves / LLM calls / wall).

Usage: python3 scripts/memloop_analysis.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.psv_online_analysis import (  # noqa: E402
    load_r1, final_states, summarize, load_loop_records, budget,
    per_round_curve)

P3 = ROOT / "runs" / "m1_pilot_priors3"


def main() -> None:
    mode = "on"
    r1_base = load_r1()
    r1_p3 = load_r1(P3, "m1_pilot_schema_sol_p3_v*.jsonl")

    arms = {
        "baseline(pass@1)": (final_states("runs/none", r1_base), None, r1_base),
        "P3 memory 1-shot": (final_states("runs/none", r1_p3), None, r1_p3),
        "B'' loop": (final_states("runs/m1_presolve/m1_presolve_guard3_*.jsonl",
                                  r1_base),
                     load_loop_records(
                         "runs/m1_presolve/m1_presolve_guard3_*.jsonl"),
                     r1_base),
        "C mem+loop": (final_states("runs/m1_presolve/m1_presolve_memloop_*.jsonl",
                                    r1_p3),
                       load_loop_records(
                           "runs/m1_presolve/m1_presolve_memloop_*.jsonl"),
                       r1_p3),
    }

    print(f"{'arm':<18} {'succ':>10} {'residual failure structure'}")
    for name, (states, _, _) in arms.items():
        s = summarize(states, mode)
        res = " ".join(f"{k}={v}" for k, v in
                       sorted(s["residual"].items(), key=lambda x: -x[1]))
        print(f"{name:<18} {s['success']:>4}/{s['n']:<5} {res}")

    print("\nper-round cumulative true success:")
    for name, (_, recs, r1) in arms.items():
        if recs is None:
            continue
        c = per_round_curve(recs, r1, mode)
        print(f"  {name:<16} " + "  ".join(f"r{k}={v}" for k, v in c.items()))

    print("\nloop-phase budget:")
    for name, (_, recs, _) in arms.items():
        if recs is None:
            continue
        b = budget(recs, mode, gated_skips_solve=True)
        if b:
            print(f"  {name:<16} cells={b['cells']} solves={b['solves']} "
                  f"llm_calls={b['llm_calls']} gate_turns={b['gate_turns']} "
                  f"guard_turns={b['guard_turns']} llm_s={b['llm_s']:.0f} "
                  f"solve_s={b['solve_s']:.0f}")


if __name__ == "__main__":
    main()

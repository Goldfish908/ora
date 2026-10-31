#!/usr/bin/env python3
"""R1.3 calibration readout: atomic-vs-composed witness pass rates on the
m2gen v2 structures (dist_plan composed of M1xM2xM6 with connections
C5/C6/C7; atom_scope/atom_lag/atom_map isolate one connection each).

Readings:
  1. per structure x thinking pass/crash rates
  2. dist_plan failure attribution by witness rule (W1=C7 lag,
     W2=C5 scope, W5=C6 map, W3/W4 feasibility, crash)
  3. excess-failure scaffold for P2: observed composed failure rate vs
     the independence prediction from atomic pass rates
     (P(all three connections right) = prod of atomic pass rates)

Usage: python3 scripts/m2_composition_analysis.py [jsonl]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSONL = ROOT / "runs" / "m2_pilot" / "m2_pilot.jsonl"

STRUCTS = ("dist_plan", "dist_setup", "atom_scope", "atom_lag",
           "atom_map", "atom_link")
# composed witness rules -> connection class they probe
RULE_TO_CONN = {"W1": "C7_lag", "W2": "C5_scope", "W5": "C6_map",
                "W3": "feasibility", "W4": "feasibility",
                "W6": "C3_link"}
ATOM_OF_CONN = {"C7_lag": "atom_lag", "C5_scope": "atom_scope",
                "C6_map": "atom_map", "C3_link": "atom_link"}
COMPOSED = ("dist_plan", "dist_setup")


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else JSONL
    rows = [json.loads(l) for l in path.read_text().splitlines()
            if l.strip()]
    rows = [r for r in rows if r["structure"] in STRUCTS
            and r["variant"] == "base"]

    agg = defaultdict(lambda: {"pass": 0, "crash": 0, "fail": 0, "n": 0})
    dist_rules = defaultdict(lambda: defaultdict(int))
    for r in rows:
        a = agg[(r["structure"], r["thinking"])]
        a["n"] += 1
        if r.get("witness_pass"):
            a["pass"] += 1
        elif r.get("model_code_crash"):
            a["crash"] += 1
        else:
            a["fail"] += 1
        if r["structure"] in COMPOSED:
            key = (r["structure"], r["thinking"])
            fired = r.get("rules") or []
            if r.get("witness_pass"):
                dist_rules[key]["(pass)"] += 1
            elif r.get("model_code_crash"):
                dist_rules[key]["(crash)"] += 1
            elif not fired:
                dist_rules[key]["(fail_no_rule)"] += 1
            for rule in set(fired):
                dist_rules[key][RULE_TO_CONN.get(rule, rule)] += 1

    print("== pass rates (base variant) ==")
    print(f"{'structure':<12}{'mode':<5}{'pass':>6}{'fail':>6}"
          f"{'crash':>6}{'n':>4}")
    pass_rate = {}
    for (s, m), a in sorted(agg.items()):
        print(f"{s:<12}{m:<5}{a['pass']:>6}{a['fail']:>6}"
              f"{a['crash']:>6}{a['n']:>4}")
        pass_rate[(s, m)] = a["pass"] / a["n"]

    print("\n== composed failure attribution (witness rules fired) ==")
    for (s, m), c in sorted(dist_rules.items()):
        total = sum(v for k, v in c.items() if k.startswith("("))
        body = ", ".join(f"{k}:{v}" for k, v in sorted(c.items()))
        print(f"  {s} {m}: n={total}  {body}")

    print("\n== P2 scaffold: composed vs independence prediction ==")
    conns_of = {"dist_plan": ("C7_lag", "C5_scope", "C6_map"),
                "dist_setup": ("C7_lag", "C5_scope", "C6_map", "C3_link")}
    for comp in COMPOSED:
        for m in ("off", "on"):
            atom_rates = {c: pass_rate.get((ATOM_OF_CONN[c], m))
                          for c in conns_of[comp]}
            if any(v is None for v in atom_rates.values()):
                continue
            pred_pass = 1.0
            for v in atom_rates.values():
                pred_pass *= v
            obs_pass = pass_rate.get((comp, m))
            if obs_pass is None:
                continue
            atom_str = "  ".join(f"{c}={v:.2f}" for c, v in atom_rates.items())
            print(f"  {comp} {m}: atomics[{atom_str}]  "
                  f"indep-pred composed pass={pred_pass:.2f}  "
                  f"observed={obs_pass:.2f}  "
                  f"excess fail={obs_pass - pred_pass:+.2f}")


if __name__ == "__main__":
    main()

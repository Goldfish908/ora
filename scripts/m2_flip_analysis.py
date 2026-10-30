#!/usr/bin/env python3
"""Flip-pair analysis for the M2 pilot.

Per-connection detection method (code regexes false-positive on comments
and generic operators like >=, so detection is numeric wherever possible):

- setup_link / activation_link (C3): solution.json setup/active flags all
  == 1 -> followed the flip (constant activation); otherwise base semantics.
- hold_time / storage_time (C4): compare the sample's objective against the
  base reference and the flip reference (solved from flip_*/correct/solve.py);
  nearer one wins, ties are ambiguous.
- hub_conservation (C2): DEGENERATE — flip reference objective equals base
  reference for every instance (slack is never useful under minimization),
  so this flip cannot discriminate; excluded from the consistency stats.

Usage: python3 scripts/m2_flip_analysis.py
"""

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROWS = ROOT / "runs" / "m2_pilot" / "m2_pilot.jsonl"
GEN = ROOT / "controlled_m2" / "gen"
TOL = 1e-6

FLAG_FIELD = {"flip_setup_link": "setup", "flip_activation_link": "active"}
OBJ_FLIPS = {"flip_hold_time", "flip_storage_time"}
DEGENERATE = {"flip_hub_conservation"}


def verdict(rec: dict) -> str:
    inst = GEN / rec["instance"]
    variant = rec["variant"]
    sb = (ROOT / "runs" / "m2_pilot" / "sandbox"
          / f"{rec['instance']}__{variant}__{rec['thinking']}__{rec['sample']}")
    sol_path = sb / "correct" / "solution.json"
    if rec.get("model_code_crash") or not sol_path.exists():
        return "crash"
    sol = json.loads(sol_path.read_text())
    if variant in FLAG_FIELD:
        flags = sol.get(FLAG_FIELD[variant])
        vals = []
        if isinstance(flags, dict):
            for v in flags.values():
                vals.extend(v if isinstance(v, list) else [v])
        if not vals:
            return "undetected"
        return "follow" if all(v > 0.5 for v in vals) else "ignore"
    if variant in OBJ_FLIPS:
        obj = sol.get("objective")
        flip_ref_path = inst / variant / "correct" / "solution.json"
        if obj is None or not flip_ref_path.exists():
            return "undetected"
        base_ref = rec["reference_objective"]
        flip_ref = json.loads(flip_ref_path.read_text())["objective"]
        d_base, d_flip = abs(obj - base_ref), abs(obj - flip_ref)
        if abs(d_base - d_flip) <= TOL:
            return "ambiguous"
        return "follow" if d_flip < d_base else "ignore"
    return "undetected"


def main() -> None:
    rows = [json.loads(l) for l in ROWS.read_text().splitlines()
            if l.strip()]
    agg = defaultdict(lambda: defaultdict(int))
    for r in rows:
        v = r["variant"]
        if not v.startswith("flip_"):
            continue
        if v in DEGENERATE:
            continue
        agg[(v, r["thinking"])][verdict(r)] += 1
    for (v, mode), counts in sorted(agg.items()):
        n = sum(counts.values())
        print(f"{v:24s} {mode:3s}  follow={counts['follow']}/{n} "
              f"ignore={counts['ignore']} crash={counts['crash']} "
              f"ambig={counts['ambiguous']} undetected={counts['undetected']}")


if __name__ == "__main__":
    main()

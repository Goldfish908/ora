#!/usr/bin/env python3
"""F12 analysis: feedback-loop recovery and residual failure distribution.

Merges round-1 (runs/m1_pilot/m1_pilot_schema_sol*.jsonl) with feedback
rounds (runs/m1_feedback/m1_feedback*.jsonl), computes per-mode layer
migration across rounds, per-family recovery, and the residual failure
taxonomy after the loop.

Usage: python3 scripts/m1_feedback_analysis.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def layer(rec: dict) -> str:
    """Failure layer of a single-round record."""
    if rec.get("exec_status") == "crash":
        return "crash"
    if rec.get("exec_status") in ("timeout", "llm_error"):
        return rec["exec_status"]
    if rec.get("solver_status") == "infeasible":
        return "declared_infeasible"
    if rec.get("objective") is None:
        return "no_objective"          # timelimit w/o incumbent etc.
    w = rec.get("witness")
    if w in ("no_solution", "parse_error"):
        return "no_dump"
    if w == "infeasible":
        return "phantom"
    # feasible
    g = rec.get("grade", "")
    if g in ("match", "better_than_reference"):
        return "TRUE_SUCCESS"
    return "feasible_suboptimal"


def load():
    r1 = {}
    for f in sorted((ROOT / "runs/m1_pilot").glob("m1_pilot_schema_sol*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                r1[(r["scenario_id"], r["thinking"])] = r
    fb = defaultdict(dict)
    for f in sorted((ROOT / "runs/m1_feedback").glob("m1_feedback*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                fb[(r["scenario_id"], r["thinking"])][r["round"]] = r
    return r1, fb


def main() -> None:
    r1, fb = load()
    cells = sorted(set(r1) | set(fb))

    # best record per cell = last available round
    final = {}
    for c in cells:
        final[c] = fb[c][max(fb[c])] if c in fb and fb[c] else r1.get(c)

    print("=== layer distribution by round ===")
    hdr = ["crash", "timeout", "llm_error", "declared_infeasible",
           "no_objective", "no_dump", "phantom", "feasible_suboptimal",
           "TRUE_SUCCESS"]
    for mode in ("off", "on"):
        for rnd, src in ((1, "r1"), (2, "fb"), (3, "fb")):
            cnt = Counter()
            for c in cells:
                if c[1] != mode:
                    continue
                rec = (r1.get(c) if rnd == 1 else fb.get(c, {}).get(rnd))
                if rec:
                    cnt[layer(rec)] += 1
            n = sum(cnt.values())
            row = " ".join(f"{h}={cnt[h]}" for h in hdr if cnt[h])
            print(f"  {mode} round{rnd} (n={n}): {row}")
        cnt = Counter()
        for c in cells:
            if c[1] == mode and c in final and final[c]:
                cnt[layer(final[c])] += 1
        row = " ".join(f"{h}={cnt[h]}" for h in hdr if cnt[h])
        print(f"  {mode} FINAL (n={sum(cnt.values())}): {row}")

    print("\n=== per-family TRUE_SUCCESS: round1 -> final ===")
    fams = sorted({c[0].split("_")[1] for c in cells})
    for fam in fams:
        line = f"  {fam}: "
        for mode in ("off", "on"):
            fcells = [c for c in cells
                      if c[0].split("_")[1] == fam and c[1] == mode]
            s1 = sum(1 for c in fcells
                     if r1.get(c) and layer(r1[c]) == "TRUE_SUCCESS")
            sF = sum(1 for c in fcells
                     if final.get(c) and layer(final[c]) == "TRUE_SUCCESS")
            line += f"{mode} {s1}->{sF}/{len(fcells)}   "
        print(line)

    print("\n=== residual phantom mechanisms (final, infeasible) ===")
    rules = Counter()
    for c, rec in final.items():
        if rec and layer(rec) == "phantom":
            for rule in rec.get("witness_rules", []):
                rules[(c[1], rule)] += 1
    for (mode, rule), n in sorted(rules.items()):
        print(f"  {mode:3s} {rule:14s} {n}")

    print("\n=== recovered-by-feedback per failure layer of round1 ===")
    recovered = Counter()
    tot_by_layer = Counter()
    for c in cells:
        if c not in r1:
            continue
        l1 = layer(r1[c])
        tot_by_layer[(c[1], l1)] += 1
        if final.get(c) and layer(final[c]) == "TRUE_SUCCESS":
            recovered[(c[1], l1)] += 1
    for (mode, l1), n in sorted(tot_by_layer.items()):
        print(f"  {mode:3s} r1={l1:20s} n={n:3d} recovered={recovered[(mode, l1)]}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""M1 RQ1 analysis: merge schema_sol shards, produce the family x thinking
table of witness-verified vs objective-match success (F10).

Usage: python3 scripts/m1_rq1_analysis.py
Reads runs/m1_pilot/m1_pilot_schema_sol*.jsonl (dedup by scenario+thinking,
last row wins), writes runs/m1_pilot/rq1_table.md + rq1_summary.json.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "runs" / "m1_pilot"


def family(sid: str) -> str:
    # retail_f7_transshipment_v3 -> F7
    return sid.split("_")[1].upper()


def main() -> None:
    rows: dict[tuple[str, str], dict] = {}
    for f in sorted(PILOT.glob("m1_pilot_schema_sol*.jsonl")):
        if "preschema" in f.name:
            continue
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                rows[(r["scenario_id"], r["thinking"])] = r

    # per (family, thinking) tallies
    agg = defaultdict(lambda: defaultdict(int))
    lat = defaultdict(list)
    for (sid, mode), r in sorted(rows.items()):
        fam = family(sid)
        a = agg[(fam, mode)]
        a["n"] += 1
        lat[(fam, mode)].append(r.get("llm_latency_s", 0))
        ex = r.get("exec_status")
        if ex != "ok":
            a["exec_fail"] += 1
            continue
        w = r.get("witness", "no_solution")
        g = r.get("grade", "?")
        a[f"witness_{w}"] += 1
        if g == "match":
            a["obj_match"] += 1
        elif g == "better_than_reference":
            a["obj_better"] += 1
        elif g.startswith("suboptimal"):
            a["obj_suboptimal"] += 1
        # phantom: objective looks fine but witness refutes feasibility
        if g in ("match", "better_than_reference") and w == "infeasible":
            a["phantom"] += 1
        # true success: feasible witness AND objective not worse than 1e-3
        if w == "feasible" and g in ("match", "better_than_reference"):
            a["true_success"] += 1
        elif w == "feasible":
            a["feasible_suboptimal"] += 1

    fams = sorted({f for f, _ in agg})
    lines = ["| family | mode | n | exec_ok | witness_feasible | obj_match "
             "| obj_better | phantom | true_success |",
             "|---|---|---|---|---|---|---|---|---|"]
    summ = {}
    for fam in fams:
        for mode in ("off", "on"):
            a = agg.get((fam, mode))
            if not a:
                continue
            n = a["n"]
            lines.append(
                f"| {fam} | {mode} | {n} | {n - a['exec_fail']} "
                f"| {a['witness_feasible']} | {a['obj_match']} "
                f"| {a['obj_better']} | {a['phantom']} "
                f"| {a['true_success']} |")
            summ[f"{fam}_{mode}"] = dict(a)
    table = "\n".join(lines)
    (PILOT / "rq1_table.md").write_text(table + "\n")
    (PILOT / "rq1_summary.json").write_text(json.dumps(summ, indent=1))
    print(table)
    tot = defaultdict(int)
    for (fam, mode), a in agg.items():
        for k, v in a.items():
            tot[f"{mode}_{k}"] += v
    print("\nTOTAL off:", {k[4:]: v for k, v in tot.items()
                           if k.startswith("off_")})
    print("TOTAL on :", {k[3:]: v for k, v in tot.items()
                         if k.startswith("on_")})


if __name__ == "__main__":
    main()

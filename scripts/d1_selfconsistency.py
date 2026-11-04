#!/usr/bin/env python3
"""D1 arm A1: self-consistency baseline.

Samples z0 / z0b / z0c are three independent single-shot bare-model runs.
Alarm rule (problem level): among samples that produced a numeric objective,
if the max pairwise relative difference exceeds TOL, the problem is flagged
as inconsistent (the model disagrees with itself => at most one can be right).

Applied to the 240 labeled cells: a cell is flagged iff its problem id is
alarmed. Detection rate on phantom cells / FP rate on correct cells.
Crashed samples (objective None) do not vote; problems with <2 votable
samples cannot be flagged (limitation reported in coverage).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs" / "industryor"
CELLS = RUNS / "industryor_judge_cells.jsonl"
OUT = ROOT / "runs" / "d1_authoring" / "selfconsistency.json"

TOL = 0.05  # relative objective disagreement threshold


def load_arm(arm: str) -> dict:
    recs = {}
    for f in sorted(RUNS.glob(f"m3_{arm}_s*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                recs[r["id"]] = r
    return recs


def main() -> None:
    arms = {a: load_arm(a) for a in ("z0", "z0b", "z0c")}
    ids = sorted(set.intersection(*[set(v) for v in arms.values()]))
    alarmed, novote = set(), set()
    for i in ids:
        objs = [arms[a][i]["objective"] for a in ("z0", "z0b", "z0c")]
        objs = [o for o in objs if isinstance(o, (int, float))]
        if len(objs) < 2:
            novote.add(i)
            continue
        hi, lo = max(objs), min(objs)
        denom = max(abs(hi), abs(lo), 1e-9)
        if (hi - lo) / denom > TOL:
            alarmed.add(i)

    cells = [json.loads(l) for l in CELLS.open() if l.strip()]
    n_ph = n_ph_flag = n_co = n_co_flag = 0
    for c in cells:
        flag = c["id"] in alarmed
        if c["wrong"]:
            n_ph += 1
            n_ph_flag += flag
        else:
            n_co += 1
            n_co_flag += flag

    summary = {
        "tol_rel": TOL,
        "problems": len(ids),
        "problems_alarmed": len(alarmed),
        "problems_no_vote(<2 objectives)": len(novote),
        "phantom": n_ph, "phantom_flagged": n_ph_flag,
        "correct": n_co, "correct_flagged": n_co_flag,
        "detection_rate": n_ph_flag / n_ph if n_ph else None,
        "false_positive_rate": n_co_flag / n_co if n_co else None,
    }
    OUT.write_text(json.dumps({"summary": summary,
                               "alarmed_ids": sorted(alarmed),
                               "novote_ids": sorted(novote)},
                              ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

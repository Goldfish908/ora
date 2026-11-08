#!/usr/bin/env python3
"""P7: build judge eval cells for F5-F8 held-out families (cross-family L2 eval).

Source: real harness trajectories from runs/evo/gen3_full190 (the full-190
ensemble run). The judge was trained ONLY on F1-F4 factory cells, so F5-F8
families are a true cross-family generalization test.

Labels (witness is the operational ground truth):
  wrong   = witness verdict "infeasible"   (includes better_than_reference
            phantoms and infeasible-but-objective-match cells)
  correct = witness "feasible" AND grade "match"
Excluded: no_solution cells (nothing to judge), feasible+suboptimal_gap
(solver-quality issue, not a semantic-validity label).

Output: work/judge_data/eval_f5f8.jsonl with the same {key, wrong, system,
user} schema as eval_v3.jsonl so the remote generative eval can run unchanged.
"""
from __future__ import annotations

import glob
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "runs" / "evo" / "gen3_full190"
SCENARIOS = ROOT / "data" / "m1_retailopt" / "f5f8_heldout90.jsonl"
OUT = ROOT / "work" / "judge_data" / "eval_f5f8.jsonl"

import sys
sys.path.insert(0, str(ROOT))
from scripts.p4_build_judge_data import data_digest, solution_digest  # noqa: E402
from scripts.p5_judge_rs import JUDGE_PROMPT  # noqa: E402

FAMS = ("f5", "f6", "f7", "f8")


def main() -> None:
    scen = {}
    for line in SCENARIOS.read_text().splitlines():
        r = json.loads(line)
        d = r.get("data")
        if isinstance(d, str):
            d = json.loads(d)
        scen[r["scenario_id"]] = {"prompt_full": r.get("prompt_full") or "", "data": d}

    rows = []
    for f in sorted(glob.glob(str(RUN / "*.jsonl"))):
        rows += [json.loads(l) for l in open(f)]
    rows = [r for r in rows if r["scenario_id"].split("_")[1] in FAMS]

    cells, skipped = [], Counter()
    for r in rows:
        sid = r["scenario_id"]
        wit, grade = r.get("witness"), r.get("grade")
        if wit == "infeasible":
            label = "wrong"
        elif wit == "feasible" and grade == "match":
            label = "correct"
        else:
            skipped[f"{wit}/{grade}"] += 1
            continue
        box = RUN / "sandbox" / f"schema_sol__{sid}__on"
        gen_py, sol_json = box / "gen.py", box / "solution.json"
        if not gen_py.exists() or not sol_json.exists():
            skipped["missing_artifact"] += 1
            continue
        s = scen.get(sid)
        if not s:
            skipped["missing_scenario"] += 1
            continue
        code = gen_py.read_text(errors="replace")
        sol = json.loads(sol_json.read_text())
        user = JUDGE_PROMPT.format(
            prompt=s["prompt_full"][:4000],
            data_digest=json.dumps(data_digest(s["data"]), ensure_ascii=False),
            code=code[:4000],
            solution_digest=json.dumps(solution_digest(sol, s["data"]),
                                       ensure_ascii=False))
        cells.append({
            "key": f"{sid}|real_traj||{label}",
            "wrong": label == "wrong",
            "system": "",
            "user": user,
        })

    with OUT.open("w") as f:
        for c in cells:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"cells: {len(cells)}")
    print("by label:", Counter(c["wrong"] for c in cells))
    print("by family/label:", sorted(Counter(
        (c["key"].split("_")[1], c["wrong"]) for c in cells).items()))
    print("skipped:", dict(skipped))


if __name__ == "__main__":
    main()

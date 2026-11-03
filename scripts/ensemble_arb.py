#!/usr/bin/env python3
"""Dual-chain ensemble arbitration over existing arm runs.

Chains: B'' (baseline-pilot round-1 + guard v0.3 + gate) and combo
(P2-pilot round-1 + guard v0.4 + gate). Both already ran; arbitration is
deterministic (witness is GT-free at decision time).

Rules reported per cell:
  E1 union (witness feasible + grade match/better in ANY chain) — uses the
     reference objective for grading; upper bound with perfect grading.
  E2 union (witness feasible in ANY chain) — fully GT-free at decision time;
     counts feasible-but-suboptimal as success (deployable, optimistic).
  E3 arbitrated: among all rounds of both chains keep witness-feasible
     candidates, pick the MIN objective (minimization), then grade vs
     reference. Decision rule is GT-free; reference is used only to score.

Usage (from /home/hewj13/wm/ora):
    python3 scripts/ensemble_arb.py
"""

from __future__ import annotations

import glob
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.m1_feedback import failure_type  # noqa: E402

CHAINS = {
    "Bpp": dict(loop="runs/m1_presolve/m1_presolve_guard3_v*.jsonl",
                pilot_dir="runs/m1_pilot",
                pilot_glob="m1_pilot_schema_sol*.jsonl"),
    "combo": dict(loop="runs/m1_presolve/m1_presolve_combo_v*.jsonl",
                  pilot_dir="runs/m1_pilot_priors2",
                  pilot_glob="m1_pilot_schema_sol_p2_v*.jsonl"),
}

TOL = 1e-4


def load_chain(spec: dict) -> dict:
    """Per on-mode cell: list of round records (round 1 = pilot, then loop)."""
    cells: dict[str, list] = {}
    pilot = {}
    for f in sorted(ROOT.glob(spec["pilot_dir"]) .glob(spec["pilot_glob"])
                    if isinstance(spec["pilot_dir"], Path) else
                    glob.glob(str(ROOT / spec["pilot_dir"] / spec["pilot_glob"]))):
        for line in open(f):
            if line.strip():
                r = json.loads(line)
                if r["thinking"] == "on":
                    pilot[r["scenario_id"]] = r
    for sid, r in pilot.items():
        cells.setdefault(sid, []).append(r)
    for f in glob.glob(str(ROOT / spec["loop"])):
        for line in open(f):
            if line.strip():
                r = json.loads(line)
                if r["thinking"] == "on":
                    cells.setdefault(r["scenario_id"], []).append(r)
    for rs in cells.values():
        rs.sort(key=lambda r: r.get("round", 1))
    return cells


def grade_ok(obj, ref) -> bool:
    if obj is None or ref is None:
        return False
    if ref == 0:
        return abs(obj) < TOL
    return (obj - ref) / max(abs(ref), 1e-12) < TOL  # minimization: lower ok


def main() -> None:
    chains = {name: load_chain(spec) for name, spec in CHAINS.items()}
    all_sids = sorted(set().union(*[set(c) for c in chains.values()]))

    e1 = e2 = e3 = 0
    per_chain_success = {name: 0 for name in chains}
    e3_pick = Counter()
    rows = []
    for sid in all_sids:
        cell_wit_ok = False      # E2
        cell_true = False        # E1
        cand = []                # E3 candidates: (obj, chain, round)
        for name, cellmap in chains.items():
            rs = cellmap.get(sid, [])
            if not rs:
                continue
            fin = rs[-1]
            if failure_type(fin) is None:
                per_chain_success[name] += 1
                cell_true = True
            for r in rs:
                if r.get("witness") == "feasible":
                    cell_wit_ok = True
                    if r.get("objective") is not None:
                        cand.append((r["objective"], name, r.get("round", 1),
                                     r.get("reference_objective")))
        e1 += cell_true
        e2 += cell_wit_ok
        if cand:
            # minimization: pick the smallest objective among feasible cands
            obj, name, rnd, ref = min(cand, key=lambda c: c[0])
            e3_pick[name] += 1
            if grade_ok(obj, ref):
                e3 += 1
        rows.append((sid, cell_true, cell_wit_ok))

    n = len(all_sids)
    L = ["# 双链集成仲裁结果", "",
         f"细胞数 n={n}(on 模式);链:B''(无先验 round-1 + guard v0.3 + 闸门)"
         "与 combo(P2 先验+脚手架 round-1 + guard v0.4 + 闸门)。", "",
         "| 规则 | 成功 | 率 | 决策时是否需真值 |", "|---|---|---|---|"]
    for name, k in per_chain_success.items():
        L.append(f"| 单链 {name} | {k} | {k/n:.1%} | — |")
    L.append(f"| **E1 并集(witness可行+grade match/better)** | {e1} | "
             f"{e1/n:.1%} | 需要(grade 用参照值) |")
    L.append(f"| E2 并集(仅 witness 可行) | {e2} | {e2/n:.1%} | 不需要 |")
    L.append(f"| **E3 仲裁(可行中取最小目标值,再判 grade)** | {e3} | "
             f"{e3/n:.1%} | 决策不需要;评分需要 |")
    L += ["", f"E3 仲裁选中来源分布:{dict(e3_pick)}", ""]
    out = "\n".join(L)
    (ROOT / "runs" / "m1_presolve" / "ensemble_dualchain.md").write_text(out)
    print(out)


if __name__ == "__main__":
    main()

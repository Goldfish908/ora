#!/usr/bin/env python3
"""N2: confirm the anchor margin threshold on gapcheck60 (independent set).

The margin>=15% threshold was selected on the 240 IndustryOR test cells
(matrix_v11.json). This script re-measures the det/FP/J curve on the
gapcheck60 RetailOpt cells with freshly authored gap rules, so the threshold
is confirmed out-of-sample.

Margin definition: for an anchor_bound violation "objective X ... bound Y",
margin = |X - Y| / |Y|. At threshold t the violation counts only if
margin >= t. Non-anchor rules are unaffected by t.

Outputs runs/d2_authoring_gap/margin_sweep.json.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from d1_apply import run_rule  # noqa: E402

GAP_DIR = ROOT / "runs" / "d2_authoring_gap"
CELLS = GAP_DIR / "gap_cells.jsonl"
OUT = GAP_DIR / "margin_sweep.json"

THRESHOLDS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30]

BELOW = re.compile(r"objective\s+([-\d.eE+]+)\s+is below the anchor lower bound\s+([-\d.eE+]+)")
ABOVE = re.compile(r"objective\s+([-\d.eE+]+)\s+exceeds the anchor upper bound\s+([-\d.eE+]+)")


def parse_margin(violation: str):
    m = BELOW.search(violation) or ABOVE.search(violation)
    if not m:
        return None
    obj, bound = float(m.group(1)), float(m.group(2))
    denom = abs(bound) if bound else 1.0
    return abs(obj - bound) / denom


def main() -> None:
    cells = [json.loads(l) for l in CELLS.read_text().splitlines() if l.strip()]
    rules_by_id = {}
    for p in sorted(GAP_DIR.glob("d2rules_gap_*.json")):
        rec = json.loads(p.read_text())
        if rec.get("ok"):
            rules_by_id[rec["id"]] = [r for r in rec.get("rules", [])
                                      if r.get("code") and r.get("status") == "calibrated"]
    n_rules = sum(len(v) for v in rules_by_id.values())
    print(f"problems with rules: {len(rules_by_id)}, calibrated rules: {n_rules}")

    # cell -> list of (rule_template, margin_or_None) violations
    hits = defaultdict(list)
    n_eval = 0
    for c in cells:
        rules = rules_by_id.get(c["scenario_id"])
        if not rules:
            continue
        n_eval += 1
        for r in rules:
            res = run_rule(r["code"], c["code"], c.get("objective"), {})
            if res.get("status") == "ok" and res.get("violation"):
                margin = parse_margin(res["violation"]) if r["template"] == "anchor_bound" else None
                hits[c["key"]].append((r["template"], margin))
    print(f"cells evaluated (rules available): {n_eval}/{len(cells)}")

    cell_by_key = {c["key"]: c for c in cells}
    wrong = {c["key"] for c in cells if c["wrong"] and c["scenario_id"] in rules_by_id}
    correct = {c["key"] for c in cells if not c["wrong"] and c["scenario_id"] in rules_by_id}

    sweep = []
    for t in THRESHOLDS:
        det = sum(1 for k in wrong
                  if any(m is None or m >= t for _, m in hits.get(k, [])))
        fp = sum(1 for k in correct
                 if any(m is None or m >= t for _, m in hits.get(k, [])))
        det_r = det / len(wrong) if wrong else 0.0
        fp_r = fp / len(correct) if correct else 0.0
        sweep.append({"margin_threshold": t, "det": det, "n_wrong": len(wrong),
                      "fp": fp, "n_correct": len(correct),
                      "detection_rate": round(det_r, 4),
                      "false_positive_rate": round(fp_r, 4),
                      "youden_j": round(det_r - fp_r, 4)})

    result = {"n_cells": len(cells), "n_eval": n_eval,
              "n_wrong": len(wrong), "n_correct": len(correct),
              "n_rules": n_rules, "sweep": sweep}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps(sweep, indent=1))


if __name__ == "__main__":
    main()

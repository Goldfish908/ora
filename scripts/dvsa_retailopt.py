#!/usr/bin/env python3
"""Compare a frozen DVSA asset with legacy C-DEMAND on saved dev40 solutions."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from m1_witness import retailopt as legacy  # noqa: E402
from ora_agent.dvsa import asset_sha256, run_asset  # noqa: E402

DEV = ROOT / "data/m1_retailopt/dev40_f1f4.jsonl"
ASSET = ROOT / "assets/dvsa/retailopt_demand_v0.1.json"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def demand_cells(result, data):
    cells = []
    products = set(data["products"])
    locations = set(data["locations"])
    for rule, detail in result["violations"]:
        if rule != "C-DEMAND":
            continue
        match = re.match(r"^\[([^,]+),([^,]+),(\d+)\]", detail)
        if not match:
            raise ValueError(f"cannot parse legacy C-DEMAND binding: {detail}")
        product, location, period = match.group(1), match.group(2), int(match.group(3))
        if product not in products or location not in locations:
            raise ValueError(f"unknown legacy binding: {detail}")
        cells.append([product, location, period])
    return cells


def compare(asset, data, solution):
    dvsa = run_asset(asset, data, solution, domain="retailopt")
    old = legacy.check(data, solution)
    old_cells = demand_cells(old, data)
    new_cells = [[item["bindings"]["p"], item["bindings"]["l"],
                  item["bindings"]["t"]] for item in dvsa["violations"]]
    visible_match = old_cells == new_cells[:len(old_cells)]
    return {
        "dvsa_status": dvsa["status"],
        "dvsa_violation_count": dvsa.get("violation_count", 0),
        "dvsa_unknown": dvsa["unknown"],
        "dvsa_cells": new_cells,
        "legacy_cells_capped_at_five": old_cells,
        "visible_cells_match": visible_match,
        "implementation_consistent": visible_match and not dvsa["unknown"],
        "complete_comparison": len(old_cells) < 5 and len(new_cells) <= 5,
        "legacy_other_rules": sorted({rule for rule, _ in old["violations"]
                                      if rule != "C-DEMAND"}),
        "legacy_warning_count": len(old["warnings"]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--roots", nargs="+", default=["work/mem_evo/replay_gen1"])
    parser.add_argument("--asset", default=str(ASSET.relative_to(ROOT)))
    parser.add_argument("--out", default="work/dvsa/retailopt_demand_consistency.json")
    args = parser.parse_args()
    dev_ids = {json.loads(line)["scenario_id"]
               for line in DEV.read_text().splitlines() if line.strip()}
    asset_path = Path(args.asset)
    if not asset_path.is_absolute():
        asset_path = ROOT / asset_path
    asset = json.loads(asset_path.read_text())
    asset_hash = asset_sha256(asset)
    rows = []
    for raw_root in args.roots:
        root = Path(raw_root)
        if not root.is_absolute():
            root = ROOT / root
        for solution_path in sorted(root.glob("sandbox/schema_sol__*__on/solution.json")):
            scenario = solution_path.parent.name[len("schema_sol__"):-len("__on")]
            if scenario not in dev_ids:
                continue
            data_path = solution_path.parent / "data.json"
            data = json.loads(data_path.read_text())
            solution = json.loads(solution_path.read_text())
            row = {"scenario_id": scenario, "solution_sha256": sha256(solution_path),
                   "data_sha256": sha256(data_path),
                   "asset_sha256": asset_hash, **compare(asset, data, solution)}
            row["implementation_consistent"] = (row["visible_cells_match"]
                                                 and not row["dvsa_unknown"])
            rows.append(row)
    rows.sort(key=lambda row: (row["scenario_id"], row["solution_sha256"]))
    counts = Counter(row["dvsa_status"] for row in rows)
    summary = {
        "available_dev_solutions": len(rows),
        "unique_dev_scenarios": len({row["scenario_id"] for row in rows}),
        "dev_scenarios_without_saved_solution": sorted(dev_ids - {row["scenario_id"] for row in rows}),
        "status_counts": dict(sorted(counts.items())),
        "visible_cells_match": sum(row["visible_cells_match"] for row in rows),
        "implementation_consistent": sum(row["implementation_consistent"] for row in rows),
        "mismatch_scenarios": [row["scenario_id"] for row in rows
                               if not row["implementation_consistent"]],
        "llm_calls": 0,
    }
    result = {
        "protocol": "retailopt-dev40-implementation-consistency-v0.1",
        "interpretation": "Rule-level agreement with legacy C-DEMAND; not independent semantic truth or end-to-end accuracy.",
        "asset_path": str(asset_path.relative_to(ROOT)),
        "asset_sha256": asset_hash,
        "summary": summary,
        "records": rows,
    }
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"asset_sha256={asset_hash}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

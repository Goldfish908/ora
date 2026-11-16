#!/usr/bin/env python3
"""Audit RetailOpt core assets on all saved solutions in a shared dev replay."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from m1_witness import retailopt as legacy  # noqa: E402
from scripts.dvsa_retail_core import asset_audit, business_score, load_assets  # noqa: E402

RULES = {"retailopt.demand_substitution_balance": "C-DEMAND",
         "retailopt.initial_inventory_zero": "C-INIT"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="work/mem_evo/replay_gen1/m1_pilot_schema_sol_gen1.jsonl")
    parser.add_argument("--sandbox-root", default="work/mem_evo/replay_gen1/sandbox")
    parser.add_argument("--out", default="work/dvsa/retailopt_core_audit")
    args = parser.parse_args()
    baseline = Path(args.baseline)
    sandbox = Path(args.sandbox_root)
    if not baseline.is_absolute():
        baseline = ROOT / baseline
    if not sandbox.is_absolute():
        sandbox = ROOT / sandbox
    rows = [json.loads(line) for line in baseline.read_text().splitlines() if line.strip()]
    assets, hashes = load_assets()
    records = []
    for row in rows:
        scenario = row["scenario_id"]
        directory = sandbox / f"schema_sol__{scenario}__on"
        data = json.loads((directory / "data.json").read_text())
        solution_path = directory / "solution.json"
        solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
        old = legacy.check(data, solution) if solution is not None else {"violations": [], "warnings": []}
        audits = asset_audit(assets, data, solution) if solution is not None else []
        asset_records = []
        for audit in audits:
            rule = RULES[audit["asset_id"]]
            old_count = sum(old_rule == rule for old_rule, _ in old["violations"])
            new_count = audit.get("violation_count", 0)
            compatible = (new_count == old_count if old_count < 5 else new_count >= old_count)
            asset_records.append({**audit, "legacy_rule": rule,
                                  "legacy_visible_count": old_count,
                                  "capped_rule_count_compatible": compatible})
        records.append({"scenario_id": scenario, "solution_available": solution is not None,
                        "initial_score": business_score(data, row["reference_objective"], solution),
                        "assets": asset_records,
                        "legacy_rules": sorted({rule for rule, _ in old["violations"]})})
    summary = {"baseline_rows": len(rows), "with_solution": sum(row["solution_available"] for row in records),
               "initial_business_correct": sum(row["initial_score"]["business_correct"] for row in records),
               "assets": {}, "llm_calls": 0}
    for asset in assets:
        asset_records = [(row, audit) for row in records for audit in row["assets"]
                         if audit["asset_id"] == asset["asset_id"]]
        summary["assets"][asset["asset_id"]] = {
            "implementation_sha256": hashes[asset["asset_id"]],
            "status_counts": dict(Counter(audit["status"] for _, audit in asset_records)),
            "capped_rule_count_compatible": sum(audit["capped_rule_count_compatible"]
                                                 for _, audit in asset_records),
            "n": len(asset_records),
            "unknown": sum(audit["status"] == "UNKNOWN" for _, audit in asset_records),
        }
    summary["asset_violation_on_initial_business_correct"] = sum(
        audit["status"] == "VIOLATED" for row in records
        if row["initial_score"]["business_correct"] for audit in row["assets"])
    result = {"protocol": "retailopt-shared-dev-core-sanity-v0.1",
              "interpretation": "Rule-count consistency with legacy C-INIT/C-DEMAND; not independent semantic truth.",
              "asset_hashes": hashes, "summary": summary, "records": records}
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

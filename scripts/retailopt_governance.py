#!/usr/bin/env python3
"""Build trusted RetailOpt audit cases and provenance-gated verification assets."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from m1_witness import retailopt as witness
from ora_agent.verification_governance import (
    CheckAsset,
    TrustedCase,
    Verdict,
    VerificationGovernor,
    convention_source,
    verbatim_source,
)
from scripts.m1_reference import build_and_solve

ROOT = Path(__file__).resolve().parents[1]
TOL = 1e-4


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table_get(table: dict, *keys) -> float:
    return float(table.get("|".join(str(key) for key in keys), 0.0))


def initial_inventory_eval(artifact: dict) -> Verdict:
    data = artifact["data"]
    inventory = artifact["solution"].get("I", {})
    for product in data["products"]:
        for location in data["locations"]:
            for remaining in range(1, data["shelf_life"][product]):
                value = table_get(inventory, product, location, 1, remaining)
                if abs(value) > TOL:
                    return Verdict("fail", f"I[{product},{location},1,{remaining}]={value} != 0")
    return Verdict("pass", "all pre-fresh initial buckets are zero")


def demand_balance_eval(artifact: dict) -> Verdict:
    data = artifact["data"]
    solution = artifact["solution"]
    sales = solution.get("sales", {})
    substitution = solution.get("sub", {})
    lost = solution.get("lost", {})
    sub_edges = {tuple(edge) for edge in data["network"]["sub_edges"]}
    for product in data["products"]:
        for location in data["locations"]:
            for period in range(1, data["periods"] + 1):
                total_sales = sum(table_get(sales, product, location, period, remaining)
                                  for remaining in range(1, data["shelf_life"][product] + 1))
                sub_out = sum(table_get(substitution, product, target, location, period)
                              for source, target in sub_edges if source == product)
                sub_in = sum(table_get(substitution, source, product, location, period)
                             for source, target in sub_edges if target == product)
                balance = total_sales + sub_out - sub_in + table_get(lost, product, location, period)
                demand = data["demand_curve"][product][period - 1] * data["demand_share"][location]
                if abs(balance - demand) > TOL * max(1.0, abs(demand)):
                    return Verdict("fail", f"[{product},{location},{period}] balance {balance} != demand {demand}")
    return Verdict("pass", "all demand balances hold")


def execution_eval(artifact: dict) -> Verdict:
    record = artifact["record"]
    if record.get("exec_status") == "ok" and record.get("objective") is not None:
        return Verdict("pass", "execution completed with an objective")
    return Verdict("fail", "execution or objective is unavailable")


def generate_cases(outdir: Path, limit: int = 3) -> dict:
    rows = [json.loads(line) for line in (ROOT / "data/m1_retailopt/dev40_f1f4.jsonl").read_text().splitlines()
            if line.strip()]
    selected = []
    seen = set()
    for row in rows:
        archetype = row["scenario_id"].rsplit("_", 1)[0]
        if archetype in seen:
            continue
        seen.add(archetype)
        data = json.loads(row["data"])
        metadata, solution = build_and_solve(data, time_limit=60, handled_mode="received")
        if metadata["status"] != "optimal" or solution is None:
            continue
        if witness.check(data, solution)["violations"]:
            continue
        selected.append((row, data, solution))
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        raise ValueError("insufficient independent clean RetailOpt references")
    cases = []
    for row, data, solution in selected:
        scenario_id = row["scenario_id"]
        cases.append({"case_id": f"{scenario_id}:clean", "expected": "pass",
                      "mutation": "clean_reference", "artifact": {"data": data, "solution": solution}})
        wrong_initial = copy.deepcopy(solution)
        product = data["products"][0]
        location = data["locations"][0]
        key = f"{product}|{location}|1|{data['shelf_life'][product] - 1}"
        wrong_initial.setdefault("I", {})[key] = 1.0
        if "C-INIT" not in {rule for rule, detail in witness.check(data, wrong_initial)["violations"]}:
            raise ValueError("controlled initial-inventory counterexample did not fire")
        cases.append({"case_id": f"{scenario_id}:wrong_initial", "expected": "fail",
                      "mutation": "fabricated_initial_inventory", "artifact": {"data": data, "solution": wrong_initial}})
        wrong_demand = copy.deepcopy(solution)
        lost = wrong_demand.setdefault("lost", {})
        lost_key = f"{product}|{location}|1"
        lost[lost_key] = lost.get(lost_key, 0.0) + 1.0
        if "C-DEMAND" not in {rule for rule, detail in witness.check(data, wrong_demand)["violations"]}:
            raise ValueError("controlled demand-balance counterexample did not fire")
        cases.append({"case_id": f"{scenario_id}:wrong_demand", "expected": "fail",
                      "mutation": "demand_balance_broken", "artifact": {"data": data, "solution": wrong_demand}})
    manifest = {"scenario_ids": [row["scenario_id"] for row, data, solution in selected],
                "split": "dev_archetypes_only", "n_cases": len(cases), "cases": cases}
    (outdir / "cases.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    return manifest


def trusted_cases(manifest: dict, mutation: str | None = None) -> list[TrustedCase]:
    if mutation == "initial":
        allowed = {"clean_reference", "fabricated_initial_inventory"}
    elif mutation == "demand":
        allowed = {"clean_reference", "demand_balance_broken"}
    else:
        allowed = None
    return [TrustedCase(case["case_id"], case["artifact"], case["expected"])
            for case in manifest["cases"] if allowed is None or case["mutation"] in allowed]


def build_governor(manifest: dict, include_demand: bool = False) -> VerificationGovernor:
    governor = VerificationGovernor(min_clean=3, min_wrong=3)
    first_row = next(json.loads(line) for line in (ROOT / "data/m1_retailopt/dev40_f1f4.jsonl").read_text().splitlines()
                     if line.strip())
    execution_source = convention_source("scip_execution_contract_v1", "a" * 64, True)
    governor.register(CheckAsset("L1_execution", 1, execution_eval, execution_source))
    execution_cases = []
    for index in range(3):
        execution_cases.append(TrustedCase(f"exec_clean_{index}",
                                           {"record": {"exec_status": "ok", "objective": float(index)}}, "pass"))
        execution_cases.append(TrustedCase(f"exec_wrong_{index}",
                                           {"record": {"exec_status": "crash", "objective": None}}, "fail"))
    governor.promote("L1_execution", execution_cases)
    initial_source = convention_source("retail_initial_inventory_v1", digest_file(ROOT / "scripts/m1_reference.py"), True)
    governor.register(CheckAsset("L2_initial_inventory", 2, initial_inventory_eval, initial_source))
    governor.promote("L2_initial_inventory", trusted_cases(manifest, "initial"))
    if include_demand:
        demand_source = verbatim_source("Demand fulfillment equation:", first_row["prompt_schema"])
        governor.register(CheckAsset("L2_demand_balance", 2, demand_balance_eval, demand_source))
        governor.promote("L2_demand_balance", trusted_cases(manifest, "demand"))
    return governor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    outdir = (ROOT / args.out).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = generate_cases(outdir)
    governor = build_governor(manifest, include_demand=True)
    write_path = outdir / "governor.json"
    write_path.write_text(json.dumps(governor.public_state(), ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"n_cases": manifest["n_cases"], "governor": governor.freeze()}, indent=1))


if __name__ == "__main__":
    main()

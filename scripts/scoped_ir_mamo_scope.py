#!/usr/bin/env python3
"""Evaluate variable-domain applicability and win-safe on MAMO mix8."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.scoped_assets import compile_asset, load_asset
from ora_agent.scoped_ir import evaluate_spec
from scripts.m1_pilot import run_code
from scripts.m3_industryor import force_integer_variables
from scripts.scoped_ir_e2e import current_cell
from scripts.scoped_ir_mamo_reuse import domain_cells, objective_score
from scripts.scoped_ir_gate import gate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="work/memory_witness/mamo_asset_registry_v0.1.json")
    parser.add_argument("--scope-config")
    parser.add_argument("--baseline", default="runs/industryor/m3_z2_mamo_mix8_s0.jsonl")
    parser.add_argument("--baseline-tag", default="z2_mamo_mix8")
    parser.add_argument("--out", default="work/scoped_ir_mamo_scope_v0.1")
    args = parser.parse_args()
    outdir = ROOT / args.out
    outdir.mkdir(parents=True, exist_ok=True)
    rows = json.loads((ROOT / "data/external/mamo_complex_lp.json").read_text())
    questions = {str(row["id"]): row for row in rows}
    baseline = []
    for line in (ROOT / args.baseline).read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record["id"] not in {r["id"]: r for r in baseline}:
            baseline.append(record)
        else:
            index = next(i for i, r in enumerate(baseline) if r["id"] == record["id"])
            if record["round"] > baseline[index]["round"]:
                baseline[index] = record
    registry = json.loads((ROOT / args.registry).read_text())
    scopes = {str(item["id"]): item for item in registry["assets"]}
    if args.scope_config:
        scopes = {}
        raw_config = json.loads((ROOT / args.scope_config).read_text())
        for key, item in raw_config.items():
            scopes[str(key)] = {**item, "status": "dev-passed"}
    asset = load_asset(ROOT / "assets/scoped_ir/variable_domain_v0.1.json")
    results = []
    for prev in sorted(baseline, key=lambda r: r["id"]):
        pid = str(prev["id"])
        scope = scopes.get(pid, {"status": "not_applicable"})
        question = questions[pid]["en_question"]
        sandbox0 = ROOT / "runs/industryor/sandbox" / f"{args.baseline_tag}__{pid}__r{prev['round']}"
        code = (sandbox0 / "gen.py").read_text()
        solution_path = sandbox0 / "solution.json"
        solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
        initial_score = objective_score(solution, float(prev["reference"]))
        result = {"id": pid, "registry_status": scope["status"],
                  "initial_score": initial_score}
        if scope["status"] != "dev-passed":
            result.update(status="not_applicable", final_score=initial_score,
                          changed=False, harmed_win=False)
            results.append(result)
            continue
        binding = {"invariant_id": "mamo_countable_food_domain",
                   "source_span": scope["evidence"],
                   "terms": [{"path": f"solution.variables.{name}"}
                             for name in solution["variables"]]}
        spec = compile_asset(asset, binding)
        gate_result = gate(spec, question, domain_cells(solution), pid)
        initial_audit = evaluate_spec(spec, question, [current_cell(solution)], pid)
        if not gate_result["accepted"]:
            result.update(status="rejected_missing_integer_evidence", binding=binding,
                          gate=gate_result, initial_audit=initial_audit,
                          final_score=initial_score, changed=False, improved=False,
                          harmed_win=False, repair_llm_calls=0, solver_runs_this_run=0)
            results.append(result)
            continue
        repaired_code = force_integer_variables(code)
        sandbox = outdir / pid
        execution = run_code(repaired_code, sandbox)
        repaired_path = sandbox / "solution.json"
        repaired = json.loads(repaired_path.read_text()) if repaired_path.exists() else None
        final_score = objective_score(repaired, float(prev["reference"]))
        final_audit = evaluate_spec(spec, question, [current_cell(repaired)], pid)
        result.update(status="frozen_template_new_binding", binding=binding,
                      initial_audit=initial_audit, final_audit=final_audit,
                      execution=execution, final_score=final_score,
                      changed=True,
                      improved=not initial_score["business_correct"] and final_score["business_correct"],
                      harmed_win=initial_score["business_correct"] and not final_score["business_correct"])
        results.append(result)
    summary = {"n": len(results),
               "activated": sum(r["status"] == "frozen_template_new_binding" for r in results),
               "not_applicable": sum(r["status"] == "not_applicable" for r in results),
               "improved": sum(r.get("improved", False) for r in results),
               "harmed_win": sum(r["harmed_win"] for r in results),
               "initial_business_correct": sum(r["initial_score"]["business_correct"] for r in results),
               "final_business_correct": sum(r["final_score"]["business_correct"] for r in results),
               "authoring_llm_calls": 0, "repair_llm_calls": 0}
    (outdir / "analysis.json").write_text(json.dumps({"summary": summary, "results": results},
                                                    ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

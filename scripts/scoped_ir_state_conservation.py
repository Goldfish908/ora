#!/usr/bin/env python3
"""Controlled SCIP checks of a frozen state-initialization/conservation asset."""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.scoped_assets import compile_asset, load_asset
from ora_agent.scoped_ir import evaluate_spec
from scripts.m1_pilot import run_code
from scripts.scoped_ir_e2e import current_cell

CASES = (
    {
        "id": "factory_stock",
        "question": ("Starting stock is zero. Next stock equals previous stock plus production "
                     "minus demand. Demand is 1. Production is at most 5. Each unit produced "
                     "costs 10. Minimize production cost."),
        "initial_span": "Starting stock is zero.",
        "flow_span": "Next stock equals previous stock plus production minus demand.",
        "names": {"initial": "stock_0", "next": "stock_1", "production": "production",
                  "demand": "demand"},
        "demand": 1, "capacity": 5, "unit_cost": 10,
    },
    {
        "id": "warehouse_inventory",
        "question": ("Beginning inventory is zero. Closing inventory equals opening inventory "
                     "plus receipts minus shipments. Shipments are 2. Receipts are at most 7. "
                     "Each received unit costs 3. Minimize receipt cost."),
        "initial_span": "Beginning inventory is zero.",
        "flow_span": "Closing inventory equals opening inventory plus receipts minus shipments.",
        "names": {"initial": "opening", "next": "closing", "production": "receipts",
                  "demand": "shipments"},
        "demand": 2, "capacity": 7, "unit_cost": 3,
    },
)


def initial_code(case: dict) -> str:
    names = case["names"]
    return f'''from pyscipopt import Model
import json

m = Model()
m.hideOutput()
{names["initial"]} = m.addVar(name="{names["initial"]}", lb=0)
{names["next"]} = m.addVar(name="{names["next"]}", lb=0)
{names["production"]} = m.addVar(name="{names["production"]}", lb=0)
{names["demand"]} = {case["demand"]}
m.addCons({names["production"]} <= {case["capacity"]})
m.addCons({names["next"]} == {names["initial"]} + {names["production"]} - {names["demand"]})
m.setObjective({case["unit_cost"]} * {names["production"]}, sense="minimize")
m.optimize()
print(f"status: {{m.getStatus()}}")
if m.getNSols() > 0:
    print(f"objective: {{m.getObjVal()}}")
    solution = {{"variables": {{name: m.getVal(var) for name, var in [
        ("{names["initial"]}", {names["initial"]}),
        ("{names["next"]}", {names["next"]}),
        ("{names["production"]}", {names["production"]})]}},
        "objective": float(m.getObjVal())}}
    solution["variables"]["{names["demand"]}"] = {names["demand"]}
    with open("solution.json", "w") as handle:
        json.dump(solution, handle, indent=1)
'''


def binding_for(case: dict) -> dict:
    names = case["names"]
    return {
        "initial": {"path": f"solution.variables.{names['initial']}", "value": 0},
        "next": {"path": f"solution.variables.{names['next']}"},
        "previous": {"path": f"solution.variables.{names['initial']}"},
        "inflows": [{"path": f"solution.variables.{names['production']}"}],
        "outflows": [{"path": f"solution.variables.{names['demand']}"}],
        "source_span": case["initial_span"],
        "flow_source_span": case["flow_span"],
    }


def repair_initialization(code: str, binding: dict) -> str:
    variable = binding["initial"]["path"].rsplit(".", 1)[-1]
    tree = ast.parse(code)
    assignment = next((node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == variable
                               for target in node.targets)
                       and isinstance(node.value, ast.Call)
                       and isinstance(node.value.func, ast.Attribute)
                       and node.value.func.attr == "addVar"), None)
    if assignment is None:
        raise ValueError("initialization repair requires a matching PySCIPOpt addVar assignment")
    optimize = next((node for node in tree.body if isinstance(node, ast.Expr)
                     and isinstance(node.value, ast.Call)
                     and isinstance(node.value.func, ast.Attribute)
                     and node.value.func.attr == "optimize"), None)
    if optimize is None:
        raise ValueError("initialization repair requires an optimize call")
    model = ast.unparse(assignment.value.func.value)
    line = f"{model}.addCons({variable} == {binding['initial']['value']!r}, \"scoped_initial_state\")\n"
    lines = code.splitlines(keepends=True)
    lines.insert(optimize.lineno - 1, line)
    return "".join(lines)


def independent_score(case: dict, solution: dict | None) -> dict:
    if not isinstance(solution, dict):
        return {"business_correct": False, "semantic_valid": False,
                "objective_correct": False, "status": "no_solution"}
    names = case["names"]
    try:
        values = {key: float(solution["variables"][name]) for key, name in names.items()}
        objective = float(solution["objective"])
    except (KeyError, TypeError, ValueError):
        return {"business_correct": False, "semantic_valid": False,
                "objective_correct": False, "status": "missing_evidence"}
    checks = {
        "explicit_initial_state": abs(values["initial"]) <= 1e-6,
        "flow_conservation": abs(values["next"] - values["initial"]
                                 - values["production"] + values["demand"]) <= 1e-6,
        "known_demand": abs(values["demand"] - case["demand"]) <= 1e-6,
        "production_capacity": -1e-6 <= values["production"] <= case["capacity"] + 1e-6,
        "nonnegative_next_state": values["next"] >= -1e-6,
        "objective_recompute": abs(objective - case["unit_cost"] * values["production"]) <= 1e-6,
    }
    expected = case["unit_cost"] * case["demand"]
    objective_correct = abs(objective - expected) <= 0.1
    semantic_valid = all(checks.values())
    return {"business_correct": semantic_valid and objective_correct,
            "semantic_valid": semantic_valid, "objective_correct": objective_correct,
            "independently_derived_optimum": expected, "objective": objective,
            "checks": checks, "status": "scored"}


def run_case(case: dict, asset: dict, outdir: Path) -> dict:
    case_dir = outdir / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    binding = binding_for(case)
    spec = compile_asset(asset, binding)
    (case_dir / "question.txt").write_text(case["question"] + "\n")
    (case_dir / "binding.json").write_text(json.dumps(binding, indent=1) + "\n")
    (case_dir / "spec.json").write_text(json.dumps(spec, indent=1) + "\n")
    code = initial_code(case)
    initial_execution = run_code(code, case_dir / "initial")
    initial_path = case_dir / "initial" / "solution.json"
    initial_solution = json.loads(initial_path.read_text()) if initial_path.exists() else None
    initial_audit = evaluate_spec(spec, case["question"], [current_cell(initial_solution)],
                                  case["id"])["records"][0]
    initial_score = independent_score(case, initial_solution)
    fired_rules = {item["rule"] for item in initial_audit["violations"]}
    if fired_rules != {"state_conservation_initial"}:
        raise AssertionError(f"unexpected controlled initial violations: {fired_rules}")
    repaired_code = repair_initialization(code, binding)
    final_execution = run_code(repaired_code, case_dir / "repaired")
    final_path = case_dir / "repaired" / "solution.json"
    final_solution = json.loads(final_path.read_text()) if final_path.exists() else None
    final_audit = evaluate_spec(spec, case["question"], [current_cell(final_solution)],
                                case["id"])["records"][0]
    final_score = independent_score(case, final_solution)
    return {
        "id": case["id"], "case_type": "controlled_synthetic",
        "reuse_type": "frozen_template_new_binding",
        "asset": {"mechanism_id": asset["mechanism_id"], "version": asset["version"]},
        "binding": binding, "initial_code": code, "final_code": repaired_code,
        "initial_execution": initial_execution, "final_execution": final_execution,
        "initial_audit": initial_audit, "final_audit": final_audit,
        "initial_score": initial_score, "final_score": final_score,
        "authoring_llm_calls": 0, "repair_llm_calls": 0,
        "improved": not initial_score["business_correct"] and final_score["business_correct"],
        "harmed_win": initial_score["business_correct"] and not final_score["business_correct"],
    }


def main() -> None:
    outdir = ROOT / "work/scoped_ir_state_conservation_v0.1"
    outdir.mkdir(parents=True, exist_ok=True)
    asset = load_asset(ROOT / "assets/scoped_ir/state_conservation_v0.1.json")
    results = [run_case(case, asset, outdir) for case in CASES]
    summary = {
        "n": len(results), "controlled_synthetic": len(results), "natural_cases": 0,
        "frozen_template_new_binding": len(results),
        "authoring_llm_calls": 0, "repair_llm_calls": 0,
        "improved": sum(row["improved"] for row in results),
        "harmed_win": sum(row["harmed_win"] for row in results),
        "final_business_correct": sum(row["final_score"]["business_correct"] for row in results),
        "checker_recoveries": sum(row["initial_audit"]["fired"]
                                  and row["final_audit"]["status"] == "ok"
                                  and not row["final_audit"]["fired"]
                                  and row["improved"] for row in results),
        "final_unknown": sum(row["final_audit"]["status"] != "ok" for row in results),
        "initial_objectives": {row["id"]: row["initial_score"].get("objective") for row in results},
        "final_objectives": {row["id"]: row["final_score"].get("objective") for row in results},
    }
    analysis = {"summary": summary, "results": results}
    (outdir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if (summary["improved"] != len(results) or summary["checker_recoveries"] != len(results)
            or summary["final_unknown"] or summary["harmed_win"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Prepare auditable IndustryOR initial programs without objective-only grading."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import itertools
import json
import math
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "industryor" / "IndustryOR.json"
ORTHOUGHT = (
    ROOT
    / "data"
    / "external"
    / "ORThought"
    / "datasets"
    / "processed"
    / "IndustryOR"
)
MANIFEST = ROOT / "assets" / "industryor_next_stage" / "manifest.json"
WORK_ROOT = ROOT / "work" / "industryor_next_stage_v0.1"
EXEC_PYTHON = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"
SUPPORTED_IDS = (19, 20, 21, 25, 48, 4, 8, 9)
ERROR_IDS = (19, 20, 21, 25, 48)
CONTROL_IDS = (4, 8, 9)
ABS_TOL = 1e-5
OBJ_REL_TOL = 1e-7
SOLUTION_SCHEMA = "industryor.solution.v1"
MANIFEST_SCHEMA = "industryor.next_stage.manifest.v1"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _source_path(problem_id: int) -> Path:
    return (
        ROOT
        / "runs"
        / "industryor"
        / "sandbox"
        / f"z0__{problem_id}__r1"
        / "gen.py"
    )


def _reference_dir(problem_id: int) -> Path:
    return ORTHOUGHT / f"prob_{problem_id - 1:03d}"


def instrument_code(source: str, export_aliases: Mapping[str, str] | None = None) -> str:
    """Append a fixed exporter after validating the top-level model shape."""
    export_aliases = dict(export_aliases or {})
    if any(not isinstance(name, str) or not name
           for name in list(export_aliases) + list(export_aliases.values())):
        raise ValueError("export aliases must contain nonempty variable names")
    if len(set(export_aliases.values())) != len(export_aliases):
        raise ValueError("export aliases must have unique destination names")
    tree = ast.parse(source)
    if any(
        isinstance(node, ast.Name) and node.id.startswith("_ior_next_")
        for node in ast.walk(tree)
    ):
        raise ValueError("source uses the reserved instrumentation prefix")

    optimize_calls = []
    model_assignments = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "optimize"
                and isinstance(call.func.value, ast.Name)
            ):
                optimize_calls.append(call.func.value.id)
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (
                isinstance(target, ast.Name)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "Model"
            ):
                model_assignments.append(target.id)
    if len(optimize_calls) != 1 or len(set(optimize_calls)) != 1:
        raise ValueError("expected exactly one top-level model.optimize() call")
    model_name = optimize_calls[0]
    if model_assignments.count(model_name) != 1:
        raise ValueError("expected one top-level Model assignment for the model")

    alias_validation = ""
    alias_export = ""
    if export_aliases:
        alias_validation = f'''
    _ior_next_aliases = {export_aliases!r}
    _ior_next_names = [
        _ior_next_aliases.get(str(_ior_next_var.name), str(_ior_next_var.name))
        for _ior_next_var in _ior_next_model.getVars()
    ]
    if len(_ior_next_names) != len(set(_ior_next_names)):
        raise ValueError("export aliases collide with another solver variable")
'''
        alias_export = '''
    _ior_next_missing = set(_ior_next_aliases) - set(_ior_next_payload["variables"])
    if _ior_next_missing:
        raise ValueError("export alias source is missing: " + str(sorted(_ior_next_missing)))
    for _ior_next_field in ("variables", "variable_types"):
        _ior_next_payload[_ior_next_field] = {
            _ior_next_aliases.get(_ior_next_name, _ior_next_name): _ior_next_value
            for _ior_next_name, _ior_next_value in _ior_next_payload[_ior_next_field].items()
        }
'''
    exporter = f'''

# Deterministic IndustryOR export suffix; no business statements are replaced.
import json as _ior_next_json
import math as _ior_next_math

_ior_next_model = {model_name}
_ior_next_payload = {{
    "schema_version": {SOLUTION_SCHEMA!r},
    "solver_status": str(_ior_next_model.getStatus()),
    "solution_count": int(_ior_next_model.getNSols()),
    "objective": None,
    "variables": {{}},
    "variable_types": {{}},
    "export": {{"complete": False, "error": None}},
}}
try:
    if _ior_next_payload["solution_count"] < 1:
        raise ValueError("SCIP returned no solution to export")
    _ior_next_payload["objective"] = float(_ior_next_model.getObjVal()){alias_validation}
    for _ior_next_var in _ior_next_model.getVars():
        _ior_next_name = str(_ior_next_var.name)
        _ior_next_value = float(_ior_next_model.getVal(_ior_next_var))
        if not _ior_next_math.isfinite(_ior_next_value):
            raise ValueError("non-finite variable: " + _ior_next_name)
        _ior_next_payload["variables"][_ior_next_name] = _ior_next_value
        _ior_next_payload["variable_types"][_ior_next_name] = str(
            _ior_next_var.vtype()
        ){alias_export}
    _ior_next_payload["export"]["complete"] = True
except Exception as _ior_next_exc:
    _ior_next_payload["variables"] = {{}}
    _ior_next_payload["variable_types"] = {{}}
    _ior_next_payload["export"]["error"] = (
        type(_ior_next_exc).__name__ + ": " + str(_ior_next_exc)
    )[:500]
with open("solution.json", "w", encoding="utf-8") as _ior_next_fp:
    _ior_next_json.dump(
        _ior_next_payload,
        _ior_next_fp,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    )
    _ior_next_fp.write("\\n")
print(
    "solution_export: "
    + ("complete" if _ior_next_payload["export"]["complete"] else "failed")
)
'''
    instrumented = source.rstrip() + exporter
    ast.parse(instrumented)
    return instrumented


def _rule(rule: str, passed: bool, observed: Any, expected: str) -> dict[str, Any]:
    return {
        "rule": rule,
        "passed": bool(passed),
        "observed": observed,
        "expected": expected,
    }


def _ge(value: float, bound: float) -> bool:
    return value >= bound - ABS_TOL


def _le(value: float, bound: float) -> bool:
    return value <= bound + ABS_TOL


def _eq(value: float, bound: float) -> bool:
    return abs(value - bound) <= ABS_TOL


def _base_result(problem_id: int) -> dict[str, Any]:
    return {
        "schema_version": "industryor.business_audit.v1",
        "problem_id": problem_id,
        "audit_status": "complete",
        "business_correct": False,
        "variable_audit": {},
        "constraint_checks": [],
        "violations": [],
        "execution_checks": {},
        "business_objective": None,
        "model_objective_consistent": False,
        "optimality": "not_assessed",
        "blocking_reasons": [],
    }


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _score_standard(
    problem_id: int,
    solution: Mapping[str, Any],
    domains: Mapping[str, str],
    constraints: Callable[[Mapping[str, float]], list[dict[str, Any]]],
    objective: Callable[[Mapping[str, float]], float],
    independent_optimum: Callable[[], float],
) -> dict[str, Any]:
    result = _base_result(problem_id)
    if not isinstance(solution, Mapping):
        result["audit_status"] = "invalid_solution"
        result["violations"].append("solution is not a JSON object")
        return result
    if solution.get("schema_version") != SOLUTION_SCHEMA:
        result["audit_status"] = "invalid_solution"
        result["violations"].append("unsupported or missing solution schema")
        return result

    export = solution.get("export")
    execution_checks = {
        "export_complete": isinstance(export, Mapping) and export.get("complete") is True,
        "solver_optimal": solution.get("solver_status") == "optimal",
        "has_solution": _finite_number(solution.get("solution_count"))
        and solution.get("solution_count", 0) >= 1,
        "model_objective_finite": _finite_number(solution.get("objective")),
    }
    result["execution_checks"] = execution_checks
    for name, passed in execution_checks.items():
        if not passed:
            result["violations"].append(f"execution check failed: {name}")

    raw_variables = solution.get("variables")
    if not isinstance(raw_variables, Mapping):
        result["audit_status"] = "invalid_solution"
        result["violations"].append("variables is not an object")
        return result

    values: dict[str, float] = {}
    structural_ok = True
    for name, domain in domains.items():
        value = raw_variables.get(name)
        present = name in raw_variables
        numeric = _finite_number(value)
        if numeric:
            values[name] = float(value)
        if domain == "integer":
            domain_ok = numeric and _eq(float(value), round(float(value)))
        elif domain == "binary":
            domain_ok = numeric and (_eq(float(value), 0.0) or _eq(float(value), 1.0))
        else:
            domain_ok = numeric
        result["variable_audit"][name] = {
            "present": present,
            "value": float(value) if numeric else None,
            "domain": domain,
            "passed": bool(domain_ok),
        }
        if not present or not numeric:
            structural_ok = False
        if not domain_ok:
            result["violations"].append(f"variable domain failed: {name}")

    if not structural_ok or not execution_checks["model_objective_finite"]:
        result["audit_status"] = "invalid_solution"
        result["violations"].append("required variables or model objective are unavailable")
        return result

    checks = constraints(values)
    result["constraint_checks"] = checks
    for check in checks:
        if not check["passed"]:
            result["violations"].append(f"business constraint failed: {check['rule']}")

    business_objective = float(objective(values))
    result["business_objective"] = business_objective
    optimum = float(independent_optimum())
    is_optimal = math.isclose(
        business_objective, optimum, rel_tol=OBJ_REL_TOL, abs_tol=ABS_TOL
    )
    domains_ok = all(item["passed"] for item in result["variable_audit"].values())
    feasible = domains_ok and all(check["passed"] for check in checks)
    result["optimality"] = (
        "proven_optimal" if is_optimal else "suboptimal"
    ) if feasible else "not_applicable_infeasible"
    if feasible and not is_optimal:
        result["violations"].append("business objective is not independently optimal")

    model_consistent = math.isclose(
        float(solution["objective"]),
        business_objective,
        rel_tol=OBJ_REL_TOL,
        abs_tol=ABS_TOL,
    )
    result["model_objective_consistent"] = model_consistent
    if not model_consistent:
        result["violations"].append(
            "reported model objective differs from the audited business objective"
        )

    result["business_correct"] = bool(
        all(execution_checks.values())
        and feasible
        and is_optimal
        and model_consistent
    )
    return result


def _nonnegative_checks(values: Mapping[str, float], names: Iterable[str]) -> list[dict[str, Any]]:
    return [
        _rule(f"nonnegative_{name}", _ge(values[name], 0.0), values[name], ">= 0")
        for name in names
    ]


def _link_check(values: Mapping[str, float], quantity: str, indicator: str) -> dict[str, Any]:
    consistent = (values[quantity] > 0.5) == (values[indicator] > 0.5)
    return _rule(
        f"link_{quantity}_{indicator}",
        consistent,
        {quantity: values[quantity], indicator: values[indicator]},
        "indicator is 1 exactly when quantity is positive",
    )


def _score_19(solution: Mapping[str, Any]) -> dict[str, Any]:
    domains = {"x_A": "integer", "x_B": "integer", "x_C": "integer", "y_A": "binary", "y_B": "binary"}

    def constraints(v: Mapping[str, float]) -> list[dict[str, Any]]:
        chairs = 15 * v["x_A"] + 10 * v["x_B"] + 10 * v["x_C"]
        return _nonnegative_checks(v, ("x_A", "x_B", "x_C")) + [
            _rule("minimum_chairs", _ge(chairs, 100), chairs, ">= 100"),
            _rule("maximum_chairs", _le(chairs, 500), chairs, "<= 500"),
            _rule("A_implies_ten_B_chairs", v["x_A"] <= 0.5 or _ge(10 * v["x_B"], 10), 10 * v["x_B"], ">= 10 when A is ordered"),
            _rule("B_implies_C_order", v["x_B"] <= 0.5 or _ge(v["x_C"], 1), v["x_C"], ">= 1 when B is ordered"),
            _link_check(v, "x_A", "y_A"),
            _link_check(v, "x_B", "y_B"),
        ]

    def optimum() -> float:
        best = math.inf
        for a in range(34):
            for b in range(51):
                for c in range(51):
                    chairs = 15 * a + 10 * b + 10 * c
                    if not 100 <= chairs <= 500:
                        continue
                    if a > 0 and 10 * b < 10:
                        continue
                    if b > 0 and c < 1:
                        continue
                    best = min(best, 750 * a + 450 * b + 400 * c)
        return best

    return _score_standard(
        19,
        solution,
        domains,
        constraints,
        lambda v: 750 * v["x_A"] + 450 * v["x_B"] + 400 * v["x_C"],
        optimum,
    )


def _toy_constraints(v: Mapping[str, float], problem_id: int) -> list[dict[str, Any]]:
    if problem_id == 20:
        plastic = 30 * v["x1"] + 10 * v["x2"] + 20 * v["x3"] + 15 * v["x4"]
        electronics = 8 * v["x1"] + 5 * v["x2"] + 3 * v["x3"] + 2 * v["x4"]
        plastic_bound, electronics_bound = 1200, 800
    else:
        plastic = 12 * v["x1"] + 20 * v["x2"] + 15 * v["x3"] + 10 * v["x4"]
        electronics = 6 * v["x1"] + 3 * v["x2"] + 5 * v["x3"] + 4 * v["x4"]
        plastic_bound, electronics_bound = 890, 500
    resource_name = "plastic" if problem_id == 20 else "wood"
    if problem_id == 20:
        implication = _rule(
            "cars_imply_blocks",
            v["x2"] <= 0.5 or _ge(v["x3"], 1),
            {"x2": v["x2"], "x3": v["x3"]},
            "x3 >= 1 when x2 > 0",
        )
        quantity_rule = _rule(
            "dolls_no_greater_than_cars",
            _le(v["x4"], v["x2"]),
            {"x2": v["x2"], "x4": v["x4"]},
            "x4 <= x2",
        )
    else:
        implication = _rule(
            "boats_imply_airplanes",
            v["x3"] <= 0.5 or _ge(v["x2"], 1),
            {"x2": v["x2"], "x3": v["x3"]},
            "x2 >= 1 when x3 > 0",
        )
        quantity_rule = _rule(
            "boats_no_greater_than_trains",
            _le(v["x3"], v["x4"]),
            {"x3": v["x3"], "x4": v["x4"]},
            "x3 <= x4",
        )
    return _nonnegative_checks(v, ("x1", "x2", "x3", "x4")) + [
        _rule(resource_name, _le(plastic, plastic_bound), plastic, f"<= {plastic_bound}"),
        _rule("electronics" if problem_id == 20 else "steel", _le(electronics, electronics_bound), electronics, f"<= {electronics_bound}"),
        _rule("first_excludes_fourth", v["x1"] <= 0.5 or _eq(v["x4"], 0), {"x1": v["x1"], "x4": v["x4"]}, "x4 = 0 when x1 > 0"),
        implication,
        quantity_rule,
    ]


def _score_20(solution: Mapping[str, Any]) -> dict[str, Any]:
    domains = {f"x{i}": "integer" for i in range(1, 5)} | {f"y{i}": "binary" for i in range(1, 5)}

    def constraints(v: Mapping[str, float]) -> list[dict[str, Any]]:
        return _toy_constraints(v, 20) + [_link_check(v, f"x{i}", f"y{i}") for i in range(1, 5)]

    def optimum() -> float:
        best = 0.0
        for x1 in range(41):
            for x2 in range(121):
                for x3 in range(61):
                    if x2 > 0 and x3 < 1:
                        continue
                    plastic_left = 1200 - 30 * x1 - 10 * x2 - 20 * x3
                    electronics_left = 800 - 8 * x1 - 5 * x2 - 3 * x3
                    if plastic_left < 0 or electronics_left < 0:
                        continue
                    x4 = 0 if x1 > 0 else min(x2, plastic_left // 15, electronics_left // 2)
                    best = max(best, 15 * x1 + 8 * x2 + 12 * x3 + 5 * x4)
        return float(best)

    return _score_standard(
        20,
        solution,
        domains,
        constraints,
        lambda v: 15 * v["x1"] + 8 * v["x2"] + 12 * v["x3"] + 5 * v["x4"],
        optimum,
    )


def _score_21(solution: Mapping[str, Any]) -> dict[str, Any]:
    domains = {"x_A": "integer", "x_B": "integer", "x_C": "integer", "y_A": "binary", "y_B": "binary"}

    def constraints(v: Mapping[str, float]) -> list[dict[str, Any]]:
        tables = 20 * v["x_A"] + 15 * v["x_B"] + 15 * v["x_C"]
        return _nonnegative_checks(v, ("x_A", "x_B", "x_C")) + [
            _rule("minimum_tables", _ge(tables, 150), tables, ">= 150"),
            _rule("maximum_tables", _le(tables, 600), tables, "<= 600"),
            _rule("A_implies_thirty_B_tables", v["x_A"] <= 0.5 or _ge(15 * v["x_B"], 30), 15 * v["x_B"], ">= 30 when A is ordered"),
            _rule("B_implies_C_order", v["x_B"] <= 0.5 or _ge(v["x_C"], 1), v["x_C"], ">= 1 when B is ordered"),
            _link_check(v, "x_A", "y_A"),
            _link_check(v, "x_B", "y_B"),
        ]

    def optimum() -> float:
        best = math.inf
        for a in range(31):
            for b in range(41):
                for c in range(41):
                    tables = 20 * a + 15 * b + 15 * c
                    if not 150 <= tables <= 600:
                        continue
                    if a > 0 and 15 * b < 30:
                        continue
                    if b > 0 and c < 1:
                        continue
                    best = min(best, 2400 * a + 1650 * b + 1500 * c)
        return best

    return _score_standard(
        21,
        solution,
        domains,
        constraints,
        lambda v: 2400 * v["x_A"] + 1650 * v["x_B"] + 1500 * v["x_C"],
        optimum,
    )


def _investment_values(v: Mapping[str, float]) -> tuple[float, float, float]:
    cash_year_1 = 100000 - v["x1"] - v["x2"] + 1.7 * v["x1"]
    cash_year_2 = cash_year_1 - v["x3"] - v["x4"] + 1.7 * v["x3"] + 3 * v["x2"]
    terminal_wealth = cash_year_2 - v["x5"] + 1.7 * v["x5"] + 3 * v["x4"]
    return cash_year_1, cash_year_2, terminal_wealth


def _score_25(solution: Mapping[str, Any]) -> dict[str, Any]:
    domains = {f"x{i}": "continuous" for i in range(1, 6)}

    def constraints(v: Mapping[str, float]) -> list[dict[str, Any]]:
        cash_1, cash_2, _ = _investment_values(v)
        return _nonnegative_checks(v, domains) + [
            _rule("year_0_cash", _le(v["x1"] + v["x2"], 100000), v["x1"] + v["x2"], "<= 100000"),
            _rule("year_1_cash", _le(v["x3"] + v["x4"], cash_1), {"invested": v["x3"] + v["x4"], "available": cash_1}, "investment <= available cash"),
            _rule("year_2_cash", _le(v["x5"], cash_2), {"invested": v["x5"], "available": cash_2}, "investment <= available cash"),
        ]

    def optimum() -> float:
        one_year = 1.7
        two_year_total_return = 3.0
        best_growth = max(
            1.0,
            one_year,
            one_year**2,
            one_year**3,
            two_year_total_return,
            two_year_total_return * one_year,
            one_year * two_year_total_return,
        )
        return 100000 * best_growth

    return _score_standard(
        25,
        solution,
        domains,
        constraints,
        lambda v: _investment_values(v)[2],
        optimum,
    )


def _score_4(solution: Mapping[str, Any]) -> dict[str, Any]:
    domains = {"x_cows": "integer", "x_sheep": "integer", "x_chickens": "integer"}

    def constraints(v: Mapping[str, float]) -> list[dict[str, Any]]:
        manure = 10 * v["x_cows"] + 5 * v["x_sheep"] + 3 * v["x_chickens"]
        animals = v["x_cows"] + v["x_sheep"] + v["x_chickens"]
        return _nonnegative_checks(v, domains) + [
            _rule("manure_capacity", _le(manure, 800), manure, "<= 800"),
            _rule("chicken_capacity", _le(v["x_chickens"], 50), v["x_chickens"], "<= 50"),
            _rule("minimum_cows", _ge(v["x_cows"], 10), v["x_cows"], ">= 10"),
            _rule("minimum_sheep", _ge(v["x_sheep"], 20), v["x_sheep"], ">= 20"),
            _rule("animal_capacity", _le(animals, 100), animals, "<= 100"),
        ]

    def optimum() -> float:
        best = -math.inf
        for cows in range(101):
            for sheep in range(101):
                for chickens in range(51):
                    if cows < 10 or sheep < 20 or cows + sheep + chickens > 100:
                        continue
                    if 10 * cows + 5 * sheep + 3 * chickens > 800:
                        continue
                    best = max(best, 400 * cows + 120 * sheep + 3 * chickens)
        return best

    return _score_standard(
        4,
        solution,
        domains,
        constraints,
        lambda v: 400 * v["x_cows"] + 120 * v["x_sheep"] + 3 * v["x_chickens"],
        optimum,
    )


_ASSIGNMENT_COST = (
    (9, 4, 3, 7),
    (4, 6, 5, 6),
    (5, 4, 7, 5),
    (7, 5, 2, 3),
    (10, 6, 7, 4),
)


def _score_8(solution: Mapping[str, Any]) -> dict[str, Any]:
    domains = {f"x_{i}_{j}": "binary" for i in range(5) for j in range(4)}

    def constraints(v: Mapping[str, float]) -> list[dict[str, Any]]:
        checks = []
        for j in range(4):
            assigned = sum(v[f"x_{i}_{j}"] for i in range(5))
            checks.append(_rule(f"task_{j}_exactly_once", _eq(assigned, 1), assigned, "= 1"))
        for i in range(5):
            assigned = sum(v[f"x_{i}_{j}"] for j in range(4))
            checks.append(_rule(f"worker_{i}_at_most_once", _le(assigned, 1), assigned, "<= 1"))
        total = sum(v[name] for name in domains)
        checks.append(_rule("exactly_four_workers", _eq(total, 4), total, "= 4"))
        return checks

    def optimum() -> float:
        return float(min(
            sum(_ASSIGNMENT_COST[worker][task] for task, worker in enumerate(workers))
            for workers in itertools.permutations(range(5), 4)
        ))

    return _score_standard(
        8,
        solution,
        domains,
        constraints,
        lambda v: sum(_ASSIGNMENT_COST[i][j] * v[f"x_{i}_{j}"] for i in range(5) for j in range(4)),
        optimum,
    )


def _score_9(solution: Mapping[str, Any]) -> dict[str, Any]:
    domains = {f"x{i}": "integer" for i in range(1, 5)} | {"y1": "binary", "y2": "binary"}

    def constraints(v: Mapping[str, float]) -> list[dict[str, Any]]:
        return _toy_constraints(v, 9) + [
            _link_check(v, "x1", "y1"),
            _link_check(v, "x3", "y2"),
        ]

    def optimum() -> float:
        best = 0.0
        for x1 in range(75):
            for x2 in range(45):
                for x4 in range(90):
                    if x1 > 0 and x4 > 0:
                        continue
                    wood_left = 890 - 12 * x1 - 20 * x2 - 10 * x4
                    steel_left = 500 - 6 * x1 - 3 * x2 - 4 * x4
                    if wood_left < 0 or steel_left < 0:
                        continue
                    x3 = min(x4, wood_left // 15, steel_left // 5)
                    if x2 < 1:
                        x3 = 0
                    best = max(best, 5 * x1 + 10 * x2 + 8 * x3 + 7 * x4)
        return float(best)

    return _score_standard(
        9,
        solution,
        domains,
        constraints,
        lambda v: 5 * v["x1"] + 10 * v["x2"] + 8 * v["x3"] + 7 * v["x4"],
        optimum,
    )


def _score_48(solution: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(solution, Mapping) or not isinstance(solution.get("variables"), Mapping):
        result = _base_result(48)
        result["audit_status"] = "invalid_solution"
        result["violations"].append("solution or variables object is unavailable")
        return result
    variables = solution["variables"]
    if "x_A_OT" not in variables or "x_B_OT" not in variables:
        result = _base_result(48)
        result["audit_status"] = "blocked"
        result["blocking_reasons"] = [
            "The initial program has no per-product overtime quantity variables x_A_OT/x_B_OT.",
            "A single overtime-hours variable cannot identify the per-unit profit reductions required by the question and ORThought model.",
        ]
        for name in ("x_A", "x_B", "y", "z"):
            value = variables.get(name)
            result["variable_audit"][name] = {
                "present": name in variables,
                "value": float(value) if _finite_number(value) else None,
                "domain": "binary" if name == "z" else "continuous",
                "passed": _finite_number(value),
                "audit_scope": "partial_only",
            }
        result["violations"].append("full variable-level business audit is blocked")
        return result

    domains = {"x_A": "continuous", "x_B": "continuous", "x_A_OT": "continuous", "x_B_OT": "continuous"}

    def constraints(v: Mapping[str, float]) -> list[dict[str, Any]]:
        process_i = 4 * v["x_A"] + 6 * v["x_B"]
        process_ii = 3 * v["x_A"] + 2 * v["x_B"]
        overtime = 3 * v["x_A_OT"] + 2 * v["x_B_OT"]
        profit = 300 * v["x_A"] + 450 * v["x_B"] - 20 * v["x_A_OT"] - 25 * v["x_B_OT"]
        return _nonnegative_checks(v, domains) + [
            _rule("minimum_A", _ge(v["x_A"], 10), v["x_A"], ">= 10"),
            _rule("minimum_B", _ge(v["x_B"], 15), v["x_B"], ">= 15"),
            _rule("process_I_exact", _eq(process_i, 150), process_i, "= 150"),
            _rule("process_II_with_overtime", _le(process_ii, 70 + overtime), {"used": process_ii, "regular_plus_overtime": 70 + overtime}, "used <= regular + overtime"),
            _rule("overtime_limit", _le(overtime, 30), overtime, "<= 30"),
            _rule("overtime_A_quantity_link", _le(v["x_A_OT"], v["x_A"]), v["x_A_OT"], "<= x_A"),
            _rule("overtime_B_quantity_link", _le(v["x_B_OT"], v["x_B"]), v["x_B_OT"], "<= x_B"),
            _rule("minimum_adjusted_profit", _ge(profit, 10000), profit, ">= 10000"),
        ]

    def optimum() -> float:
        feasible_a = 10.0
        feasible_b = (150 - 4 * feasible_a) / 6
        return 300 * feasible_a + 450 * feasible_b

    return _score_standard(
        48,
        solution,
        domains,
        constraints,
        lambda v: 300 * v["x_A"] + 450 * v["x_B"] - 20 * v["x_A_OT"] - 25 * v["x_B_OT"],
        optimum,
    )


_SCORERS: dict[int, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    4: _score_4,
    8: _score_8,
    9: _score_9,
    19: _score_19,
    20: _score_20,
    21: _score_21,
    25: _score_25,
    48: _score_48,
}


def score_solution(problem_id: int, solution: Mapping[str, Any]) -> dict[str, Any]:
    """Audit variables and business semantics without returning a target objective."""
    if problem_id not in _SCORERS:
        raise KeyError(f"unsupported IndustryOR problem: {problem_id}")
    return _SCORERS[problem_id](solution)


@dataclass(frozen=True)
class Problem:
    problem_id: int
    initial: str
    code: str
    solution: dict[str, Any]
    scorer: Callable[[Mapping[str, Any] | None], dict[str, Any]]


def list_problem_ids() -> tuple[int, ...]:
    return SUPPORTED_IDS


def load_problem(problem_id: int) -> Problem:
    """Load only initial/code/solution/scorer; no reference objective is exposed."""
    if problem_id not in SUPPORTED_IDS:
        raise KeyError(f"unsupported IndustryOR problem: {problem_id}")
    directory = WORK_ROOT / f"prob_{problem_id:03d}"
    solution = json.loads((directory / "solution.json").read_text(encoding="utf-8"))

    def scorer(candidate: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return score_solution(problem_id, solution if candidate is None else candidate)

    return Problem(
        problem_id=problem_id,
        initial=(directory / "initial.py").read_text(encoding="utf-8"),
        code=(directory / "instrumented.py").read_text(encoding="utf-8"),
        solution=solution,
        scorer=scorer,
    )


def _variable_specs(problem_id: int) -> dict[str, dict[str, Any]]:
    def spec(domain: str, meaning: str, required: bool = True) -> dict[str, Any]:
        return {"domain": domain, "meaning": meaning, "required_for_audit": required}

    if problem_id in (19, 21):
        unit = "chair orders" if problem_id == 19 else "table orders"
        return {
            **{f"x_{supplier}": spec("integer", f"{unit} from {supplier}") for supplier in "ABC"},
            "y_A": spec("binary", "whether supplier A is used"),
            "y_B": spec("binary", "whether supplier B is used"),
        }
    if problem_id == 20:
        names = ("robots", "model cars", "building blocks", "dolls")
        return {
            **{f"x{i}": spec("integer", f"quantity of {name}") for i, name in enumerate(names, 1)},
            **{f"y{i}": spec("binary", f"whether {name} are manufactured") for i, name in enumerate(names, 1)},
        }
    if problem_id == 9:
        names = ("trucks", "airplanes", "boats", "trains")
        return {
            **{f"x{i}": spec("integer", f"quantity of {name}") for i, name in enumerate(names, 1)},
            "y1": spec("binary", "whether trucks are manufactured"),
            "y2": spec("binary", "whether boats are manufactured"),
        }
    if problem_id == 4:
        return {
            "x_cows": spec("integer", "number of cows"),
            "x_sheep": spec("integer", "number of sheep"),
            "x_chickens": spec("integer", "number of chickens"),
        }
    if problem_id == 8:
        return {
            f"x_{i}_{j}": spec("binary", f"worker index {i} assigned to task index {j}; both zero-based")
            for i in range(5)
            for j in range(4)
        }
    if problem_id == 25:
        meanings = (
            "option 1 invested at start of year 1",
            "option 2 invested at start of year 1",
            "option 1 invested at start of year 2",
            "option 2 invested at start of year 2",
            "option 1 invested at start of year 3",
        )
        return {f"x{i}": spec("continuous", meaning) for i, meaning in enumerate(meanings, 1)}
    if problem_id == 48:
        specs = {
            "x_A": spec("continuous", "total production of model A"),
            "x_B": spec("continuous", "total production of model B"),
            "x_A_OT": spec("continuous", "model A quantity produced in Process II overtime"),
            "x_B_OT": spec("continuous", "model B quantity produced in Process II overtime"),
            "y": spec("continuous", "initial model overtime hours; insufficient for profit attribution", False),
            "z": spec("binary", "initial model overtime indicator", False),
        }
        for name in ("d1_p", "d1_n", "d2A_p", "d2A_n", "d2B_p", "d2B_n", "d3I_p", "d3I_n", "d3II_p", "d3II_n"):
            specs[name] = spec("continuous", f"initial goal deviation auxiliary {name}", False)
        return specs
    raise KeyError(problem_id)


def _audit_method(problem_id: int) -> dict[str, Any]:
    methods = {
        4: "bounded exhaustive integer enumeration plus manure, count, and animal-limit checks",
        8: "enumeration of all 5P4 worker-to-task assignments plus binary assignment checks",
        9: "bounded integer enumeration with exact resource and production-logic checks",
        19: "bounded integer order enumeration; per-chair costs multiplied by chairs per order",
        20: "bounded integer quantity enumeration using ORThought's integer semantics",
        21: "bounded integer order enumeration; per-table costs multiplied by tables per order",
        25: "cash-flow audit including idle cash; independent maximum-growth bound over one- and two-year products",
        48: "ORThought per-product overtime LP when x_A_OT/x_B_OT exist; otherwise explicitly blocked",
    }
    return {
        "method": methods[problem_id],
        "optimality_target_returned_to_caller": False,
        "business_correct_requires": [
            "complete export from an optimal SCIP solve",
            "all mapped variable domains and business constraints pass",
            "business objective recomputed from variables is independently optimal",
            "reported model objective equals the recomputed business objective",
        ],
    }


def _boundary_record(problem_id: int) -> dict[str, Any]:
    specific = {
        19: ["A business-optimal order vector can still fail if the reported objective uses cost per order instead of cost per chair."],
        20: ["Integer quantities follow ORThought model.txt; the question alone does not explicitly state integrality."],
        21: ["A business-optimal order vector can still fail if the reported objective uses cost per order instead of cost per table."],
        25: ["Terminal wealth includes uninvested cash; option returns are principal plus profit, following ORThought code.py."],
        48: [
            "The initial model is not audit-qualified because per-product overtime quantities are absent.",
            "ORThought model.txt is used for the optional repaired LP audit; its code.py has a conflicting Process II regular-capacity constraint and is not treated as executable truth.",
        ],
        4: [],
        8: ["Worker and task indices in variable names are zero-based."],
        9: ["Auxiliary indicators are checked against positive production, following ORThought linking semantics."],
    }
    return {
        "schema_version": "industryor.audit_boundaries.v1",
        "problem_id": problem_id,
        "absolute_tolerance": ABS_TOL,
        "objective_relative_tolerance": OBJ_REL_TOL,
        "public_answer_used_for_grading": False,
        "reference_objective_returned": False,
        "known_boundaries": specific[problem_id],
        "export_failure_policy": "Missing, incomplete, non-finite, or non-optimal exports cannot be business_correct.",
    }


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _execute(code: str, directory: Path, timeout: int, source_hash: str) -> dict[str, Any]:
    script = directory / "instrumented.py"
    solution_path = directory / "solution.json"
    if solution_path.exists():
        solution_path.unlink()
    started = time.time()
    stdout = ""
    stderr = ""
    return_code = None
    try:
        completed = subprocess.run(
            [EXEC_PYTHON, str(script)],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout, stderr = completed.stdout, completed.stderr
        return_code = completed.returncode
        exec_status = "ok" if return_code == 0 else "crash"
    except subprocess.TimeoutExpired as exc:
        stdout = _timeout_text(exc.stdout)
        stderr = _timeout_text(exc.stderr)
        exec_status = "timeout"
    wall_s = time.time() - started
    (directory / "stdout.txt").write_text(stdout, encoding="utf-8")
    (directory / "stderr.txt").write_text(stderr, encoding="utf-8")
    status_match = re.search(r"^status:\s*(\S+)", stdout, re.MULTILINE)
    objective_match = re.search(r"^objective:\s*([-+0-9.eE]+)", stdout, re.MULTILINE)
    exported = None
    if solution_path.exists():
        try:
            exported = json.loads(solution_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            exported = None
    return {
        "schema_version": "industryor.execution.v1",
        "python": EXEC_PYTHON,
        "engine": "PySCIPOpt/SCIP",
        "timeout_seconds": timeout,
        "exec_status": exec_status,
        "return_code": return_code,
        "solver_status": status_match.group(1) if status_match else None,
        "printed_objective": float(objective_match.group(1)) if objective_match else None,
        "wall_seconds": round(wall_s, 3),
        "initial_sha256": source_hash,
        "instrumented_sha256": _sha256_file(script),
        "solution_exists": solution_path.exists(),
        "export_complete": bool(
            isinstance(exported, dict)
            and isinstance(exported.get("export"), dict)
            and exported["export"].get("complete") is True
        ),
        "stdout_artifact": "stdout.txt",
        "stderr_artifact": "stderr.txt",
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _environment_metadata() -> dict[str, Any]:
    command = (
        "import pyscipopt; "
        "from pyscipopt import Model; "
        "print(pyscipopt.__version__); "
        "print(Model().version())"
    )
    completed = subprocess.run([EXEC_PYTHON, "-c", command], capture_output=True, text=True, timeout=30)
    lines = completed.stdout.splitlines()
    if completed.returncode != 0 or len(lines) < 2:
        raise RuntimeError(f"cannot verify PySCIPOpt/SCIP environment: {completed.stderr[-500:]}")
    return {"python": EXEC_PYTHON, "pyscipopt": lines[0].strip(), "scip": lines[1].strip()}


def build_artifacts(problem_ids: tuple[int, ...] = SUPPORTED_IDS, timeout: int = 120) -> dict[str, Any]:
    rows = {row["id"]: row for row in json.loads(DATASET.read_text(encoding="utf-8"))}
    environment = _environment_metadata()
    entries = []
    for problem_id in problem_ids:
        if problem_id not in SUPPORTED_IDS:
            raise ValueError(f"unsupported requested id: {problem_id}")
        row = rows[problem_id]
        source_path = _source_path(problem_id)
        source_bytes = source_path.read_bytes()
        source = source_bytes.decode("utf-8")
        source_hash = _sha256_bytes(source_bytes)
        instrumented = instrument_code(source)
        directory = WORK_ROOT / f"prob_{problem_id:03d}"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "initial.py").write_bytes(source_bytes)
        (directory / "instrumented.py").write_text(instrumented, encoding="utf-8")
        execution = _execute(instrumented, directory, timeout, source_hash)
        _write_json(directory / "execution.json", execution)
        _write_json(directory / "boundaries.json", _boundary_record(problem_id))

        solution_path = directory / "solution.json"
        failure_path = directory / "export_failure.json"
        if failure_path.exists():
            failure_path.unlink()
        try:
            solution = json.loads(solution_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            solution = {}
            _write_json(failure_path, {"problem_id": problem_id, "error": f"{type(exc).__name__}: {exc}"})
            score = _base_result(problem_id)
            score["audit_status"] = "invalid_solution"
            score["violations"].append("solution export could not be loaded")
        else:
            export = solution.get("export") if isinstance(solution, dict) else None
            if not isinstance(export, dict) or export.get("complete") is not True:
                error = export.get("error") if isinstance(export, dict) else None
                _write_json(failure_path, {
                    "problem_id": problem_id,
                    "error": error or "export incomplete",
                    "solver_status": solution.get("solver_status") if isinstance(solution, dict) else None,
                })
            score = score_solution(problem_id, solution)
        _write_json(directory / "score.json", score)

        raw_variables = solution.get("variables") if isinstance(solution, dict) else None
        exported_names = set(raw_variables) if isinstance(raw_variables, dict) else set()
        variable_mapping = copy.deepcopy(_variable_specs(problem_id))
        for name, variable_spec in variable_mapping.items():
            variable_spec["observed_in_initial_export"] = name in exported_names
        qualified = bool(
            execution["exec_status"] == "ok"
            and execution["export_complete"]
            and score["audit_status"] == "complete"
        )
        reference_dir = _reference_dir(problem_id)
        reference_files = {}
        for filename in ("question.txt", "model.txt", "code.py"):
            path = reference_dir / filename
            reference_files[filename] = {
                "path": str(path.relative_to(ROOT)),
                "sha256": _sha256_file(path),
            }
        artifact_names = ("initial.py", "instrumented.py", "solution.json", "execution.json", "stdout.txt", "stderr.txt", "score.json", "boundaries.json")
        entry = {
            "id": problem_id,
            "cohort": "natural_objective_error" if problem_id in ERROR_IDS else "known_correct_control",
            "question": row["en_question"],
            "question_sha256": _sha256_text(row["en_question"]),
            "initial": {
                "source_path": str(source_path.relative_to(ROOT)),
                "sha256": source_hash,
            },
            "instrumented": {
                "method": "AST-validated fixed append-only exporter",
                "sha256": _sha256_text(instrumented),
                "business_statements_rewritten": False,
                "public_answer_injected": False,
            },
            "solution_schema": {
                "name": SOLUTION_SCHEMA,
                "variables": "flat object keyed by PySCIPOpt variable name; finite numeric values including zeros",
                "variable_types": "flat object keyed like variables",
                "objective": "candidate model objective, not a reference objective",
                "export": "complete boolean and captured error",
            },
            "variable_mapping": variable_mapping,
            "sources": {
                "industryor_question": {
                    "path": str(DATASET.relative_to(ROOT)),
                    "record_id": problem_id,
                    "dataset_sha256": _sha256_file(DATASET),
                },
                "orthought": reference_files,
            },
            "audit": {
                **_audit_method(problem_id),
                "qualified": qualified,
                "audit_status": score["audit_status"],
                "business_correct": score["business_correct"],
                "blocking_reasons": score["blocking_reasons"],
            },
            "artifacts": {
                name: str((directory / name).relative_to(ROOT))
                for name in artifact_names
                if (directory / name).exists()
            },
        }
        entries.append(entry)
        print(
            f"[{problem_id}] exec={execution['exec_status']} "
            f"solver={execution['solver_status']} export={execution['export_complete']} "
            f"audit={score['audit_status']} business_correct={score['business_correct']}"
        )

    qualified_ids = [entry["id"] for entry in entries if entry["audit"]["qualified"]]
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "execution_environment": environment,
        "problem_ids": [entry["id"] for entry in entries],
        "qualification": {
            "meaning": "A reproducible variable-level business audit exists; this is independent of whether the initial program is correct.",
            "minimum_required": 6,
            "count": len(qualified_ids),
            "qualified_ids": qualified_ids,
            "blocked_ids": [entry["id"] for entry in entries if not entry["audit"]["qualified"]],
        },
        "problems": entries,
    }
    _write_json(MANIFEST, manifest)
    print(f"qualified={len(qualified_ids)} ids={qualified_ids}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", type=int, nargs="+", default=list(SUPPORTED_IDS))
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    ids = tuple(dict.fromkeys(args.ids))
    manifest = build_artifacts(ids, args.timeout)
    if manifest["qualification"]["count"] < min(6, len(ids)):
        raise SystemExit(2)


if __name__ == "__main__":
    main()

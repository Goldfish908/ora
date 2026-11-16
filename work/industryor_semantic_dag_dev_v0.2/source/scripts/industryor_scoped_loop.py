#!/usr/bin/env python3
"""Shared-initial scoped-asset repair controls on independently audited IndustryOR cases."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.acceptance import can_accept
from ora_agent.repair_controller import ProgressController
from ora_agent.scoped_assets import compile_asset, load_asset, validate_asset
from ora_agent.scoped_ir import evaluate_spec
from scripts.industryor_next_stage import load_problem
from scripts.m1_pilot import run_code
from scripts.scoped_ir_e2e import current_cell
from scripts.scoped_ir_gate import gate

IDS = (19, 20, 21, 25, 4, 8, 9)
POLICIES = ("no_repair", "fixed", "progress")
CASES = {
    19: {"per_order": {"x_A": 15, "x_B": 10, "x_C": 10},
         "unit_cost": {"x_A": 50, "x_B": 45, "x_C": 40},
         "minimum": 100, "maximum": 500, "minimum_b_if_a": 1},
    20: {"profit": (15, 8, 12, 5), "plastic": (30, 10, 20, 15),
         "electronics": (8, 5, 3, 2), "plastic_limit": 1200,
         "electronics_limit": 800, "upper_bounds": (40, 120, 60, 80)},
    21: {"per_order": {"x_A": 20, "x_B": 15, "x_C": 15},
         "unit_cost": {"x_A": 120, "x_B": 110, "x_C": 100},
         "minimum": 150, "maximum": 600, "minimum_b_if_a": 2},
}
MANIFEST = ROOT / "assets/industryor_next_stage/manifest.json"
TEMPLATE = ROOT / "assets/scoped_ir/objective_recompute_v0.1.json"
INDICATOR_TEMPLATE = ROOT / "assets/scoped_ir/indicator_link_v0.1.json"
DOMAIN_TEMPLATE = ROOT / "assets/scoped_ir/variable_domain_v0.1.json"


def source_reference(problem_id: int, filename: str, markers: tuple[str, ...]) -> dict:
    manifest = json.loads(MANIFEST.read_text())
    row = next(item for item in manifest["problems"] if item["id"] == problem_id)
    reference = row["sources"]["orthought"][filename]
    text = (ROOT / reference["path"]).read_text()
    lines = text.splitlines()
    indices = []
    for marker in markers:
        matches = [i for i, line in enumerate(lines) if marker in line]
        if len(matches) != 1:
            raise ValueError(f"independent evidence is not unique for {problem_id}: {marker}")
        indices.append(matches[0])
    span = "\n".join(lines[min(indices):max(indices) + 1])
    return {"type": "independent_reference", "reference": reference["path"],
            "text": text, "span": span, "sha256": hashlib.sha256(text.encode()).hexdigest()}


def domain_binding_for(problem_id: int, question: str) -> dict:
    if problem_id != 20:
        return {}
    evidence = source_reference(problem_id, "model.txt", ("Integer variable,",))
    return {"invariant_id": f"industryor_{problem_id}_integer_quantity",
            "source_span": question, "source_evidence": evidence,
            "terms": [{"path": f"solution.variables.x{i}"} for i in range(1, 5)]}


def indicator_binding_for(problem_id: int, question: str) -> dict:
    if problem_id == 9:
        evidence = source_reference(problem_id, "model.txt",
                                    ("x_{Trucks} \\leq M", "x_{Boats} \\leq M"))
        pairs = [("x1", "y1", 890 // 12), ("x3", "y2", 890 // 15)]
        return {"links": [
            {"invariant_id": f"industryor_9_{quantity}_indicator",
             "quantity_path": f"solution.variables.{quantity}",
             "indicator_path": f"solution.variables.{indicator}", "upper_bound": upper,
             "source_span": question, "source_evidence": evidence}
            for quantity, indicator, upper in pairs]}
    case = CASES[problem_id]
    if problem_id == 20:
        evidence = source_reference(
            problem_id, "code.py", ("# (use_toy[t] == 1) => (qty[t] >= 1)",
                                    'f"Link_use_{t}_if_zero")'))
        pairs = [(f"x{i}", f"y{i}", case["upper_bounds"][i - 1]) for i in range(1, 5)]
    else:
        if problem_id not in (19, 21):
            raise ValueError(f"no independently supported indicator binding for {problem_id}")
        reference = source_reference(problem_id, "code.py", ("Link_use_B_if_zero",))
        text = reference["text"]
        lines = text.splitlines()
        targets = {
            "A": ("# (use_A == 1) => (orders_A >= 1)",
                  "# (use_A == 0) => (orders_A == 0)"),
            "B": ('model.addConstr((use_B == 1) >> (orders_B >= 1), "Link_use_B_if_one")',
                  'model.addConstr((use_B == 0) >> (orders_B == 0), "Link_use_B_if_zero")'),
        }
        pairs = []
        for suffix, (first, second) in targets.items():
            index = next(i for i, line in enumerate(lines) if line.strip() == first)
            if lines[index + 1].strip() != second:
                raise ValueError(f"independent indicator evidence is incomplete for {problem_id}/{suffix}")
            quantity = f"x_{suffix}"
            evidence = dict(reference, span="\n".join(lines[index:index + 2]))
            pairs.append((quantity, f"y_{suffix}",
                          case["maximum"] // case["per_order"][quantity], evidence))
        return {"links": [
            {"invariant_id": f"industryor_{problem_id}_{quantity}_indicator",
             "quantity_path": f"solution.variables.{quantity}",
             "indicator_path": f"solution.variables.{indicator}", "upper_bound": upper,
             "source_span": question, "source_evidence": evidence}
            for quantity, indicator, upper, evidence in pairs]}
    return {"links": [
        {"invariant_id": f"industryor_{problem_id}_{quantity}_indicator",
         "quantity_path": f"solution.variables.{quantity}",
         "indicator_path": f"solution.variables.{indicator}", "upper_bound": upper,
         "source_span": question, "source_evidence": evidence}
        for quantity, indicator, upper in pairs]}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def binding_for(problem_id: int, question: str) -> dict:
    if problem_id == 9:
        coefficients = (5, 10, 8, 7)
        return {"invariant_id": "industryor_9_business_objective",
                "source_span": question,
                "terms": [{"path": f"solution.variables.x{i}", "coefficient": coefficient}
                          for i, coefficient in enumerate(coefficients, 1)]}
    case = CASES[problem_id]
    if problem_id == 20:
        end = question.index("How many types of toys")
        return {"invariant_id": f"industryor_{problem_id}_business_objective",
                "source_span": question[:end].strip(),
                "terms": [{"path": f"solution.variables.x{i}", "coefficient": coefficient}
                          for i, coefficient in enumerate(case["profit"], 1)]}
    start = question.index("The cost of ordering")
    marker = "The number of orders must be an integer."
    end = question.index(marker) + len(marker)
    return {
        "invariant_id": f"industryor_{problem_id}_business_objective",
        "source_span": question[start:end],
        "terms": [{"path": f"solution.variables.{name}",
                   "coefficient": case["unit_cost"][name] * case["per_order"][name]}
                  for name in ("x_A", "x_B", "x_C")],
    }


def independent_toy_clean(initial_solution: dict) -> dict:
    from pyscipopt import Model

    case = CASES[20]
    model = Model()
    model.hideOutput()
    model.setRealParam("limits/time", 60)
    x = [model.addVar(f"x{i}", lb=0, vtype="I") for i in range(1, 5)]
    y = [model.addVar(f"y{i}", vtype="B") for i in range(1, 5)]
    model.addCons(sum(case["plastic"][i] * x[i] for i in range(4)) <= case["plastic_limit"])
    model.addCons(sum(case["electronics"][i] * x[i] for i in range(4)) <= case["electronics_limit"])
    for i in range(4):
        model.addCons(y[i] <= x[i])
        model.addCons(x[i] <= case["upper_bounds"][i] * y[i])
    model.addCons(y[0] + y[3] <= 1)
    model.addCons(y[1] <= y[2])
    model.addCons(x[3] <= x[1])
    model.setObjective(sum(case["profit"][i] * x[i] for i in range(4)), "maximize")
    model.optimize()
    if model.getStatus() != "optimal" or model.getNSols() < 1:
        raise ValueError("independent toy reference did not solve to optimality")
    solution = dict(initial_solution)
    solution["variables"] = {var.name: float(model.getVal(var)) for var in x + y}
    solution["objective"] = float(model.getObjVal())
    return solution


def independent_clean(problem_id: int, initial_solution: dict) -> dict:
    if problem_id == 20:
        return independent_toy_clean(initial_solution)
    case = CASES[problem_id]
    per_order = case["per_order"]
    best = None
    for a in range(case["maximum"] // per_order["x_A"] + 1):
        for b in range(case["maximum"] // per_order["x_B"] + 1):
            for c in range(case["maximum"] // per_order["x_C"] + 1):
                quantities = {"x_A": a, "x_B": b, "x_C": c}
                items = sum(per_order[name] * value for name, value in quantities.items())
                if not case["minimum"] <= items <= case["maximum"]:
                    continue
                if a > 0 and b < case["minimum_b_if_a"]:
                    continue
                if b > 0 and c < 1:
                    continue
                objective = sum(case["unit_cost"][name] * per_order[name] * value
                                for name, value in quantities.items())
                if best is None or objective < best[0]:
                    best = objective, quantities
    if best is None:
        raise ValueError(f"no feasible independent solution for {problem_id}")
    objective, quantities = best
    solution = dict(initial_solution)
    solution["variables"] = {**quantities, "y_A": float(quantities["x_A"] > 0),
                             "y_B": float(quantities["x_B"] > 0)}
    solution["objective"] = float(objective)
    return solution


def toy_validation_cells(initial_solution: dict) -> list[dict]:
    clean = independent_clean(20, initial_solution)

    def toy_solution(x1: float, y1: float) -> dict:
        solution = dict(clean)
        solution["variables"] = {name: 0.0 for name in clean["variables"]}
        solution["variables"].update(x1=x1, y1=y1)
        solution["objective"] = 15 * x1
        return solution

    wrong_objective = dict(clean)
    wrong_objective["objective"] = clean["objective"] + 1
    return [
        {"key": "independent_clean", "wrong": False, "mutation": "reference_feasible_optimum",
         "reference_violations": [], "solution": clean},
        {"key": "natural_initial", "wrong": True, "mutation": "natural_initial_error",
         "reference_violations": ["domain_integer", "indicator_link"], "solution": initial_solution},
        {"key": "wrong_objective", "wrong": True, "mutation": "objective_mismatch",
         "reference_violations": ["business_objective"], "solution": wrong_objective},
        {"key": "clean_zero", "wrong": False, "mutation": "feasible_zero_production",
         "reference_violations": [], "solution": toy_solution(0.0, 0.0)},
        {"key": "clean_positive", "wrong": False, "mutation": "feasible_positive_indicator",
         "reference_violations": [], "solution": toy_solution(1.0, 1.0)},
        {"key": "wrong_domain", "wrong": True, "mutation": "fractional_toy_quantity",
         "reference_violations": ["domain_integer"], "solution": toy_solution(0.5, 1.0)},
        {"key": "wrong_indicator_off", "wrong": True, "mutation": "zero_quantity_indicator_one",
         "reference_violations": ["indicator_link"], "solution": toy_solution(0.0, 1.0)},
        {"key": "wrong_indicator_on", "wrong": True, "mutation": "positive_quantity_indicator_zero",
         "reference_violations": ["indicator_link"], "solution": toy_solution(1.0, 0.0)},
    ]


def validation_cells(problem_id: int, initial_solution: dict) -> list[dict]:
    if problem_id == 20:
        return toy_validation_cells(initial_solution)
    clean = independent_clean(problem_id, initial_solution)
    wrong_objective = dict(clean)
    wrong_objective["objective"] = clean["objective"] + 1
    case = CASES[problem_id]
    coefficient_b = case["unit_cost"]["x_B"] * case["per_order"]["x_B"]
    positive = dict(clean)
    positive["variables"] = dict(clean["variables"])
    positive["variables"]["x_B"] += 1
    positive["variables"]["y_B"] = 1.0
    positive["objective"] = clean["objective"] + coefficient_b
    wrong_off = dict(positive)
    wrong_off["variables"] = dict(positive["variables"])
    wrong_off["variables"]["x_B"] = 0.0
    wrong_off["objective"] = positive["objective"] - coefficient_b
    wrong_on = dict(positive)
    wrong_on["variables"] = dict(positive["variables"])
    wrong_on["variables"]["y_B"] = 0.0
    return [
        {"key": "independent_clean", "wrong": False, "mutation": "reference_feasible_optimum",
         "reference_violations": [], "solution": clean},
        {"key": "natural_initial", "wrong": True, "mutation": "natural_initial_error",
         "reference_violations": ["business_objective"], "solution": initial_solution},
        {"key": "wrong_objective", "wrong": True, "mutation": "objective_mismatch",
         "reference_violations": ["business_objective"], "solution": wrong_objective},
        {"key": "clean_positive", "wrong": False, "mutation": "feasible_positive_indicator",
         "reference_violations": [], "solution": positive},
        {"key": "wrong_indicator_off", "wrong": True, "mutation": "zero_quantity_indicator_one",
         "reference_violations": ["indicator_link"], "solution": wrong_off},
        {"key": "wrong_indicator_on", "wrong": True, "mutation": "positive_quantity_indicator_zero",
         "reference_violations": ["indicator_link"], "solution": wrong_on},
    ]


def _local_variable(path: str, aliases: dict | None = None) -> str:
    if not path.startswith("solution.variables."):
        raise ValueError(f"invalid solution variable path: {path}")
    name = path.rsplit(".", 1)[-1]
    if "/" in name:
        raise ValueError(f"invalid solution variable path: {path}")
    return (aliases or {}).get(name, name)


def _declared_variables(tree: ast.AST) -> set[str]:
    declared = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "addVar"):
            declared.update(target.id for target in node.targets if isinstance(target, ast.Name))
    return declared


def repair_objective(code: str, binding: dict, aliases: dict | None = None) -> str:
    tree = ast.parse(code)
    declared = _declared_variables(tree)
    names = []
    expressions = []
    for term in binding["terms"]:
        name = _local_variable(term["path"], aliases)
        if name not in declared and name not in (aliases or {}).values():
            raise ValueError(f"no matching PySCIPOpt variable for {term['path']}")
        if name in names:
            raise ValueError(f"duplicate objective variable: {name}")
        names.append(name)
        expressions.append(f"{term.get('coefficient', 1)} * {name}")
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "setObjective"]
    if len(calls) != 1 or not calls[0].args:
        raise ValueError("expected exactly one setObjective call with an expression")
    calls[0].args[0] = ast.parse(" + ".join(expressions), mode="eval").body
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def repair_indicator_links(code: str, binding: dict, aliases: dict | None = None) -> str:
    tree = ast.parse(code)
    declared = _declared_variables(tree)
    comparisons = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "addCons" and node.args):
            comparisons.add(ast.unparse(node.args[0]))
    optimize = next((node for node in tree.body if isinstance(node, ast.Expr)
                     and isinstance(node.value, ast.Call)
                     and isinstance(node.value.func, ast.Attribute)
                     and node.value.func.attr == "optimize"), None)
    if optimize is None:
        raise ValueError("indicator repair requires a top-level optimize call")
    model_name = ast.unparse(optimize.value.func.value)
    declarations = []
    additions = []
    for link in binding["links"]:
        quantity = _local_variable(link["quantity_path"], aliases)
        indicator = _local_variable(link["indicator_path"], aliases)
        if quantity not in declared and quantity not in (aliases or {}).values():
            raise ValueError(f"missing indicator variables: {quantity}, {indicator}")
        if indicator not in declared:
            if indicator not in (aliases or {}).values():
                raise ValueError(f"missing indicator variables: {quantity}, {indicator}")
            if indicator.isidentifier():
                declarations.append(ast.parse(
                    f"{indicator} = {model_name}.addVar({indicator!r}, vtype='B')").body[0])
                declared.add(indicator)
        rule = link["invariant_id"]
        for suffix, expression in (
                ("off", f"{indicator} <= {quantity}"),
                ("on", f"{quantity} <= {link['upper_bound']} * {indicator}")):
            normalized = ast.unparse(ast.parse(expression, mode="eval").body)
            if normalized not in comparisons:
                statement = f"{model_name}.addCons({expression}, {rule + '_' + suffix!r})"
                additions.append(ast.parse(statement).body[0])
                comparisons.add(normalized)
    if declarations or additions:
        index = tree.body.index(optimize)
        tree.body[index:index] = declarations + additions
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def repair_integer_variables(code: str, binding: dict, aliases: dict | None = None) -> str:
    tree = ast.parse(code)
    assignments = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "addVar"):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)
    for term in binding["terms"]:
        path = term["path"]
        try:
            name = _local_variable(path, aliases)
        except ValueError as exc:
            raise ValueError(f"invalid integer variable path: {path}") from exc
        calls = assignments.get(name, [])
        if len(calls) != 1:
            raise ValueError(f"expected one PySCIPOpt declaration for {path}")
        call = calls[0]
        for keyword in call.keywords:
            if keyword.arg == "vtype":
                keyword.value = ast.Constant("I")
                break
        else:
            call.keywords.append(ast.keyword(arg="vtype", value=ast.Constant("I")))
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def repair_model(code: str, objective_binding: dict, indicator_binding: dict,
                 domain_binding: dict | None = None, aliases: dict | None = None) -> str:
    patched = repair_objective(code, objective_binding, aliases)
    patched = repair_indicator_links(patched, indicator_binding, aliases)
    if domain_binding:
        patched = repair_integer_variables(patched, domain_binding, aliases)
    return patched


def execute(code: str, sandbox: Path) -> tuple[dict, dict | None]:
    record = run_code(code, sandbox)
    path = sandbox / "solution.json"
    solution = json.loads(path.read_text()) if path.exists() else None
    return record, solution


def run_problem(problem_id: int, policy: str, outdir: Path, max_repairs: int = 2) -> dict:
    if policy not in POLICIES:
        raise ValueError(f"unsupported policy: {policy}")
    manifest = json.loads(MANIFEST.read_text())
    row = next(item for item in manifest["problems"] if item["id"] == problem_id)
    problem = load_problem(problem_id)
    initial_score = problem.scorer(problem.solution)
    initial = {"code": problem.code, "solution": problem.solution,
               "record": json.loads((ROOT / row["artifacts"]["execution.json"]).read_text())}
    initial["record"]["stderr_tail"] = ""
    case_dir = outdir / f"prob_{problem_id:03d}" / policy
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "initial.py").write_text(problem.code)
    if problem_id not in CASES:
        result = {"id": problem_id, "policy": policy, "status": "not_applicable",
                  "initial_score": initial_score, "final_score": initial_score,
                  "initial_code": problem.code, "final_code": problem.code,
                  "history": [], "improved": False, "harmed_win": False,
                  "semantic_recovery": False, "accepted_but_business_incorrect": False,
                  "llm_calls": 0, "tokens": 0, "solver_runs_this_run": 0}
        (case_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
        return result

    question = row["question"]
    binding = binding_for(problem_id, question)
    template = load_asset(TEMPLATE)
    if validate_asset(template)["status"] != "validated":
        raise ValueError("objective template failed its mechanism validation")
    indicator_binding = indicator_binding_for(problem_id, question)
    indicator_template = load_asset(INDICATOR_TEMPLATE)
    if validate_asset(indicator_template)["status"] != "validated":
        raise ValueError("indicator template failed its mechanism validation")
    spec = compile_asset(template, binding)
    spec["invariants"].extend(compile_asset(indicator_template, indicator_binding)["invariants"])
    domain_binding = domain_binding_for(problem_id, question)
    if domain_binding:
        domain_template = load_asset(DOMAIN_TEMPLATE)
        if validate_asset(domain_template)["status"] != "validated":
            raise ValueError("integer-domain template failed its mechanism validation")
        spec["invariants"].extend(compile_asset(domain_template, domain_binding)["invariants"])
    cells = validation_cells(problem_id, problem.solution)
    if not problem.scorer(cells[0]["solution"])["business_correct"]:
        raise ValueError(f"independent clean reference failed scoring for {problem_id}")
    for cell in cells[1:]:
        if cell["wrong"] and problem.scorer(cell["solution"])["business_correct"]:
            raise ValueError(f"wrong counterexample was independently accepted: {cell['key']}")
    if problem_id == 20:
        positive_score = problem.scorer(cells[4]["solution"])
        if positive_score["violations"] != ["business objective is not independently optimal"]:
            raise ValueError("feasible positive indicator control has an unexpected violation")
    gate_result = gate(spec, question, cells, str(problem_id))
    checker_status = "accepted" if gate_result["accepted"] else "rejected"
    (case_dir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n")
    (case_dir / "gate.json").write_text(json.dumps(gate_result, ensure_ascii=False, indent=1) + "\n")
    current = initial
    accepted = None
    accepted_round = None
    history = []
    controller = ProgressController() if policy == "progress" else None
    stop_reason = None
    transforms = 0
    solver_runs = 0
    if policy != "no_repair":
        for round_idx in range(max_repairs + 1):
            audit = evaluate_spec(spec, question, [current_cell(current["solution"])],
                                  str(problem_id))["records"][0]
            history.append({"round": round_idx, "audit": audit,
                            "code_sha256": hashlib.sha256(current["code"].encode()).hexdigest(),
                            "checker_status": checker_status})
            if can_accept(audit, checker_status):
                accepted = current
                accepted_round = round_idx
                stop_reason = "accepted"
                break
            if checker_status == "rejected":
                stop_reason = "repair_checker_required"
                break
            if not audit.get("fired"):
                stop_reason = audit.get("status") or "not_accepted"
                break
            if round_idx >= max_repairs:
                stop_reason = "budget_exhausted"
                break
            action = "local_patch"
            decision = None
            if controller is not None:
                decision = controller.decide(current["code"], current["record"], audit,
                                             max_repairs - round_idx, checker_status)
                action = decision.action
                history[-1]["controller_decision"] = decision.__dict__
                if action == "stop":
                    stop_reason = decision.reason
                    break
                if action != "local_patch":
                    stop_reason = action + "_unavailable"
                    break
            code = repair_model(current["code"], binding, indicator_binding, domain_binding)
            before_hash = hashlib.sha256(current["code"].encode()).hexdigest()
            after_hash = hashlib.sha256(code.encode()).hexdigest()
            if code == current["code"]:
                record, solution = current["record"], current["solution"]
            else:
                record, solution = execute(code, case_dir / f"round_{round_idx + 1}")
                solver_runs += 1
            transforms += 1
            history[-1]["action"] = {"name": action, "before_sha256": before_hash,
                                     "after_sha256": after_hash, "llm_calls": 0}
            if controller is not None:
                controller.record(decision, code)
            current = {"code": code, "solution": solution, "record": record}
    final = accepted or initial
    final_score = problem.scorer(final["solution"])
    last_score = problem.scorer(current["solution"])
    result = {
        "id": problem_id, "policy": policy, "status": "completed",
        "binding": binding, "indicator_binding": indicator_binding,
        "domain_binding": domain_binding,
        "initial_score": initial_score, "final_score": final_score,
        "last_candidate_score": last_score, "history": history,
        "initial_code": initial["code"], "final_code": final["code"],
        "accepted_round": accepted_round, "accepted": accepted is not None,
        "baseline_fallback": accepted is None, "stop_reason": stop_reason,
        "controller_trace": controller.trace() if controller else [],
        "no_progress_attempts": controller.no_progress_count if controller else None,
        "deterministic_transforms": transforms, "solver_runs_this_run": solver_runs,
        "llm_calls": 0, "tokens": 0,
        "improved": not initial_score["business_correct"] and final_score["business_correct"],
        "harmed_win": initial_score["business_correct"] and not final_score["business_correct"],
        "semantic_recovery": bool(accepted_round not in (None, 0)
                                  and history and history[0]["audit"].get("fired")
                                  and not initial_score["business_correct"]
                                  and final_score["business_correct"]),
        "accepted_but_business_incorrect": bool(accepted is not None
                                                and not final_score["business_correct"]),
    }
    (case_dir / "final.py").write_text(final["code"])
    (case_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    return result


def summarize(results: list[dict], policy: str) -> dict:
    rows = [row for row in results if row["policy"] == policy]
    return {
        "n": len(rows),
        "initial_business_correct": sum(row["initial_score"]["business_correct"] for row in rows),
        "final_business_correct": sum(row["final_score"]["business_correct"] for row in rows),
        "improved": sum(row["improved"] for row in rows),
        "semantic_recoveries": sum(row["semantic_recovery"] for row in rows),
        "harmed_win": sum(row["harmed_win"] for row in rows),
        "accepted_but_business_incorrect": sum(row["accepted_but_business_incorrect"] for row in rows),
        "not_applicable": sum(row["status"] == "not_applicable" for row in rows),
        "baseline_fallback": sum(row.get("baseline_fallback", False) for row in rows),
        "llm_calls": sum(row["llm_calls"] for row in rows),
        "tokens": sum(row["tokens"] for row in rows),
        "solver_runs_this_run": sum(row["solver_runs_this_run"] for row in rows),
        "no_progress_attempts": sum(row.get("no_progress_attempts") or 0 for row in rows),
    }


def run_all(outdir: Path, ids=IDS, resume: bool = False, max_repairs: int = 2) -> dict:
    ids = tuple(ids)
    implementation_paths = [Path(__file__), ROOT / "ora_agent/acceptance.py",
                            ROOT / "ora_agent/repair_controller.py",
                            ROOT / "ora_agent/scoped_ir.py", ROOT / "ora_agent/scoped_assets.py",
                            ROOT / "scripts/industryor_next_stage.py"]
    config = {"schema_version": "industryor.scoped_loop.v0.6", "ids": list(ids),
              "policies": list(POLICIES), "max_repairs": max_repairs,
              "input_manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
              "template_sha256": hashlib.sha256(TEMPLATE.read_bytes()).hexdigest(),
              "indicator_template_sha256": hashlib.sha256(INDICATOR_TEMPLATE.read_bytes()).hexdigest(),
              "domain_template_sha256": hashlib.sha256(DOMAIN_TEMPLATE.read_bytes()).hexdigest(),
              "implementation_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                        for path in implementation_paths},
              "exposure": "historical_development_not_frozen"}
    analysis_path = outdir / "analysis.json"
    if analysis_path.exists():
        previous = json.loads(analysis_path.read_text())
        if resume and previous["run_config"] == config:
            return previous
        raise ValueError("existing analysis has a different configuration; choose a new output directory")
    outdir.mkdir(parents=True, exist_ok=True)
    results = [run_problem(problem_id, policy, outdir, max_repairs)
               for problem_id in ids for policy in POLICIES]
    analysis = {"run_config": config,
                "arms": {policy: summarize(results, policy) for policy in POLICIES},
                "results": results}
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=1) + "\n")
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", type=int, nargs="+", default=list(IDS))
    parser.add_argument("--out", default="work/industryor_scoped_loop_v0.6")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-repairs", type=int, default=2)
    args = parser.parse_args()
    if set(args.ids) - set(IDS):
        raise ValueError("requested an unregistered problem ID")
    analysis = run_all(ROOT / args.out, tuple(args.ids), args.resume, args.max_repairs)
    print(json.dumps(analysis["arms"], ensure_ascii=False, indent=1))
    if any(analysis["arms"][policy]["harmed_win"]
           or analysis["arms"][policy]["accepted_but_business_incorrect"] for policy in POLICIES):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

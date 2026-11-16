#!/usr/bin/env python3
"""Compile scalar NLP4LP expert formulations into independent reference audits."""
from __future__ import annotations

import argparse
import ast
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/external/ORThought/datasets/processed/NLP4LP/nlp4lp.csv"
SPLITS = ROOT / "data/memory_witness/nlp4lp"


def load_rows(split: str) -> list[dict]:
    ids = set((SPLITS / f"{split}.txt").read_text().splitlines())
    with DATA.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["id"] in ids]
    rows.sort(key=lambda r: r["id"])
    return rows


def calls(code: str, method: str) -> list[ast.Call]:
    out = []
    for node in ast.walk(ast.parse(code)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == method):
            out.append(node)
    return out


def evaluate(node: ast.AST, values: dict[str, float]):
    if isinstance(node, ast.Expression):
        return evaluate(node.body, values)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        value = values[node.id]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"non-scalar value for {node.id}")
        return float(value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = evaluate(node.operand, values)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left, right = evaluate(node.left, values), evaluate(node.right, values)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.Pow):
            return left ** right
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left = evaluate(node.left, values)
        right = evaluate(node.comparators[0], values)
        op = node.ops[0]
        if isinstance(op, ast.Lt):
            return left < right
        if isinstance(op, ast.LtE):
            return left <= right
        if isinstance(op, ast.Gt):
            return left > right
        if isinstance(op, ast.GtE):
            return left >= right
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = node.func.id
        if name not in {"abs", "min", "max", "sum", "round"}:
            raise TypeError(f"unsupported function {name}")
        args = [evaluate(a, values) for a in node.args]
        if name == "sum":
            return sum(args[0])
        functions = {"abs": abs, "min": min, "max": max, "round": round}
        return functions[name](*args)
    raise TypeError(f"unsupported expression {ast.dump(node)[:160]}")


def comparison(node: ast.AST, values: dict[str, float]) -> tuple[bool, float, float]:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        raise TypeError("constraint is not a single comparison")
    left = evaluate(node.left, values)
    right = evaluate(node.comparators[0], values)
    op = node.ops[0]
    tol = 1e-5 + 1e-6 * max(abs(left), abs(right), 1.0)
    if isinstance(op, ast.LtE):
        ok = left <= right + tol
    elif isinstance(op, ast.GtE):
        ok = left + tol >= right
    elif isinstance(op, ast.Eq):
        ok = math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-5)
    elif isinstance(op, ast.Lt):
        ok = left < right + tol
    elif isinstance(op, ast.Gt):
        ok = left + tol > right
    else:
        raise TypeError("unsupported comparison")
    return ok, left, right


def constraints(row: dict) -> list[dict]:
    info = json.loads(row["problem_info"])
    out = []
    for raw in info["constraints"]:
        code = raw.get("code", {}).get("gurobipy", "")
        for call in calls(code, "addConstr"):
            if not call.args:
                continue
            out.append({"rule": f"C{len(out) + 1:02d}",
                        "description": raw.get("description", ""),
                        "expression": call.args[0]})
    return out


def objective(row: dict) -> tuple[ast.AST, str]:
    info = json.loads(row["problem_info"])
    code = info["objective"].get("code", {}).get("gurobipy", "")
    found = calls(code, "setObjective")
    if len(found) != 1 or not found[0].args:
        raise TypeError("objective is not one setObjective call")
    sense = "max" if "MAXIMIZE" in code else "min"
    return found[0].args[0], sense


def values_for(row: dict, variables: dict) -> dict[str, float]:
    values = {k: v for k, v in json.loads(row["parameters"]).items()}
    values.update(variables)
    return values


def objective_value(row: dict, variables: dict) -> float:
    expr, _ = objective(row)
    return float(evaluate(expr, values_for(row, variables)))


def compatible(row: dict) -> tuple[bool, str]:
    try:
        info = json.loads(row["problem_info"])
        params = json.loads(row["parameters"])
        sol = json.loads(row["solution"])
        if any(not isinstance(v, (int, float)) for v in params.values()):
            return False, "non_scalar_parameter"
        if any(v.get("shape") for v in info["variables"].values()):
            return False, "non_scalar_variable"
        if any(not isinstance(v, (int, float)) for v in sol["variables"].values()):
            return False, "non_scalar_solution"
        magnitudes = [abs(float(v)) for v in sol["variables"].values()]
        magnitudes.append(abs(float(sol["objective"])))
        if any(not math.isfinite(v) or v > 1e12 for v in magnitudes):
            return False, "pathological_reference_magnitude"
        for raw in info["constraints"]:
            code = raw.get("code", {}).get("gurobipy", "")
            if "addConstrs" in code or "quicksum" in code:
                return False, "generator_constraint"
        constraints(row)
        objective(row)
        return True, "ok"
    except (KeyError, TypeError, ValueError, SyntaxError) as e:
        return False, f"{type(e).__name__}: {e}"


def audit(row: dict, solution: dict) -> dict:
    variables = solution["variables"]
    values = values_for(row, variables)
    violations = []
    for c in constraints(row):
        ok, left, right = comparison(c["expression"], values)
        if not ok:
            violations.append({"rule": c["rule"], "description": c["description"],
                               "lhs": left, "rhs": right})
    expr, _ = objective(row)
    recomputed = float(evaluate(expr, values))
    reported = float(solution["objective"])
    if not math.isclose(recomputed, reported, rel_tol=1e-6, abs_tol=1e-5):
        violations.append({"rule": "OBJECTIVE", "reported": reported,
                           "recomputed": recomputed})
    info = json.loads(row["problem_info"])
    for name, spec in info["variables"].items():
        kind = str(spec.get("type", "")).lower()
        if ("integer" in kind or "binary" in kind) and abs(variables[name] - round(variables[name])) > 1e-6:
            violations.append({"rule": "INTEGRALITY", "variable": name,
                               "value": variables[name]})
    return {"verdict": "INVALID" if violations else "VALID",
            "violations": violations, "objective_recomputed": recomputed}


def with_objective(row: dict, variables: dict) -> dict:
    return {"variables": variables, "objective": objective_value(row, variables)}


def mutate(row: dict, split: str = "dev") -> list[dict]:
    import hashlib
    import random

    seed = int(hashlib.sha256(f"memory-witness-v0.1:{split}:{row['id']}".encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    clean = json.loads(row["solution"])
    _, sense = objective(row)
    objective_factor = 0.05 if split == "dev" else rng.choice([0.03, 0.07, 0.11, 0.17])
    delta = max(1.0, abs(float(clean["objective"])) * objective_factor)
    changed = dict(clean)
    changed["objective"] = float(clean["objective"]) + (delta if sense == "max" else -delta)
    out = [{"wrong": True, "mutation": "objective_misreport", "solution": changed}]
    variables = clean["variables"]
    info = json.loads(row["problem_info"])
    for name, spec in info["variables"].items():
        kind = str(spec.get("type", "")).lower()
        if "integer" not in kind and "binary" not in kind:
            continue
        fraction = 0.5 if split == "dev" else rng.choice([0.25, 0.5, 0.75])
        changed_vars = dict(variables)
        changed_vars[name] = variables[name] + fraction
        out.append({"wrong": True, "mutation": f"integrality:{name}",
                    "solution": with_objective(row, changed_vars)})
    for c in constraints(row):
        names = {n.id for n in ast.walk(c["expression"]) if isinstance(n, ast.Name)}
        found = None
        candidates = sorted(names & set(variables))
        if split != "dev":
            rng.shuffle(candidates)
        factor_pairs = [(factor, sign) for factor in (0.1, 0.5, 1.0, 4.0, 16.0)
                        for sign in (1.0, -1.0)]
        if split != "dev":
            rng.shuffle(factor_pairs)
        for name in candidates:
            original = float(variables[name])
            scale = max(1.0, abs(original))
            for factor, sign in factor_pairs:
                changed_vars = dict(variables)
                changed_vars[name] = original + sign * scale * factor
                if changed_vars[name] < 0:
                    continue
                ok, _, _ = comparison(c["expression"], values_for(row, changed_vars))
                if not ok:
                    found = changed_vars
                    break
            if found is not None:
                break
        if found is not None:
            out.append({"wrong": True, "mutation": f"{c['rule']}:{c['description']}",
                        "target_rule": c["rule"],
                        "solution": with_objective(row, found)})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "validation", "sealed"], default="dev")
    ap.add_argument("--allow-sealed", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="work/memory_witness/nlp4lp_artifacts")
    args = ap.parse_args()
    if args.split == "sealed" and not args.allow_sealed:
        raise SystemExit("sealed access requires --allow-sealed after asset freeze")
    rows = load_rows(args.split)
    outdir = ROOT / args.out / args.split
    outdir.mkdir(parents=True, exist_ok=True)
    cells, skipped = [], []
    for row in rows:
        ok, reason = compatible(row)
        if not ok:
            skipped.append({"id": row["id"], "reason": reason})
            continue
        clean = json.loads(row["solution"])
        try:
            ref = audit(row, clean)
        except Exception as e:
            skipped.append({"id": row["id"], "reason": "reference_audit_error",
                            "error": f"{type(e).__name__}: {e}"})
            continue
        if ref["verdict"] != "VALID":
            skipped.append({"id": row["id"], "reason": "expert_solution_failed_audit",
                            "violations": ref["violations"]})
            continue
        candidates = [{"wrong": False, "mutation": "clean", "solution": clean}]
        for m in mutate(row, args.split):
            mref = audit(row, m["solution"])
            if mref["verdict"] == "INVALID":
                candidates.append(m)
        for m in candidates:
            mref = audit(row, m["solution"])
            cells.append({"key": f"{row['id']}|{len(cells):03d}", "id": row["id"],
                          "wrong": bool(m["wrong"]), "mutation": m["mutation"],
                          "target_rule": m.get("target_rule"), "solution": m["solution"],
                          "reference_verdict": mref["verdict"],
                          "reference_violations": [v["rule"] for v in mref["violations"]]})
        (outdir / f"{row['id']}__question.txt").write_text(row["description"])
        if args.limit and len({c["id"] for c in cells}) >= args.limit:
            break
    with (outdir / "cells.jsonl").open("w") as f:
        for c in cells:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    summary = {"split": args.split, "n_cells": len(cells),
               "n_problems": len({c["id"] for c in cells}),
               "n_wrong": sum(c["wrong"] for c in cells),
               "n_clean": sum(not c["wrong"] for c in cells), "skipped": skipped}
    (outdir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

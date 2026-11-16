#!/usr/bin/env python3
"""Independently audit small MAMO TSP references by exhaustive tours."""
from __future__ import annotations

import argparse
import ast
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def scalar_value(node: ast.AST, tree: ast.AST):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return literal_assignment(tree, node.id)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -scalar_value(node.operand, tree)
    if isinstance(node, ast.BinOp):
        left, right = scalar_value(node.left, tree), scalar_value(node.right, tree)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
    raise ValueError("unsupported scalar expression")


def literal_assignment(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            continue
        try:
            return ast.literal_eval(node.value)
        except ValueError:
            if (name == "cities" and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "list" and node.value.args
                    and isinstance(node.value.args[0], ast.Call)
                    and isinstance(node.value.args[0].func, ast.Name)
                    and node.value.args[0].func.id == "range"):
                args = [scalar_value(a, tree) for a in node.value.args[0].args]
                return list(range(*args))
            continue
    raise KeyError(name)


def first_assignment(tree: ast.AST, names: tuple[str, ...]):
    for name in names:
        try:
            return literal_assignment(tree, name)
        except KeyError:
            continue
    raise KeyError(names[0])


def audit_code(code: str) -> dict:
    tree = ast.parse(code)
    try:
        cities = first_assignment(tree, ("cities", "locations", "nodes"))
    except KeyError:
        n = literal_assignment(tree, "n")
        cities = list(range(n))
    cost = first_assignment(
        tree, ("cost", "c", "cost_matrix", "distance", "distances", "weights"))

    def edge(a, b):
        if isinstance(cost, dict):
            if (a, b) in cost:
                return cost[a, b]
            return cost[cities.index(a), cities.index(b)]
        return cost[cities.index(a)][cities.index(b)]

    start = cities[0]
    best = (float("inf"), None)
    for perm in itertools.permutations(cities[1:]):
        tour = (start,) + perm + (start,)
        value = sum(edge(tour[i], tour[i + 1]) for i in range(len(tour) - 1))
        if value < best[0]:
            best = (value, tour)
    return {"objective": best[0], "tour": best[1], "n_tours": 0}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--baseline-tag", required=True)
    ap.add_argument("--ids", nargs="+", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    baseline = [json.loads(l) for l in Path(args.baseline).read_text().splitlines() if l.strip()]
    last = {}
    for r in baseline:
        if r["id"] not in last or r["round"] > last[r["id"]]["round"]:
            last[r["id"]] = r
    results = []
    for pid in args.ids:
        r = last[pid]
        code = (ROOT / "runs/industryor/sandbox"
                / f"{args.baseline_tag}__{pid}__r{r['round']}" / "gen.py").read_text()
        try:
            audit = audit_code(code)
            audit["n_tours"] = 1
            for i in range(1, len(audit["tour"]) - 1):
                audit["n_tours"] *= i
            rec = {"id": pid, "public_reference": r["reference"],
                   "independent_optimum": audit["objective"], "tour": audit["tour"],
                   "n_tours": audit["n_tours"],
                   "status": ("consistent" if abs(audit["objective"] - r["reference"]) <= 0.1
                              else "reference_mismatch")}
        except Exception as e:
            rec = {"id": pid, "public_reference": r["reference"],
                   "status": "audit_unsupported", "error": f"{type(e).__name__}: {e}"}
        results.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()

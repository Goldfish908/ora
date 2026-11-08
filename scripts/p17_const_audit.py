#!/usr/bin/env python3
"""P17: deterministic code-vs-data constant audit (prototype + validation).

Hypothesis (from judge harvest analysis): wrong_constant mutants evade the
active judge because solution-level checks pass on a self-consistent wrong
model. The discriminating signal is in the CODE: numeric literals that do not
appear in the instance data.

Tool: extract numeric literals from model code via AST; extract all numeric
values from data.json; flag code literals absent from data (with tolerance),
excluding ubiquitous literals (0, 1, small ints, indices).

Validation: judge_v2 cells (F1-F4 factory). wrong_constant mutants should be
flagged at high rate; repair_pass (correct) cells at low rate. No LLM calls.
"""
from __future__ import annotations

import ast
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JUDGE_DATA = ROOT / "work" / "judge_data" / "judge_v2.jsonl"
SCENARIOS = ROOT / "data" / "m1_retailopt" / "f1f4_all100.jsonl"


def code_literals(code: str):
    """numeric literals in code, excluding array-index-ish small ints."""
    out = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            v = float(node.value)
            if v in (0.0, 1.0, -1.0, 2.0) or v == int(v) and abs(v) < 10:
                continue
            out.append(v)
    return out


def data_values(x, acc):
    if isinstance(x, bool):
        return
    if isinstance(x, (int, float)):
        acc.append(float(x))
    elif isinstance(x, dict):
        for v in x.values():
            data_values(v, acc)
    elif isinstance(x, list):
        for v in x:
            data_values(v, acc)


def audit(code: str, data: dict, band=(0.03, 0.60), tol=1e-6):
    """suspicious = code literal whose nearest data value is close-but-wrong
    (relative diff in `band`): the wrong_constant mutation signature is a
    10-30% shift of a true constant; legitimate literals (1e-9, big-M) sit
    far from any data value, exact copies match at tol."""
    vals = []
    data_values(data, vals)
    vals = sorted(v for v in vals if v != 0)
    if not vals:
        return []
    import bisect
    sus = []
    for lit in set(code_literals(code)):
        if lit == 0:
            continue
        i = bisect.bisect_left(vals, lit)
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(vals):
                rel = abs(vals[j] - lit) / max(abs(vals[j]), abs(lit))
                if best is None or rel < best:
                    best = rel
        if best is not None and band[0] <= best <= band[1]:
            sus.append((lit, round(best, 4)))
    return sus


def factor_literals(code, lo=1.08, hi=1.45):
    """numeric factors multiplying a data reference: BinOp(*, /) with one side
    a Constant in [lo,hi] or reciprocal band, other side a data access
    (Subscript/Name/Call/Attribute). Catches factor-injection mutants
    (1.25 * costs['inventory'][p]) that near-miss matching cannot see."""
    sus = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return sus
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div)):
            for a, b in ((node.left, node.right), (node.right, node.left)):
                if isinstance(a, ast.Constant) \
                        and isinstance(a.value, (int, float)) \
                        and not isinstance(a.value, bool):
                    v = float(a.value)
                    if (lo <= v <= hi) or (1 / hi <= v <= 1 / lo < 1):
                        if isinstance(b, (ast.Subscript, ast.Name, ast.Call,
                                          ast.Attribute)):
                            sus.append(v)
    return sus


def main() -> None:
    scen = {}
    for line in SCENARIOS.read_text().splitlines():
        r = json.loads(line)
        d = r.get("data")
        scen[r["scenario_id"]] = json.loads(d) if isinstance(d, str) else d

    records = [json.loads(l) for l in JUDGE_DATA.read_text().splitlines()]
    stats = Counter()
    by_mutant = {}
    for r in records:
        d = scen.get(r["scenario_id"])
        if d is None:
            continue
        sus_f = factor_literals(r["code"])
        sus_n = audit(r["code"], d, band=(0.07, 0.31))
        flagged = bool(sus_f) or bool(sus_n)
        mut, label = r.get("mutant"), r["label"]
        by_mutant.setdefault(mut, Counter())
        by_mutant[mut][(label, flagged)] += 1
        by_mutant[mut][(label, "factor")] += bool(sus_f)
        stats[(label, flagged)] += 1

    print("overall (label, flagged):", dict(stats))
    for m, c in sorted(by_mutant.items()):
        w_flag = c[("wrong", True)]; w_tot = w_flag + c[("wrong", False)]
        c_flag = c[("correct", True)]; c_tot = c_flag + c[("correct", False)]
        print(f"  {m:20s} wrong flagged {w_flag}/{w_tot}"
              f" = {w_flag/max(w_tot,1):.1%}   correct flagged {c_flag}/{c_tot}"
              f" = {c_flag/max(c_tot,1):.1%}")


if __name__ == "__main__":
    main()

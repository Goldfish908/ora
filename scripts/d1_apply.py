#!/usr/bin/env python3
"""D1: apply authored rules to the 240 labeled IndustryOR cells; build matrix.

Each rule runs in a subprocess (5s timeout, stdlib only): the subprocess
execs the rule code and calls check(code, objective, params).
A rule that crashes is counted as rule_error (neither detection nor FP).

Matrix: detection rate on 61 phantom cells / false-positive rate on 179
correct cells, plus per-rule stats.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CELLS = ROOT / "runs" / "industryor" / "industryor_judge_cells.jsonl"
RULES = ROOT / "runs" / "d1_authoring"
OUT = ROOT / "runs" / "d1_authoring" / "matrix.json"

RUNNER = r"""
import json, sys
spec = json.loads(open(sys.argv[1]).read())
ns = {}
try:
    exec(spec["rule_code"], ns)
    check = ns.get("check")
    if check is None:
        print(json.dumps({"status": "no_check"})); sys.exit(0)
    v = check(spec["code"], spec["objective"], spec["params"])
    print(json.dumps({"status": "ok", "violation": v if isinstance(v, str) else None}))
except Exception as e:
    print(json.dumps({"status": "rule_error", "err": f"{type(e).__name__}: {e}"[:200]}))
"""


def run_rule(rule_code: str, code: str, objective, params) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"rule_code": rule_code, "code": code,
                   "objective": objective, "params": params}, f)
        spec = f.name
    try:
        r = subprocess.run([sys.executable, "-c", RUNNER, spec],
                           capture_output=True, text=True, timeout=5)
        line = r.stdout.strip().splitlines()
        return json.loads(line[-1]) if line else {"status": "rule_error",
                                                  "err": r.stderr[-200:]}
    except subprocess.TimeoutExpired:
        return {"status": "rule_error", "err": "timeout"}
    except Exception as e:
        return {"status": "rule_error", "err": f"{type(e).__name__}: {e}"}


def rule_class(rule_code: str) -> str:
    """numeric: the rule body actually reads params and/or objective;
    code_only: the rule only greps the code text (keyword heuristics).
    Uses AST so the def-signature argument names don't count."""
    import ast
    try:
        tree = ast.parse(rule_code)
    except SyntaxError:
        return "code_only"
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in ("params", "objective") \
                and isinstance(node.ctx, ast.Load):
            return "numeric"
    return "code_only"


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules-dir", default=str(RULES))
    ap.add_argument("--glob", default="rules_*.json")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    rules_dir, out_path = Path(args.rules_dir), Path(args.out)

    cells = [json.loads(l) for l in CELLS.open() if l.strip()]
    rules_by_id = {}
    for f in sorted(rules_dir.glob(args.glob)):
        r = json.loads(f.read_text())
        rules_by_id[r["id"]] = r

    n_flag_phantom = n_phantom = n_flag_correct = n_correct = 0
    cls_stats = {"numeric": [0, 0, 0, 0], "code_only": [0, 0, 0, 0]}
    # per class: [phantom_flagged, phantom_total, correct_flagged, correct_total]
    rule_stats = Counter()
    missing_rule = 0
    details = []
    for c in cells:
        rr = rules_by_id.get(c["id"])
        if not rr or not rr.get("rules"):
            missing_rule += 1
            continue
        n_phantom += c["wrong"]
        n_correct += (not c["wrong"])
        flagged = False
        cls_flagged = {"numeric": False, "code_only": False}
        for rule in rr["rules"]:
            res = run_rule(rule["code"], c["code"], c["objective"],
                           rr.get("params") or {})
            rule_stats[(c["id"], rule.get("name") or rule.get("template"), res["status"])] += 1
            if res["status"] == "ok" and res.get("violation"):
                flagged = True
                cls_flagged[rule_class(rule["code"])] = True
                details.append({"key": c["key"], "wrong": c["wrong"],
                                "rule": rule.get("name") or rule.get("template"),
                                "class": rule_class(rule["code"]),
                                "violation": res["violation"][:160]})
        for cls, f in cls_flagged.items():
            if c["wrong"]:
                cls_stats[cls][0] += f
                cls_stats[cls][1] += 1
            else:
                cls_stats[cls][2] += f
                cls_stats[cls][3] += 1
        if c["wrong"]:
            n_flag_phantom += flagged
        else:
            n_flag_correct += flagged

    def _rate(a, b):
        return a / b if b else None

    summary = {
        "cells": len(cells), "cells_with_rules": n_phantom + n_correct,
        "cells_missing_rules": missing_rule,
        "phantom": n_phantom, "correct": n_correct,
        "detection_rate": _rate(n_flag_phantom, n_phantom),
        "false_positive_rate": _rate(n_flag_correct, n_correct),
        "by_class": {cls: {"detection_rate": _rate(v[0], v[1]),
                           "false_positive_rate": _rate(v[2], v[3]),
                           "phantom": v[1], "correct": v[3]}
                     for cls, v in cls_stats.items()},
        "status_counts": {s: sum(v for k, v in rule_stats.items() if k[2] == s)
                          for s in ("ok", "rule_error", "no_check")},
        "n_rules_total": sum(len(r.get("rules") or [])
                             for r in rules_by_id.values()),
    }
    out_path.write_text(json.dumps({"summary": summary, "details": details},
                              ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

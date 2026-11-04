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


def main() -> None:
    cells = [json.loads(l) for l in CELLS.open() if l.strip()]
    rules_by_id = {}
    for f in sorted(RULES.glob("rules_*.json")):
        r = json.loads(f.read_text())
        rules_by_id[r["id"]] = r

    n_flag_phantom = n_phantom = n_flag_correct = n_correct = 0
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
        for rule in rr["rules"]:
            res = run_rule(rule["code"], c["code"], c["objective"],
                           rr.get("params") or {})
            rule_stats[(c["id"], rule["name"], res["status"])] += 1
            if res["status"] == "ok" and res.get("violation"):
                flagged = True
                details.append({"key": c["key"], "wrong": c["wrong"],
                                "rule": rule["name"],
                                "violation": res["violation"][:160]})
        if c["wrong"]:
            n_flag_phantom += flagged
        else:
            n_flag_correct += flagged

    summary = {
        "cells": len(cells), "cells_with_rules": n_phantom + n_correct,
        "cells_missing_rules": missing_rule,
        "phantom": n_phantom, "correct": n_correct,
        "detection_rate": n_flag_phantom / n_phantom if n_phantom else None,
        "false_positive_rate": n_flag_correct / n_correct if n_correct else None,
        "status_counts": {s: sum(v for k, v in rule_stats.items() if k[2] == s)
                          for s in ("ok", "rule_error", "no_check")},
        "n_rules_total": sum(len(r.get("rules") or [])
                             for r in rules_by_id.values()),
    }
    OUT.write_text(json.dumps({"summary": summary, "details": details},
                              ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""D1.5: rule-library coverage optimization over the 499 authored rules.

Question: how much of D1's 49.2% FP is bad-rule noise that a *selector*
can prune, vs a library ceiling that needs better rules (D2)?

Protocol (honest, no test leakage):
- build full trigger matrix: each rule x each cell of its own problem
  (subprocess sandbox, cached to trigger_matrix.json);
- split cells per problem into dev/test halves (seed 0, stratified-ish);
- greedy set cover on dev: maximize phantom-cell coverage s.t. FP cells
  <= budget; evaluate the selected set on test;
- oracle ceiling: rules that never fire on any correct cell (uses all
  cells -> labeled ORACLE, an upper bound, not a deployable selector);
- baselines on test: all rules, numeric-class only, A1 self-consistency.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from d1_apply import run_rule, rule_class, ROOT, CELLS, RULES  # noqa: E402

CACHE = ROOT / "runs" / "d1_authoring" / "trigger_matrix.json"
OUT = ROOT / "runs" / "d1_authoring" / "coverage.json"


def build_matrix(cells, rules_by_id):
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    mat = {}  # rule_uid -> {cell_key: 1}
    for i, c in enumerate(cells):
        rr = rules_by_id.get(c["id"])
        if not rr:
            continue
        for j, rule in enumerate(rr["rules"]):
            uid = f"{c['id']}#{j}:{rule['name']}"
            res = run_rule(rule["code"], c["code"], c["objective"],
                           rr.get("params") or {})
            if res["status"] == "ok" and res.get("violation"):
                mat.setdefault(uid, {})[c["key"]] = 1
        if (i + 1) % 40 == 0:
            print(f"  matrix {i+1}/{len(cells)}", flush=True)
    CACHE.write_text(json.dumps(mat))
    return mat


def greedy_select(dev_cells, mat, rule_meta, fp_budget):
    dev_ph = {c["key"] for c in dev_cells if c["wrong"]}
    dev_co = {c["key"] for c in dev_cells if not c["wrong"]}
    selected, covered, fps = set(), set(), set()
    while True:
        best, best_gain = None, 0
        for uid, fires in mat.items():
            if uid in selected:
                continue
            f = set(fires)
            new_co = (f & dev_co) - fps
            if len(fps) + len(new_co) > fp_budget:
                continue
            gain = len((f & dev_ph) - covered)
            if gain > best_gain:
                best, best_gain = uid, gain
        if best is None:
            break
        selected.add(best)
        covered |= set(mat[best]) & dev_ph
        fps |= set(mat[best]) & dev_co
    return selected


def eval_set(selected, mat, cells):
    ph = {c["key"] for c in cells if c["wrong"]}
    co = {c["key"] for c in cells if not c["wrong"]}
    fired = set()
    for uid in selected:
        fired |= set(mat.get(uid, {}))
    det = len(fired & ph) / len(ph) if ph else None
    fp = len(fired & co) / len(co) if co else None
    return det, fp, len(fired & ph), len(fired & co), len(ph), len(co)


def main() -> None:
    cells = [json.loads(l) for l in CELLS.open() if l.strip()]
    rules_by_id = {}
    for f in sorted(RULES.glob("rules_*.json")):
        r = json.loads(f.read_text())
        rules_by_id[r["id"]] = r
    print("building trigger matrix...", flush=True)
    mat = build_matrix(cells, rules_by_id)
    rule_meta = {}
    for pid, rr in rules_by_id.items():
        for j, rule in enumerate(rr["rules"]):
            rule_meta[f"{pid}#{j}:{rule['name']}"] = rule_class(rule["code"])

    # per-problem dev/test split (seed 0)
    by_id = {}
    for c in cells:
        by_id.setdefault(c["id"], []).append(c)
    dev, test = [], []
    rng = random.Random(0)
    for pid, cl in sorted(by_id.items()):
        cl = cl[:]
        rng.shuffle(cl)
        h = (len(cl) + 1) // 2
        dev += cl[:h]
        test += cl[h:]

    all_rules = set(mat)
    numeric = {u for u in all_rules if rule_meta.get(u) == "numeric"}

    rows = []
    det, fp, *_ = eval_set(all_rules, mat, test)
    rows.append({"gate": "all rules (test)", "det": det, "fp": fp})
    det, fp, *_ = eval_set(numeric, mat, test)
    rows.append({"gate": "numeric only (test)", "det": det, "fp": fp})

    # oracle ceiling on ALL cells (upper bound, not deployable)
    oracle = {u for u, fires in mat.items()
              if not any(not c["wrong"] and c["key"] in fires for c in cells)}
    det, fp, nd, nf, nph, nco = eval_set(oracle, mat, cells)
    rows.append({"gate": "ORACLE ceiling FP=0 (all cells, upper bound)",
                 "det": det, "fp": fp, "rules_kept": len(oracle)})

    # greedy on dev at several FP budgets, evaluate on test
    n_dev_co = sum(1 for c in dev if not c["wrong"])
    for frac in (0.0, 0.01, 0.025, 0.05):
        budget = int(frac * n_dev_co) if frac else 0
        sel = greedy_select(dev, mat, rule_meta, budget)
        det, fp, nd, nf, nph, nco = eval_set(sel, mat, test)
        ddev = eval_set(sel, mat, dev)
        rows.append({"gate": f"greedy dev FP<={frac:.1%} -> test",
                     "det": det, "fp": fp, "rules_kept": len(sel),
                     "dev_det": ddev[0], "dev_fp": ddev[1]})

    out = {"n_rules": len(all_rules), "n_cells": len(cells),
           "dev": len(dev), "test": len(test), "rows": rows}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for r in rows:
        print(f"{r['gate']:42s} det={r['det']:.1%} fp={r['fp']:.1%}"
              + (f" rules={r['rules_kept']}" if "rules_kept" in r else ""))


if __name__ == "__main__":
    main()

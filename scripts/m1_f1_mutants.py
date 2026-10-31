#!/usr/bin/env python3
"""Negative controls for the F1 witness checker.

Each mutant takes the validated reference solution and breaks exactly one
rule; the checker must report that rule. A checker that passes a mutant is
blind; a checker that flags only unrelated rules is misattributing.

    python3 scripts/m1_f1_mutants.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from m1_witness.f1 import check  # noqa: E402

SID = "retail_f1_base_v0"


def load():
    rows = [json.loads(l) for l in
            (ROOT / "data/m1_retailopt/retailopt_190.jsonl")
            .read_text().splitlines() if l.strip()]
    row = next(r for r in rows if r["scenario_id"] == SID)
    data = json.loads(row["data"])
    sol = json.loads((ROOT / "runs/m1_witness_ref"
                      / f"{SID}.solution.json").read_text())
    return data, sol


def first_key(table):
    return next(iter(table)) if table else None


def mutants(sol):
    out = {}

    m = copy.deepcopy(sol)                       # waste over-reported
    m["W"]["SKU_Basic|DC1|2"] = 1e5              # (f1_base has zero true waste)
    out["M-WASTE"] = ("C-WASTE", m)

    k = first_key({k: v for k, v in sol["I"].items()
                   if int(k.split("|")[2]) > 1})  # aging carryover cut
    if k:
        m = copy.deepcopy(sol)
        p, l, t, r = k.split("|")
        if int(r) < 10:
            m["I"][k] = float(m["I"][k]) * 0.5
            out["M-AGING"] = ("C-AGING", m)

    m = copy.deepcopy(sol)                       # production cap exceeded
    k = first_key(sol["Q"])
    if k:
        p, l, t = k.split("|")
        m["Q"][k] = float(m["Q"][k]) + 1e6
        out["M-PRODCAP"] = ("C-PRODCAP", m)

    m = copy.deepcopy(sol)                       # sales above inventory
    k = first_key(sol["sales"])
    if k:
        p, l, t, r = k.split("|")
        ik = f"{p}|{l}|{t}|{r}"
        m["sales"][k] = float(sol["I"].get(ik, 0.0)) + 1e5
        out["M-AVAIL"] = ("C-AVAIL", m)

    m = copy.deepcopy(sol)                       # undeclared sub edge
    m["sub"]["SKU_Premium|SKU_Basic|DC1|1"] = 10.0  # reverse of declared edge
    out["M-SUBEDGE"] = ("C-SUBEDGE", m)

    m = copy.deepcopy(sol)                       # demand balance broken
    m["lost"]["SKU_Basic|DC1|2"] = 1e5           # (f1_base has zero true lost)
    out["M-DEMAND"] = ("C-DEMAND", m)

    m = copy.deepcopy(sol)                       # phantom initial stock
    m["I"]["SKU_Basic|DC1|1|1"] = 25.0
    out["M-INIT"] = ("C-INIT", m)

    m = copy.deepcopy(sol)                       # objective misreported
    m["objective"] = float(sol["objective"]) * 0.9
    out["M-OBJ"] = ("C-OBJ", m)

    return out


def main() -> None:
    data, sol = load()
    base = check(data, sol)
    assert not base["violations"], f"reference must PASS: {base['violations'][:3]}"
    print("reference: PASS (0 violations,"
          f" {len(base['warnings'])} warnings)")
    fails = 0
    for name, (expect, msol) in mutants(sol).items():
        res = check(data, msol)
        rules = {r for r, _ in res["violations"]}
        ok = expect in rules
        fails += not ok
        print(f"{name}: expect {expect} -> {'HIT' if ok else 'MISS'} "
              f"(rules fired: {sorted(rules)})")
    print("ALL OK" if fails == 0 else f"{fails} mutants MISSED")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()

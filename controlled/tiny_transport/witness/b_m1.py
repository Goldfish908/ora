"""Witness for tiny_transport artifact "correct".

Runs the artifact's solve.py, then checks solution.json against the business
rules (plant capacity, exact warehouse demand in pieces, >=20 pieces from P2 to
each warehouse) and against the independent reference objective (tol 1e-6).
Prints "WITNESS PASS" (exit 0) or "WITNESS FAIL: <reason>" (exit 1).
"""
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

PY = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"
AID = "b_m1"
TOL = 1e-6
BOX_TO_PIECES = 10
MIN_FROM_P2 = 20

PROB = Path(__file__).resolve().parent.parent


def fail(reason):
    print(f"WITNESS FAIL: {reason}")
    sys.exit(1)


def artifact_dir():
    if AID == "correct":
        return PROB / "correct"
    for sub in ("mutants", "equivalent"):
        cand = PROB / sub / AID
        if cand.is_dir():
            return cand
    fail(f"artifact directory for {AID} not found")


def main():
    art = artifact_dir()
    proc = subprocess.run(
        [PY, str(art / "solve.py")],
        cwd=art, capture_output=True, text=True, timeout=60,
    )
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        fail(f"solve.py exited with code {proc.returncode}: {proc.stderr.strip()[:300]}")

    sol_path = art / "solution.json"
    if not sol_path.exists():
        fail("solution.json was not produced (model infeasible or solve failed)")
    sol = json.loads(sol_path.read_text())

    ref = subprocess.run(
        [PY, str(PROB / "reference.py")], capture_output=True, text=True, timeout=60,
    )
    m = re.search(r"REFERENCE\s+([0-9.eE+-]+)", ref.stdout)
    if not m:
        fail("reference.py did not print a REFERENCE value")
    ref_obj = float(m.group(1))

    with open(PROB / "data" / "supply.csv", newline="") as f:
        supply = {r["plant"]: float(r["supply"]) for r in csv.DictReader(f)}
    with open(PROB / "data" / "demand.csv", newline="") as f:
        demand = {r["warehouse"]: float(r["demand"]) * BOX_TO_PIECES for r in csv.DictReader(f)}
    costs = {}
    with open(PROB / "data" / "costs.csv", newline="") as f:
        for r in csv.DictReader(f):
            costs[(r["plant"], r["warehouse"])] = float(r["cost"])

    flows = sol.get("flows")
    if not isinstance(flows, list):
        fail("solution.json has no flows list")
    for fl in flows:
        if (fl["plant"], fl["warehouse"]) not in costs:
            fail(f"unknown lane {fl['plant']}-{fl['warehouse']}")
        if fl["qty"] < -TOL:
            fail(f"negative flow on {fl['plant']}-{fl['warehouse']}")

    out = {p: 0.0 for p in supply}
    inn = {w: 0.0 for w in demand}
    for fl in flows:
        out[fl["plant"]] += fl["qty"]
        inn[fl["warehouse"]] += fl["qty"]
    for p, q in out.items():
        if q > supply[p] + TOL:
            fail(f"plant {p} ships {q} > supply {supply[p]}")
    for w, q in inn.items():
        if abs(q - demand[w]) > TOL:
            fail(f"warehouse {w} receives {q} pieces, demand is {demand[w]} pieces")

    p2 = {w: 0.0 for w in demand}
    for fl in flows:
        if fl["plant"] == "P2":
            p2[fl["warehouse"]] += fl["qty"]
    for w, q in p2.items():
        if q < MIN_FROM_P2 - TOL:
            fail(f"business rule violated: warehouse {w} receives only {q} pieces from P2 (< {MIN_FROM_P2})")

    recomputed = sum(costs[(fl["plant"], fl["warehouse"])] * fl["qty"] for fl in flows)
    if abs(float(sol.get("objective", float("nan"))) - recomputed) > TOL:
        fail(f"reported objective {sol.get('objective')} != recomputed {recomputed}")
    if abs(recomputed - ref_obj) > TOL:
        fail(f"objective {recomputed} != reference optimum {ref_obj}")

    print("WITNESS PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()

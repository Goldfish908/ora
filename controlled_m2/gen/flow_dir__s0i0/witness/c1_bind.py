"""flow_dir__s0i0 witness: independent semantic checker (does NOT import or
reuse the artifact's modeling code — rules re-implemented from problem.md).

Usage: python3 witness/<aid>.py   (runs the artifact's solve.py first)
Checks on the artifact's solution.json:
  W1 plant supply limits (outflow <= supply)
  W2 edge capacities
  W3 TRUE hub conservation with correct edge orientation:
     f[A->H] + f[B->H] == f[H->D1] + f[H->D2]
  W4 demand met exactly at D1, D2
  W5 reported objective equals recomputed production+transport cost
     with TRUE costs (tol 1e-6)
Prints PASS or FAIL:<rule> lines; exit code 0 on PASS, 1 on FAIL.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_CAND = os.environ.get("ORA_MIP_PYTHON")
if not _CAND:
    for _c in ("/home/hewj13/planbb/miniforge3/envs/rl/bin/python",):
        if os.path.exists(_c):
            _CAND = _c
            break
PY = _CAND or sys.executable
TOL = 1e-6
EDGES = [("A", "H"), ("B", "H"), ("H", "D1"), ("H", "D2")]


def main():
    aid = Path(__file__).stem
    root = HERE.parent
    art = root / ("correct" if aid == "correct" else f"mutants/{aid}")
    d = json.loads((root / "data" / "params.json").read_text())

    r = subprocess.run([PY, str(art / "solve.py")], cwd=art,
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print("FAIL:crash", r.stderr[-300:])
        sys.exit(1)
    sol = json.loads((art / "solution.json").read_text())
    fl = sol["flows"]

    def f(a, b):
        return fl[f"{a}->{b}"]

    fails = []
    for plant in ("A", "B"):
        if f(plant, "H") - d["supply"][plant] > TOL:
            fails.append(f"W1 supply {plant}")
    for (a, b) in EDGES:
        if f(a, b) - d["edge_cap"][f"{a}->{b}"] > TOL:
            fails.append(f"W2 edge_cap {a}->{b}")
        if f(a, b) < -TOL:
            fails.append(f"W2 neg_flow {a}->{b}")
    if abs(f("A", "H") + f("B", "H") - f("H", "D1") - f("H", "D2")) > TOL:
        fails.append("W3 hub_conservation")
    for dp in ("D1", "D2"):
        if abs(f("H", dp) - d["demand"][dp]) > TOL:
            fails.append(f"W4 demand {dp}")

    obj = (sum(d["prod_cost"][a] * f(a, "H") for a in ("A", "B"))
           + sum(d["transp_cost"][a][b] * f(a, b) for (a, b) in EDGES))
    if abs(obj - sol["objective"]) > TOL:
        fails.append("W5 objective_mismatch")

    if fails:
        print("FAIL:" + ";".join(fails))
        sys.exit(1)
    print(f"PASS objective={sol['objective']}")


if __name__ == "__main__":
    main()

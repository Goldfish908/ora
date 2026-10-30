"""setup_charge__s0i0 witness: independent semantic checker (does NOT import or
reuse the artifact's modeling code — rules re-implemented from problem.md).

Usage: python3 witness/<aid>.py   (runs the artifact's solve.py first)
Checks on the artifact's solution.json:
  W1 inventory balance with THIS-period production and given init_inv
  W2 per-period production capacity
  W3 activation: production>0 iff setup==1, for every product/period
  W4 non-negative inventory
  W5 reported objective equals recomputed cost with TRUE setup costs
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


def main():
    aid = Path(__file__).stem
    root = HERE.parent
    art = root / ("correct" if aid == "correct" else f"mutants/{aid}")
    d = json.loads((root / "data" / "params.json").read_text())
    P, T = d["products"], d["periods"]

    r = subprocess.run([PY, str(art / "solve.py")], cwd=art,
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print("FAIL:crash", r.stderr[-300:])
        sys.exit(1)
    sol = json.loads((art / "solution.json").read_text())
    x, inv, y = sol["production"], sol["inventory"], sol["setup"]
    fails = []

    for p in P:
        for t in range(T):
            prev = d["init_inv"][p] if t == 0 else inv[p][t - 1]
            if abs(inv[p][t] - (prev + x[p][t] - d["demand"][p][t])) > TOL:
                fails.append(f"W1 balance {p} t{t + 1}")
            if x[p][t] - d["prod_cap"][p] > TOL:
                fails.append(f"W2 capacity {p} t{t + 1}")
            if inv[p][t] < -TOL:
                fails.append(f"W4 neg_inv {p} t{t + 1}")
            producing = x[p][t] > TOL
            setup_on = y[p][t] > 0.5
            if producing != setup_on:
                fails.append(f"W3 activation {p} t{t + 1}")

    obj = (sum(d["prod_cost"][p] * x[p][t] for p in P for t in range(T))
           + sum(d["hold_cost"][p] * inv[p][t] for p in P for t in range(T))
           + sum(d["setup_cost"][p] * round(y[p][t]) for p in P for t in range(T)))
    if abs(obj - sol["objective"]) > TOL:
        fails.append("W5 objective_mismatch")

    if fails:
        print("FAIL:" + ";".join(fails))
        sys.exit(1)
    print(f"PASS objective={sol['objective']}")


if __name__ == "__main__":
    main()

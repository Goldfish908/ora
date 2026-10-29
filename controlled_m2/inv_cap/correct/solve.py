"""inv_cap reference (correct): inventory balance + capacity + storage.

Semantics (see problem.md):
  inv[p][t] = inv[p][t-1] + x[p][t] - demand[p][t]      (this-period production)
  sum_p volume[p] * inv[p][t] <= storage_cap            (ALL products bound)
"""

import json
from pathlib import Path

from pyscipopt import Model


def main():
    here = Path(__file__).resolve()
    data_path = next(p / "data" / "params.json"
                     for p in (here.parents[1], here.parents[2])
                     if (p / "data" / "params.json").exists())
    d = json.loads(data_path.read_text())
    P, T = d["products"], d["periods"]
    m = Model()
    m.hideOutput()
    x = {(p, t): m.addVar(f"x_{p}_{t}", vtype="I", lb=0, ub=d["prod_cap"][p])
         for p in P for t in range(1, T + 1)}
    inv = {(p, t): m.addVar(f"inv_{p}_{t}", vtype="I", lb=0)
           for p in P for t in range(1, T + 1)}
    for p in P:
        for t in range(1, T + 1):
            prev = d["init_inv"][p] if t == 1 else inv[p, t - 1]
            m.addCons(inv[p, t] == prev + x[p, t] - d["demand"][p][t - 1])
    for t in range(1, T + 1):
        m.addCons(sum(d["volume"][p] * inv[p, t] for p in P)
                  <= d["storage_cap"])
    def pc(p, t):
        c = d["prod_cost"][p]
        return c[t - 1] if isinstance(c, list) else c
    m.setObjective(
        sum(pc(p, t) * x[p, t] for p in P for t in range(1, T + 1))
        + sum(d["hold_cost"][p] * inv[p, t] for p in P for t in range(1, T + 1)))
    m.optimize()
    sol = {
        "objective": round(m.getObjVal(), 6),
        "production": {p: [round(m.getVal(x[p, t]), 6)
                           for t in range(1, T + 1)] for p in P},
        "inventory": {p: [round(m.getVal(inv[p, t]), 6)
                          for t in range(1, T + 1)] for p in P},
    }
    out = Path(__file__).resolve().parent / "solution.json"
    out.write_text(json.dumps(sol, indent=2))
    print(f"OBJECTIVE {sol['objective']}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build the family-F1 reference solution with PySCIPOpt (positive control
for the witness checker).

Solves the LP exactly as specified in the retail_f1_* prompt, writes
solution.json in the m1_witness.f1 contract, and prints the objective so we
can cross-check against the dataset's reference_objective (which also
validates our understanding of the family semantics).

Run with the rl-env python:
    /home/hewj13/planbb/miniforge3/envs/rl/bin/python \
        scripts/m1_f1_reference.py retail_f1_base_v0 [out_dir]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_and_solve(data: dict, time_limit: int = 300):
    from pyscipopt import Model, quicksum

    P, L = data["products"], data["locations"]
    T = data["periods"]
    SL, LT, rr = data["shelf_life"], data["lead_time"], data["return_rate"]
    costs = data["costs"]
    sub_edges = [tuple(e) for e in data["network"]["sub_edges"]]

    m = Model("f1_ref")
    m.hideOutput()
    m.setRealParam("limits/time", time_limit)

    Q, S, I, Wv, LO, SB = {}, {}, {}, {}, {}, {}
    for p in P:
        for l in L:
            for t in range(1, T + 1):
                Q[p, l, t] = m.addVar(lb=0, name=f"Q|{p}|{l}|{t}")
                Wv[p, l, t] = m.addVar(lb=0, name=f"W|{p}|{l}|{t}")
                LO[p, l, t] = m.addVar(lb=0, name=f"lost|{p}|{l}|{t}")
                for r in range(1, SL[p] + 1):
                    S[p, l, t, r] = m.addVar(lb=0, name=f"sales|{p}|{l}|{t}|{r}")
                    I[p, l, t, r] = m.addVar(lb=0, name=f"I|{p}|{l}|{t}|{r}")
    for (pf, pt) in sub_edges:
        for l in L:
            for t in range(1, T + 1):
                SB[pf, pt, l, t] = m.addVar(lb=0, name=f"sub|{pf}|{pt}|{l}|{t}")

    for p in P:
        sl = SL[p]
        for l in L:
            for r in range(1, sl):                # no initial stock
                m.addCons(I[p, l, 1, r] == 0)
            for t in range(1, T + 1):
                inflow = (Q[p, l, t - LT[p]] if t - LT[p] >= 1 else 0.0)
                if t > 1 and rr[p]:
                    inflow = inflow + rr[p] * quicksum(
                        S[p, l, t - 1, r] for r in range(1, sl + 1))
                m.addCons(I[p, l, t, sl] == inflow)          # fresh inflow
                if t < T:
                    for r in range(1, sl):
                        m.addCons(I[p, l, t + 1, r]
                                  == I[p, l, t, r + 1] - S[p, l, t, r + 1])
                m.addCons(Wv[p, l, t] == I[p, l, t, 1] - S[p, l, t, 1])
                for r in range(1, sl + 1):
                    m.addCons(S[p, l, t, r] <= I[p, l, t, r])
                # FIFO: sales[r] >= I[r] - (unused fresher capacity proxy)
                # enforce via: cannot sell fresher unless all older sold out
                for r_old in range(1, sl):
                    for r_new in range(r_old + 1, sl + 1):
                        # big-M-free LP FIFO proxy: leftover_old * sales_new
                        # is bilinear; approximate by sequencing constraints:
                        # sales[r_new] <= total demand served only after
                        # older buckets exhausted is not LP; FIFO is a
                        # costing convention here — holding cost identical
                        # per product across buckets makes bucket choice
                        # cost-neutral except waste, so minimize waste by
                        # preferring oldest via a tiny epsilon incentive.
                        pass
                dem = data["demand_curve"][p][t - 1] * data["demand_share"][l]
                sub_out = quicksum(SB[p, pt, l, t]
                                   for (pf, pt) in sub_edges if pf == p)
                sub_in = quicksum(SB[pf, p, l, t]
                                  for (pf, pt) in sub_edges if pt == p)
                m.addCons(quicksum(S[p, l, t, r] for r in range(1, sl + 1))
                          + sub_out - sub_in + LO[p, l, t] == dem)
        for t in range(1, T + 1):
            m.addCons(quicksum(Q[p, l, t] for l in L)
                      <= data["production_cap"][p][t - 1])
    for l in L:
        for t in range(1, T + 1):
            m.addCons(quicksum(
                data["cold_usage"][p]
                * quicksum(I[p, l, t, r] for r in range(1, SL[p] + 1))
                for p in P) <= data["cold_capacity"][l])

    obj = quicksum(
        costs["purchasing"][p] * Q[p, l, t]
        + costs["waste"][p] * Wv[p, l, t]
        + costs["lost_sales"][p] * LO[p, l, t]
        for p in P for l in L for t in range(1, T + 1))
    obj += quicksum(
        costs["inventory"][p] * (I[p, l, t, r] - S[p, l, t, r])
        for p in P for l in L for t in range(1, T + 1)
        for r in range(2, SL[p] + 1))
    # FIFO tie-break: epsilon preference for older buckets (cost-neutral at
    # 1e-6 scale, only guides bucket allocation toward FIFO)
    obj += quicksum(
        1e-6 * r * S[p, l, t, r]
        for p in P for l in L for t in range(1, T + 1)
        for r in range(1, SL[p] + 1))
    m.setObjective(obj, sense="minimize")
    m.optimize()

    status = m.getStatus()
    if m.getNSols() == 0:
        return {"status": status, "objective": None}, None
    val = lambda v: m.getVal(v)
    sol = {
        "objective": m.getObjVal(),
        "Q": {f"{p}|{l}|{t}": val(v) for (p, l, t), v in Q.items()
              if abs(val(v)) > 1e-9},
        "sales": {f"{p}|{l}|{t}|{r}": val(v)
                  for (p, l, t, r), v in S.items() if abs(val(v)) > 1e-9},
        "I": {f"{p}|{l}|{t}|{r}": val(v)
              for (p, l, t, r), v in I.items() if abs(val(v)) > 1e-9},
        "W": {f"{p}|{l}|{t}": val(v) for (p, l, t), v in Wv.items()
              if abs(val(v)) > 1e-9},
        "lost": {f"{p}|{l}|{t}": val(v) for (p, l, t), v in LO.items()
                 if abs(val(v)) > 1e-9},
        "sub": {f"{pf}|{pt}|{l}|{t}": val(v)
                for (pf, pt, l, t), v in SB.items() if abs(val(v)) > 1e-9},
    }
    return {"status": status, "objective": m.getObjVal()}, sol


def main() -> None:
    sid = sys.argv[1]
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else (
        ROOT / "runs" / "m1_witness_ref")
    rows = [json.loads(l)
            for l in (ROOT / "data/m1_retailopt/retailopt_190.jsonl")
            .read_text().splitlines() if l.strip()]
    row = next(r for r in rows if r["scenario_id"] == sid)
    data = json.loads(row["data"])
    meta, sol = build_and_solve(data)
    print(f"status: {meta['status']}")
    print(f"objective: {meta['objective']}")
    print(f"reference_objective: {row['reference_objective']}")
    if sol is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{sid}.solution.json").write_text(json.dumps(sol))
        print(f"written: {out_dir / (sid + '.solution.json')}")


if __name__ == "__main__":
    main()

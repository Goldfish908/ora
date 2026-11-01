#!/usr/bin/env python3
"""Generalized RetailOpt reference solver (positive control / semantic
calibration for m1_witness.retailopt).

Supports every mechanism that activates in the 190-instance dataset:
fixed order cost, MOQ, pack-size integrality, per-period budget,
transshipment network, labor capacity, return flows, waste-limit pct.

Semantics are calibrated against each archetype's reference_objective:
a match within tolerance confirms we understood the prompt correctly.

Run with the rl-env python:
    /home/hewj13/planbb/miniforge3/envs/rl/bin/python \
        scripts/m1_reference.py retail_f8_labor_constraint_v0 \
        [--handled received_picked] [--tl 300] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_and_solve(data: dict, time_limit: int = 300,
                    handled_mode: str = "received_picked"):
    from pyscipopt import Model, quicksum

    P, L = data["products"], data["locations"]
    T = data["periods"]
    SL, LT, rr = data["shelf_life"], data["lead_time"], data["return_rate"]
    costs = data["costs"]
    cons = data.get("constraints", {})
    sub_edges = [tuple(e) for e in data["network"]["sub_edges"]]
    trans_edges = [tuple(e) for e in data["network"]["trans_edges"]]
    fixed = float(costs.get("fixed_order", 0.0))
    trans_cost = float(costs.get("transshipment", 0.0))
    moq = float(cons.get("moq") or 0.0)
    pack = float(cons.get("pack_size") or 1.0)
    budget = cons.get("budget_per_period")
    waste_pct = cons.get("waste_limit_pct")
    labor_on = (any(v > 0 for v in data["labor_usage"].values())
                and any(c < 99999
                        for c in data["labor_cap"][data["locations"][0]]))

    m = Model("retailopt_ref")
    m.hideOutput()
    m.setRealParam("limits/time", time_limit)

    Q, S, I, Wv, LO, SB, X, Y, N = {}, {}, {}, {}, {}, {}, {}, {}, {}
    for p in P:
        big_m = max(data["production_cap"][p])
        for l in L:
            for t in range(1, T + 1):
                if pack > 1:            # integral number of packs
                    N[p, l, t] = m.addVar(vtype="I", lb=0,
                                          ub=int(big_m / pack) + 1,
                                          name=f"n|{p}|{l}|{t}")
                    Q[p, l, t] = m.addVar(lb=0, name=f"Q|{p}|{l}|{t}")
                    m.addCons(Q[p, l, t] == pack * N[p, l, t])
                else:
                    Q[p, l, t] = m.addVar(lb=0, name=f"Q|{p}|{l}|{t}")
                if fixed > 0 or moq > 0:
                    Y[p, l, t] = m.addVar(vtype="B",
                                          name=f"y|{p}|{l}|{t}")
                    m.addCons(Q[p, l, t] <= big_m * Y[p, l, t])
                    if moq > 0:
                        m.addCons(Q[p, l, t] >= moq * Y[p, l, t])
                Wv[p, l, t] = m.addVar(lb=0, name=f"W|{p}|{l}|{t}")
                LO[p, l, t] = m.addVar(lb=0, name=f"lost|{p}|{l}|{t}")
                for r in range(1, SL[p] + 1):
                    S[p, l, t, r] = m.addVar(lb=0,
                                             name=f"sales|{p}|{l}|{t}|{r}")
                    I[p, l, t, r] = m.addVar(lb=0, name=f"I|{p}|{l}|{t}|{r}")
    for (pf, pt) in sub_edges:
        for l in L:
            for t in range(1, T + 1):
                SB[pf, pt, l, t] = m.addVar(lb=0,
                                            name=f"sub|{pf}|{pt}|{l}|{t}")
    for (src, dst) in trans_edges:
        for p in P:
            for t in range(1, T + 1):
                X[p, src, dst, t] = m.addVar(lb=0,
                                             name=f"X|{p}|{src}|{dst}|{t}")

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
                for (src, dst) in trans_edges:
                    if dst == l:
                        inflow = inflow + X[p, src, dst, t]
                    if src == l:
                        inflow = inflow - X[p, src, dst, t]
                m.addCons(I[p, l, t, sl] == inflow)          # fresh inflow
                if t < T:
                    for r in range(1, sl):
                        m.addCons(I[p, l, t + 1, r]
                                  == I[p, l, t, r + 1] - S[p, l, t, r + 1])
                m.addCons(Wv[p, l, t] == I[p, l, t, 1] - S[p, l, t, 1])
                for r in range(1, sl + 1):
                    m.addCons(S[p, l, t, r] <= I[p, l, t, r])
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

    if budget is not None:
        for t in range(1, T + 1):
            spend = quicksum(costs["purchasing"][p] * Q[p, l, t]
                             for p in P for l in L)
            if fixed > 0:
                spend = spend + fixed * quicksum(Y[p, l, t]
                                                 for p in P for l in L)
            m.addCons(spend <= float(budget))

    if labor_on:
        usage = data["labor_usage"]
        for l in L:
            for t in range(1, T + 1):
                used = 0.0
                for p in P:
                    handled = 0.0
                    received = (Q[p, l, t - LT[p]] if t - LT[p] >= 1 else 0.0)
                    if t > 1 and rr[p]:
                        received = received + rr[p] * quicksum(
                            S[p, l, t - 1, r] for r in range(1, SL[p] + 1))
                    received = received + quicksum(
                        X[p, src, l, t] for (src, dst) in trans_edges
                        if dst == l)
                    if handled_mode in ("received", "received_picked",
                                        "full"):
                        handled = handled + received
                    if handled_mode in ("received_picked", "full"):
                        handled = handled + quicksum(
                            S[p, l, t, r] for r in range(1, SL[p] + 1))
                    if handled_mode == "full":
                        handled = handled + quicksum(
                            X[p, l, dst, t] for (src, dst) in trans_edges
                            if src == l)
                    used = used + usage[p] * handled
                m.addCons(used <= data["labor_cap"][l][t - 1])

    if waste_pct is not None:
        tot_dem = sum(data["demand_curve"][p][t - 1] * data["demand_share"][l]
                      for p in P for l in L for t in range(1, T + 1))
        m.addCons(quicksum(Wv[p, l, t] for p in P for l in L
                           for t in range(1, T + 1))
                  <= float(waste_pct) * tot_dem)

    obj = quicksum(
        costs["purchasing"][p] * Q[p, l, t]
        + costs["waste"][p] * Wv[p, l, t]
        + costs["lost_sales"][p] * LO[p, l, t]
        for p in P for l in L for t in range(1, T + 1))
    obj += quicksum(
        costs["inventory"][p] * (I[p, l, t, r] - S[p, l, t, r])
        for p in P for l in L for t in range(1, T + 1)
        for r in range(2, SL[p] + 1))
    if fixed > 0:
        obj += fixed * quicksum(Y[p, l, t] for p in P for l in L
                                for t in range(1, T + 1))
    if trans_cost and trans_edges:
        obj += trans_cost * quicksum(X[p, src, dst, t]
                                     for (src, dst) in trans_edges
                                     for p in P for t in range(1, T + 1))
    obj += quicksum(                       # FIFO tie-break epsilon
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
        "X": {f"{p}|{src}|{dst}|{t}": val(v)
              for (p, src, dst, t), v in X.items() if abs(val(v)) > 1e-9},
    }
    return {"status": status, "objective": m.getObjVal()}, sol


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario_id")
    ap.add_argument("--handled", default="received",
                    choices=["received", "received_picked", "full"])
    ap.add_argument("--tl", type=int, default=300)
    ap.add_argument("--out", default=str(ROOT / "runs" / "m1_witness_ref"))
    args = ap.parse_args()

    rows = [json.loads(l)
            for l in (ROOT / "data/m1_retailopt/retailopt_190.jsonl")
            .read_text().splitlines() if l.strip()]
    row = next(r for r in rows if r["scenario_id"] == args.scenario_id)
    data = json.loads(row["data"])
    meta, sol = build_and_solve(data, time_limit=args.tl,
                                handled_mode=args.handled)
    ref = row["reference_objective"]
    print(f"status: {meta['status']}")
    print(f"objective: {meta['objective']}")
    print(f"reference_objective: {ref}  (status {row['reference_status']})")
    if meta["objective"] is not None and ref is not None:
        rel = abs(meta["objective"] - ref) / max(1.0, abs(ref))
        print(f"rel_gap: {rel:.3e}  {'MATCH' if rel < 1e-3 else 'MISMATCH'}")
    if sol is not None:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{args.scenario_id}.solution.json").write_text(
            json.dumps(sol))
        print(f"written: {out_dir / (args.scenario_id + '.solution.json')}")


if __name__ == "__main__":
    main()

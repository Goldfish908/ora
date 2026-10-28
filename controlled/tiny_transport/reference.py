"""LP-vertex-enumeration reference for tiny_transport.

Builds the transportation LP directly from the CSV data, enumerates all basic
feasible solutions (vertices) by solving 6x6 boundary systems with numpy, and
prints the optimal cost. Independent of any MIP solver.
"""
import csv
import itertools
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent / "data"

BOX_TO_PIECES = 10
MIN_FROM_P2 = 20
TOL = 1e-7


def main():
    with open(DATA / "supply.csv", newline="") as f:
        supply = {r["plant"]: float(r["supply"]) for r in csv.DictReader(f)}
    with open(DATA / "demand.csv", newline="") as f:
        demand = {r["warehouse"]: float(r["demand"]) * BOX_TO_PIECES for r in csv.DictReader(f)}
    costs = {}
    with open(DATA / "costs.csv", newline="") as f:
        for r in csv.DictReader(f):
            costs[(r["plant"], r["warehouse"])] = float(r["cost"])

    plants = sorted(supply)
    warehouses = sorted(demand)
    lanes = [(p, w) for p in plants for w in warehouses]
    idx = {lane: i for i, lane in enumerate(lanes)}
    n = len(lanes)

    # All constraints as a_i . x <= b_i
    cons = []
    for lane in lanes:  # x_lane >= 0
        row = np.zeros(n)
        row[idx[lane]] = -1.0
        cons.append((row, 0.0))
    for p in plants:  # supply capacity
        row = np.zeros(n)
        for w in warehouses:
            row[idx[p, w]] = 1.0
        cons.append((row, supply[p]))
    for w in warehouses:  # demand, as both inequalities
        row = np.zeros(n)
        for p in plants:
            row[idx[p, w]] = 1.0
        cons.append((row.copy(), demand[w]))
        cons.append((-row, -demand[w]))
    for w in warehouses:  # at least MIN_FROM_P2 pieces from P2
        row = np.zeros(n)
        row[idx["P2", w]] = -1.0
        cons.append((row, -float(MIN_FROM_P2)))

    c = np.array([costs[lane] for lane in lanes])

    def feasible(x):
        return all(float(a @ x) <= b + 1e-6 for a, b in cons)

    best = None
    for combo in itertools.combinations(range(len(cons)), n):
        A = np.array([cons[i][0] for i in combo])
        b = np.array([cons[i][1] for i in combo])
        try:
            x = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            continue
        if feasible(x):
            val = float(c @ x)
            if best is None or val < best - TOL:
                best = val
    print(f"REFERENCE {best}")


if __name__ == "__main__":
    main()

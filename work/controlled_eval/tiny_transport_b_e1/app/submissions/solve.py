"""tiny_transport solver: 2 plants, 3 warehouses, minimize shipping cost."""
import csv
import json
from pathlib import Path

from pyscipopt import Model

BASE = Path(__file__).resolve().parent
DATA = BASE.parent.parent / "data"

BOX_TO_PIECES = 10  # demand.csv is in boxes; 1 box = 10 pieces
MIN_FROM_P2 = 20    # each warehouse must receive at least 20 pieces from P2


def read_csv(name):
    with open(DATA / name, newline="") as f:
        return list(csv.DictReader(f))


def main():
    supply = {r["plant"]: float(r["supply"]) for r in read_csv("supply.csv")}
    # Convert demand from boxes to pieces.
    demand = {r["warehouse"]: float(r["demand"]) * BOX_TO_PIECES for r in read_csv("demand.csv")}
    cost_rows = read_csv("costs.csv")
    plants = sorted(supply)
    warehouses = sorted(demand)
    cost = {(r["plant"], r["warehouse"]): float(r["cost"]) for r in cost_rows}

    model = Model("tiny_transport")
    model.hideOutput()
    # One variable per lane; P2 lanes carry the supply-stability lower bound.
    x = {}
    for p in plants:
        for w in warehouses:
            lb = MIN_FROM_P2 if p == "P2" else 0.0
            x[p, w] = model.addVar(lb=lb, vtype="C", name=f"x_{p}_{w}")

    # Plant capacity: total outflow bounded by supply.
    for p in plants:
        model.addCons(sum(x[p, w] for w in warehouses) <= supply[p])
    # Warehouse demand must be met exactly (in pieces).
    for w in warehouses:
        model.addCons(sum(x[p, w] for p in plants) >= demand[w])
        model.addCons(sum(x[p, w] for p in plants) <= demand[w])

    model.setObjective(sum(cost[p, w] * x[p, w] for (p, w) in x), "minimize")
    model.optimize()

    flows = [
        {"plant": p, "warehouse": w, "qty": model.getVal(x[p, w])}
        for (p, w) in sorted(x)
        if model.getVal(x[p, w]) > 1e-9
    ]
    objective = sum(cost[f["plant"], f["warehouse"]] * f["qty"] for f in flows)

    with open(BASE / "solution.json", "w") as f:
        json.dump({"objective": objective, "flows": flows}, f, indent=2)
    print(f"OBJECTIVE {objective}")


if __name__ == "__main__":
    main()

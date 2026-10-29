"""tiny_transport solver: 2 plants, 3 warehouses, minimize shipping cost."""
import csv
import json
from pathlib import Path

from pyscipopt import Model, quicksum

BASE = Path(__file__).resolve().parent
DATA = BASE.parent.parent / "data"

BOX_TO_PIECES = 10  # demand.csv is in boxes; 1 box = 10 pieces
MIN_FROM_P2 = 20    # each warehouse must receive at least 20 pieces from P2

def load_data():
    with open(DATA / "supply.csv", newline="") as f:
        supply = {r["plant"]: float(r["supply"]) for r in csv.DictReader(f)}
    with open(DATA / "demand.csv", newline="") as f:
        demand = {r["warehouse"]: float(r["demand"]) for r in csv.DictReader(f)}
    costs = {}
    with open(DATA / "costs.csv", newline="") as f:
        for r in csv.DictReader(f):
            costs[(r["plant"], r["warehouse"])] = float(r["cost"])
    return supply, demand, costs


def main():
    supply, demand, costs = load_data()
    plants = sorted(supply)
    warehouses = sorted(demand)

    model = Model("tiny_transport")
    model.hideOutput()
    x = {(p, w): model.addVar(lb=0, vtype="C", name=f"x_{p}_{w}") for p in plants for w in warehouses}

    for p in plants:
        model.addCons(quicksum(x[p, w] for w in warehouses) <= supply[p])
    for w in warehouses:
        model.addCons(quicksum(x[p, w] for p in plants) == demand[w])
    # Supply-stability rule: at least 20 pieces from P2 to each warehouse.
    for w in warehouses:
        model.addCons(x["P2", w] >= MIN_FROM_P2)

    model.setObjective(quicksum(costs[p, w] * x[p, w] for p in plants for w in warehouses), "minimize")
    model.optimize()

    flows = []
    for p in plants:
        for w in warehouses:
            q = model.getVal(x[p, w])
            if q > 1e-9:
                flows.append({"plant": p, "warehouse": w, "qty": q})
    objective = sum(costs[f["plant"], f["warehouse"]] * f["qty"] for f in flows)

    with open(BASE / "solution.json", "w") as f:
        json.dump({"objective": objective, "flows": flows}, f, indent=2)
    print(f"OBJECTIVE {objective}")


if __name__ == "__main__":
    main()

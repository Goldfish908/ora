"""tiny_assign solver: 4 workers x 4 jobs, minimize total cost."""
import csv
import json
from pathlib import Path

from pyscipopt import Model, quicksum

BASE = Path(__file__).resolve().parent
DATA = BASE.parent / "data"


def load_costs():
    costs = {}
    with open(DATA / "costs.csv", newline="") as f:
        for row in csv.DictReader(f):
            costs[(row["worker"], row["job"])] = float(row["cost"])
    return costs


def main():
    costs = load_costs()
    workers = sorted({w for w, _ in costs})
    jobs = sorted({j for _, j in costs})

    model = Model("tiny_assign")
    model.hideOutput()
    x = {(w, j): model.addVar(vtype="B", name=f"x_{w}_{j}") for w in workers for j in jobs}

    for w in workers:
        model.addCons(quicksum(x[w, j] for j in jobs) <= 1)
    for j in jobs:
        model.addCons(quicksum(x[w, j] for w in workers) == 1)
    # W2 is not qualified for J3.
    model.addCons(x["W2", "J3"] == 0)

    model.setObjective(quicksum(costs[w, j] * x[w, j] for w in workers for j in jobs), "minimize")
    model.optimize()

    assignments = []
    for w in workers:
        for j in jobs:
            if model.getVal(x[w, j]) > 0.5:
                assignments.append({"worker": w, "job": j, "cost": costs[w, j]})
    objective = sum(a["cost"] for a in assignments)

    with open(BASE / "solution.json", "w") as f:
        json.dump({"objective": objective, "assignments": assignments}, f, indent=2)
    print(f"OBJECTIVE {objective}")


if __name__ == "__main__":
    main()

"""tiny_assign solver: 4 workers x 4 jobs, minimize total cost."""
import csv
import json
from pathlib import Path

from pyscipopt import Model

BASE = Path(__file__).resolve().parent
DATA = BASE.parent.parent / "data"

# W2 is not qualified for J3.
FORBIDDEN = [("W2", "J3")]


def main():
    with open(DATA / "costs.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    workers = sorted({r["worker"] for r in rows})
    jobs = sorted({r["job"] for r in rows})
    cost = {(r["worker"], r["job"]): float(r["cost"]) for r in rows}

    model = Model("tiny_assign")
    model.hideOutput()
    x = {}
    for r in rows:
        x[r["worker"], r["job"]] = model.addVar(vtype="B", name=f"x_{r['worker']}_{r['job']}")

    # Each job is done by exactly one worker.
    for j in jobs:
        model.addCons(sum(x[w, j] for w in workers if (w, j) in x) == 1)
    # Each worker takes at most one job.
    for w in workers:
        model.addCons(sum(x[w, j] for j in jobs if (w, j) in x) <= 1)
    # Forbidden assignments: fix the variable to zero.
    for w, j in FORBIDDEN:
        model.chgVarUb(x[w, j], 0.0)

    model.setObjective(sum(cost[w, j] * x[w, j] for (w, j) in x), "minimize")
    model.optimize()

    assignments = [
        {"worker": w, "job": j, "cost": cost[w, j]}
        for (w, j) in sorted(x)
        if model.getVal(x[w, j]) > 0.5
    ]
    objective = sum(a["cost"] for a in assignments)

    with open(BASE / "solution.json", "w") as f:
        json.dump({"objective": objective, "assignments": assignments}, f, indent=2)
    print(f"OBJECTIVE {objective}")


if __name__ == "__main__":
    main()

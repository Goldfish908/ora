"""tiny_sched solver: 5 jobs, 2 machines, precedence J1 -> J3, minimize makespan."""
import csv
import json
from pathlib import Path

from pyscipopt import Model, quicksum

BASE = Path(__file__).resolve().parent
DATA = BASE.parent.parent / "data"


def load_data():
    proc = {}
    with open(DATA / "jobs.csv", newline="") as f:
        for r in csv.DictReader(f):
            proc[r["job_id"]] = float(r["proc_min"])
    with open(DATA / "machines.csv", newline="") as f:
        machines = [r["machine_id"] for r in csv.DictReader(f)]
    prec = []
    with open(DATA / "precedence.csv", newline="") as f:
        for r in csv.DictReader(f):
            prec.append((r["pred"], r["succ"]))
    return proc, machines, prec


def main():
    proc, machines, prec = load_data()
    jobs = sorted(proc)
    big_m = sum(proc.values())

    model = Model("tiny_sched")
    model.hideOutput()
    start = {j: model.addVar(lb=0, vtype="C", name=f"s_{j}") for j in jobs}
    cmax = model.addVar(lb=0, vtype="C", name="cmax")
    a = {(j, m): model.addVar(vtype="B", name=f"a_{j}_{m}") for j in jobs for m in machines}
    before = {}
    for i in jobs:
        for j in jobs:
            if i < j:
                before[i, j] = model.addVar(vtype="B", name=f"b_{i}_{j}")

    for j in jobs:
        model.addCons(quicksum(a[j, m] for m in machines) == 1)
        model.addCons(cmax >= start[j] + proc[j])

    # No overlap on each machine: disjunctive big-M constraints.
    for m in machines:
        for i in jobs:
            for j in jobs:
                if i < j:
                    model.addCons(
                        start[j] >= start[i] + proc[i] - big_m * (3 - a[i, m] - a[j, m] - before[i, j])
                    )
                    model.addCons(
                        start[i] >= start[j] + proc[j] - big_m * (2 - a[i, m] - a[j, m] + before[i, j])
                    )

    # Precedence: pred finishes before succ starts.
    for u, v in prec:
        model.addCons(start[v] >= start[u] + proc[u])

    # Primary: makespan. Tiny secondary term only breaks ties toward early starts.
    model.setObjective(cmax + 1e-4 * quicksum(start[j] for j in jobs), "minimize")
    model.optimize()

    sched = []
    for j in jobs:
        m = next(m for m in machines if model.getVal(a[j, m]) > 0.5)
        s = model.getVal(start[j])
        sched.append({"job_id": j, "machine": m, "start": s, "proc": proc[j], "end": s + proc[j]})
    makespan = max(j["end"] for j in sched)

    with open(BASE / "solution.json", "w") as f:
        json.dump({"makespan": makespan, "jobs": sched}, f, indent=2)
    print(f"OBJECTIVE {makespan}")


if __name__ == "__main__":
    main()

"""tiny_sched solver: 5 jobs, 2 machines, precedence J1 -> J3, minimize makespan."""
import csv
import json
from itertools import combinations
from pathlib import Path

from pyscipopt import Model

BASE = Path(__file__).resolve().parent
DATA = BASE.parent.parent / "data"


def read_csv(name):
    with open(DATA / name, newline="") as f:
        return list(csv.DictReader(f))


def main():
    job_rows = read_csv("jobs.csv")
    proc = {r["job_id"]: float(r["proc_min"]) for r in job_rows}
    machines = [r["machine_id"] for r in read_csv("machines.csv")]
    prec = [(r["pred"], r["succ"]) for r in read_csv("precedence.csv")]
    jobs = sorted(proc)
    horizon = sum(proc.values())

    model = Model("tiny_sched")
    model.hideOutput()

    start = {}
    for j in jobs:
        start[j] = model.addVar(lb=0, ub=horizon, vtype="C", name=f"s_{j}")
    cmax = model.addVar(lb=0, vtype="C", name="cmax")
    on = {}
    for m in machines:
        for j in jobs:
            on[m, j] = model.addVar(vtype="B", name=f"on_{m}_{j}")
    order = {}
    for i, j in combinations(jobs, 2):
        order[i, j] = model.addVar(vtype="B", name=f"ord_{i}_{j}")

    # Each job on exactly one machine; makespan covers every completion.
    for j in jobs:
        model.addCons(sum(on[m, j] for m in machines) == 1)
        model.addCons(start[j] + proc[j] <= cmax)

    # Same-machine pairs cannot overlap: one must finish before the other starts.
    for m in machines:
        for i, j in combinations(jobs, 2):
            model.addCons(
                start[i] + proc[i] <= start[j] + horizon * (3 - on[m, i] - on[m, j] - order[i, j])
            )
            model.addCons(
                start[j] + proc[j] <= start[i] + horizon * (2 - on[m, i] - on[m, j] + order[i, j])
            )

    # Precedence: pred finishes before succ starts.
    for u, v in prec:
        model.addCons(start[u] + proc[u] <= start[v])

    model.setObjective(cmax + 0.0001 * sum(start[j] for j in jobs), "minimize")
    model.optimize()

    sched = []
    for j in jobs:
        m = next(m for m in machines if model.getVal(on[m, j]) > 0.5)
        s = model.getVal(start[j])
        sched.append({"job_id": j, "machine": m, "start": s, "proc": proc[j], "end": s + proc[j]})
    makespan = max(j["end"] for j in sched)

    with open(BASE / "solution.json", "w") as f:
        json.dump({"makespan": makespan, "jobs": sched}, f, indent=2)
    print(f"OBJECTIVE {makespan}")


if __name__ == "__main__":
    main()

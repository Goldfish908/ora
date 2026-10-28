"""Pure-enumeration reference for tiny_sched.

Enumerates every job-to-machine assignment (2^5) and every per-machine job
order, computes the earliest schedule honoring the precedence pair(s) from
precedence.csv, and prints the true optimal makespan. No MIP/CP solver.
Only precedence pairs (pred, succ) where pred has itself no predecessor are
supported, which covers data/precedence.csv (J1 -> J3).
"""
import csv
import itertools
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"


def main():
    with open(DATA / "jobs.csv", newline="") as f:
        proc = {r["job_id"]: float(r["proc_min"]) for r in csv.DictReader(f)}
    with open(DATA / "machines.csv", newline="") as f:
        machines = [r["machine_id"] for r in csv.DictReader(f)]
    with open(DATA / "precedence.csv", newline="") as f:
        prec = [(r["pred"], r["succ"]) for r in csv.DictReader(f)]
    jobs = sorted(proc)
    pred_of = {v: u for u, v in prec}

    def simulate(machine, order, end):
        """Schedule jobs in `order` on one machine given known pred end times.
        Returns dict of new end times, or None if a job's predecessor is on
        this machine but appears later in the order (infeasible)."""
        free = 0.0
        out = {}
        for j in order:
            s = free
            if j in pred_of:
                u = pred_of[j]
                if u not in end and u not in out:
                    return None
                s = max(s, out.get(u, end.get(u)))
            out[j] = s + proc[j]
            free = out[j]
        return out

    best = None
    for assignment in itertools.product(machines, repeat=len(jobs)):
        amap = dict(zip(jobs, assignment))
        per_machine = {m: [j for j in jobs if amap[j] == m] for m in machines}
        order_lists = [itertools.permutations(per_machine[m]) for m in machines]
        for combo in itertools.product(*order_lists):
            orders = dict(zip(machines, combo))
            # Simulate machines whose jobs have no external predecessor first.
            end = {}
            pending = list(machines)
            ok = True
            while pending and ok:
                progressed = False
                still = []
                for m in pending:
                    res = simulate(m, orders[m], end)
                    if res is None:
                        # may be waiting for a predecessor on a pending machine
                        deps = {pred_of[j] for j in orders[m] if j in pred_of}
                        if any(d not in end for d in deps):
                            still.append(m)
                            continue
                        ok = False
                        break
                    end.update(res)
                    progressed = True
                if not ok:
                    break
                pending = still
                if not progressed:
                    ok = False
            if not ok or len(end) != len(jobs):
                continue
            makespan = max(end.values())
            if best is None or makespan < best:
                best = makespan
    print(f"REFERENCE {best}")


if __name__ == "__main__":
    main()

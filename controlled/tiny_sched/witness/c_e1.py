"""Witness for tiny_sched artifact "correct".

Runs the artifact's solve.py, then checks solution.json against the business
rules (each job once, proc equals jobs.csv proc_min, precedence pred end <=
succ start, no same-machine overlap) and the makespan against the independent
enumeration reference (tol 1e-6).
Prints "WITNESS PASS" (exit 0) or "WITNESS FAIL: <reason>" (exit 1).
"""
import csv
import json
import re
import subprocess
import sys
from itertools import combinations
from pathlib import Path

PY = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"
AID = "c_e1"
TOL = 1e-6

PROB = Path(__file__).resolve().parent.parent


def fail(reason):
    print(f"WITNESS FAIL: {reason}")
    sys.exit(1)


def artifact_dir():
    if AID == "correct":
        return PROB / "correct"
    for sub in ("mutants", "equivalent"):
        cand = PROB / sub / AID
        if cand.is_dir():
            return cand
    fail(f"artifact directory for {AID} not found")


def main():
    art = artifact_dir()
    proc_run = subprocess.run(
        [PY, str(art / "solve.py")],
        cwd=art, capture_output=True, text=True, timeout=60,
    )
    sys.stdout.write(proc_run.stdout)
    if proc_run.returncode != 0:
        fail(f"solve.py exited with code {proc_run.returncode}: {proc_run.stderr.strip()[:300]}")

    sol_path = art / "solution.json"
    if not sol_path.exists():
        fail("solution.json was not produced (model infeasible or solve failed)")
    sol = json.loads(sol_path.read_text())

    ref = subprocess.run(
        [PY, str(PROB / "reference.py")], capture_output=True, text=True, timeout=60,
    )
    m = re.search(r"REFERENCE\s+([0-9.eE+-]+)", ref.stdout)
    if not m:
        fail("reference.py did not print a REFERENCE value")
    ref_obj = float(m.group(1))

    with open(PROB / "data" / "jobs.csv", newline="") as f:
        proc = {r["job_id"]: float(r["proc_min"]) for r in csv.DictReader(f)}
    with open(PROB / "data" / "machines.csv", newline="") as f:
        machines = {r["machine_id"] for r in csv.DictReader(f)}
    with open(PROB / "data" / "precedence.csv", newline="") as f:
        prec = [(r["pred"], r["succ"]) for r in csv.DictReader(f)]

    sched = sol.get("jobs")
    if not isinstance(sched, list):
        fail("solution.json has no jobs list")
    ids = [j["job_id"] for j in sched]
    if sorted(ids) != sorted(proc):
        fail(f"each job must appear exactly once; got {sorted(ids)}")

    info = {}
    for j in sched:
        if j["machine"] not in machines:
            fail(f"job {j['job_id']} assigned to unknown machine {j['machine']}")
        if abs(j["end"] - j["start"] - j["proc"]) > TOL:
            fail(f"job {j['job_id']}: end - start != proc")
        if abs(j["proc"] - proc[j["job_id"]]) > TOL:
            fail(
                f"job {j['job_id']}: proc used ({j['proc']}) != proc_min from jobs.csv ({proc[j['job_id']]})"
            )
        info[j["job_id"]] = j

    for u, v in prec:
        if info[u]["end"] > info[v]["start"] + TOL:
            fail(
                f"precedence violated: {u} ends at {info[u]['end']} but {v} starts at {info[v]['start']}"
            )

    by_machine = {}
    for j in sched:
        by_machine.setdefault(j["machine"], []).append(j)
    for mch, js in by_machine.items():
        for x, y in combinations(js, 2):
            if min(x["end"], y["end"]) - max(x["start"], y["start"]) > TOL:
                fail(
                    f"overlap on machine {mch}: {x['job_id']} [{x['start']},{x['end']}) vs "
                    f"{y['job_id']} [{y['start']},{y['end']})"
                )

    recomputed = max(j["end"] for j in sched)
    if abs(float(sol.get("makespan", float("nan"))) - recomputed) > TOL:
        fail(f"reported makespan {sol.get('makespan')} != max end {recomputed}")
    if abs(recomputed - ref_obj) > TOL:
        fail(f"makespan {recomputed} != reference optimum {ref_obj}")

    print("WITNESS PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()

"""Witness for tiny_assign artifact "correct".

Runs the artifact's solve.py, then checks solution.json against the business
rules (one-to-one assignment, W2 cannot take J3) and against the independent
brute-force reference objective (tolerance 1e-6).
Prints "WITNESS PASS" (exit 0) or "WITNESS FAIL: <reason>" (exit 1).
"""
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

PY = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"
AID = "a_m2"
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
    proc = subprocess.run(
        [PY, str(art / "solve.py")],
        cwd=art, capture_output=True, text=True, timeout=60,
    )
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        fail(f"solve.py exited with code {proc.returncode}: {proc.stderr.strip()[:300]}")

    sol_path = art / "solution.json"
    if not sol_path.exists():
        fail("solution.json was not produced")
    sol = json.loads(sol_path.read_text())

    ref = subprocess.run(
        [PY, str(PROB / "reference.py")], capture_output=True, text=True, timeout=60,
    )
    m = re.search(r"REFERENCE\s+([0-9.eE+-]+)", ref.stdout)
    if not m:
        fail("reference.py did not print a REFERENCE value")
    ref_obj = float(m.group(1))

    costs = {}
    with open(PROB / "data" / "costs.csv", newline="") as f:
        for row in csv.DictReader(f):
            costs[(row["worker"], row["job"])] = float(row["cost"])
    workers = sorted({w for w, _ in costs})
    jobs = sorted({j for _, j in costs})

    assigns = sol.get("assignments")
    if not isinstance(assigns, list):
        fail("solution.json has no assignments list")

    seen_jobs = [a["job"] for a in assigns]
    if sorted(seen_jobs) != jobs:
        fail(f"each job must be assigned exactly once; got {sorted(seen_jobs)}")
    seen_workers = [a["worker"] for a in assigns]
    if len(set(seen_workers)) != len(seen_workers):
        fail(f"a worker is assigned more than one task: {sorted(seen_workers)}")
    for a in assigns:
        if (a["worker"], a["job"]) not in costs:
            fail(f"unknown pair {a['worker']}-{a['job']}")
    if ("W2", "J3") in {(a["worker"], a["job"]) for a in assigns}:
        fail("business rule violated: W2 assigned to J3")

    recomputed = sum(costs[(a["worker"], a["job"])] for a in assigns)
    if abs(float(sol.get("objective", float("nan"))) - recomputed) > TOL:
        fail(f"reported objective {sol.get('objective')} != recomputed {recomputed}")
    if abs(recomputed - ref_obj) > TOL:
        fail(f"objective {recomputed} != reference optimum {ref_obj}")

    print("WITNESS PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()

"""Brute-force reference for tiny_assign: enumerate all one-to-one assignments
respecting the W2-J3 qualification ban, print the true optimal total cost."""
import csv
import itertools
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"


def main():
    costs = {}
    with open(DATA / "costs.csv", newline="") as f:
        for row in csv.DictReader(f):
            costs[(row["worker"], row["job"])] = float(row["cost"])
    workers = sorted({w for w, _ in costs})
    jobs = sorted({j for _, j in costs})

    best = None
    for perm in itertools.permutations(workers, len(jobs)):
        pairs = list(zip(perm, jobs))
        if ("W2", "J3") in pairs:
            continue
        total = sum(costs[p] for p in pairs)
        if best is None or total < best:
            best = total
    print(f"REFERENCE {best}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""M3 analysis: IndustryOR zero-adaptation three arms vs references.

Reads runs/industryor/m3_{z0,z1,z2}_s*.jsonl, takes the LAST round per
(arm, id) as the arm's final state (loops stop early on printed objective),
and reports executability / Acc@tol / phantom-proxy by difficulty.

Phantom proxy (cold-start): a cell whose loop stopped cleanly (objective
printed) but |obj - ref| / |ref| > tol. Without a semantic auditor these are
invisible at run time — that invisibility is the phenomenon under study.
"""
from __future__ import annotations

import glob
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARMS = ["z0", "z1", "z2"]
TOLS = [1e-4, 1e-3, 1e-2]
DIFFS = ["Easy", "Medium", "Hard"]


def load(arm: str) -> dict[int, dict]:
    best: dict[int, dict] = {}
    for fp in sorted(glob.glob(str(ROOT / "runs" / "industryor"
                                     / f"m3_{arm}_s*.jsonl"))):
        for line in open(fp):
            r = json.loads(line)
            pid = r["id"]
            if pid not in best or r["round"] > best[pid]["round"]:
                best[pid] = r
    return best


def verdict(r: dict) -> str:
    if r.get("exec_status") != "ok":
        return "exec_fail"          # crash / timeout / llm_error
    if r.get("objective") is None:
        return "no_objective"
    return "solved"                 # printed an objective (correctness TBD)


def acc(r: dict, tol: float) -> bool:
    if r.get("objective") is None:
        return False
    ref = r["reference"]
    return abs(r["objective"] - ref) / max(abs(ref), 1e-9) <= tol


def main() -> None:
    arms = {a: load(a) for a in ARMS}
    for a in ARMS:
        print(f"{a}: {len(arms[a])} cells")

    print("\n## 主表(最后一轮口径)\n")
    hdr = "| 臂 | n | 可执行 | " + " | ".join(f"Acc@{t:g}" for t in TOLS) \
        + " | 幻影代理(出解但错) |"
    print(hdr)
    print("|---|---|---|---|---|---|---|")
    for a in ARMS:
        rs = arms[a]
        n = len(rs)
        ex = sum(1 for r in rs.values() if verdict(r) == "solved")
        accs = [sum(1 for r in rs.values() if acc(r, t)) for t in TOLS]
        ph = sum(1 for r in rs.values()
                 if verdict(r) == "solved" and not acc(r, 1e-3))
        print(f"| {a} | {n} | {ex} ({ex / max(n, 1):.1%}) | "
              + " | ".join(f"{c} ({c / max(n, 1):.1%})" for c in accs)
              + f" | {ph} ({ph / max(ex, 1):.1%} of exec) |")

    print("\n## 难度分层(Acc@1e-3)\n")
    print("| 臂 | Easy | Medium | Hard |")
    print("|---|---|---|---|")
    for a in ARMS:
        cells = defaultdict(list)
        for r in arms[a].values():
            cells[r["difficulty"]].append(r)
        row = []
        for d in DIFFS:
            rs = cells[d]
            c = sum(1 for r in rs if acc(r, 1e-3))
            row.append(f"{c}/{len(rs)} ({c / max(len(rs), 1):.1%})")
        print(f"| {a} | " + " | ".join(row) + " |")

    print("\n## 失败类型分布(最后一轮)\n")
    print("| 臂 | crash | timeout | infeasible 声明 | 无目标值 | 出解 |")
    print("|---|---|---|---|---|---|")
    for a in ARMS:
        c = defaultdict(int)
        for r in arms[a].values():
            v = verdict(r)
            if v == "solved":
                c["solved"] += 1
            elif v == "no_objective":
                c["no_obj"] += 1
            elif r.get("solver_status") == "infeasible":
                c["infeasible"] += 1
            elif r.get("exec_status") == "timeout":
                c["timeout"] += 1
            else:
                c["crash"] += 1
        print(f"| {a} | {c['crash']} | {c['timeout']} | {c['infeasible']} "
              f"| {c['no_obj']} | {c['solved']} |")


if __name__ == "__main__":
    main()

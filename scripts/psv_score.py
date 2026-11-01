#!/usr/bin/env python3
"""Phase C scoring: join code_checks with witness ground truth.

BLOCK rule (deterministic): a cell is BLOCKed iff any requirement check is
missing/wrong, or 'implemented' without a non-empty evidence citation.

Metrics per mode: phantom recall (BLOCKed / all phantoms), win pass-through
(unBLOCKed / all wins -- must stay near 1.0), per-requirement-type miss counts
cross-tabbed with witness rule ids.

Usage: python3 scripts/psv_score.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PILOT = ROOT / "runs" / "m1_pilot"
PSV = ROOT / "runs" / "presolve"


def load_ground_truth() -> dict:
    rows = {}
    files = ["m1_pilot_schema_sol"] + [f"m1_pilot_schema_sol_v{v}" for v in range(1, 5)]
    for f in files:
        for line in open(PILOT / f"{f}.jsonl"):
            r = json.loads(line)
            rows[(r["scenario_id"], r["thinking"])] = r
    return rows


def classify(r: dict) -> str:
    if r["exec_status"] != "ok":
        return "crash"
    if r["witness"] != "feasible":
        return "phantom"
    return "win" if r["grade"] == "match" else "other"


def blocked(checks: list[dict]) -> tuple[bool, list[dict]]:
    bad = []
    for c in checks:
        st = c.get("status")
        ev = (c.get("evidence") or "").strip()
        if st in ("missing", "wrong") or (st == "implemented" and not ev):
            bad.append(c)
    return bool(bad), bad


def main() -> None:
    gt = load_ground_truth()
    checks = {}
    n_err = 0
    for line in open(PSV / "code_checks.jsonl"):
        r = json.loads(line)
        if r.get("checks"):
            checks[(r["scenario_id"], r["thinking"])] = r["checks"]
        else:
            n_err += 1

    rows = []
    for key, g in gt.items():
        if key not in checks:
            continue
        b, bad = blocked(checks[key])
        rows.append({"key": key, "gt": classify(g), "blocked": b,
                     "bad": bad, "witness_rules": g.get("witness_rules", [])})

    lines = ["# Phase C: pre-solve verifier (ledger checklist) offline scoring", ""]
    lines.append(f"cells scored: {len(rows)} (llm errors skipped: {n_err})")
    lines.append("")
    for mode in ("on", "off"):
        sel = [r for r in rows if r["key"][1] == mode]
        phan = [r for r in sel if r["gt"] == "phantom"]
        wins = [r for r in sel if r["gt"] == "win"]
        crash = [r for r in sel if r["gt"] == "crash"]
        pr = sum(r["blocked"] for r in phan)
        pt = sum(not r["blocked"] for r in wins)
        cf = sum(r["blocked"] for r in crash)
        lines.append(
            f"- **{mode}**: n={len(sel)}; phantom recall {pr}/{len(phan)} "
            f"({pr/len(phan):.1%})" if phan else f"- **{mode}**: no phantoms")
        lines[-1] += (
            f"; win pass-through {pt}/{len(wins)} "
            f"({pt/len(wins):.1%})" if wins else "; no wins")
        lines[-1] += f"; crash also-blocked {cf}/{len(crash)}"

    # which witness-rule failures did the verifier catch?
    lines.append("")
    lines.append("## Phantom catch rate by witness rule (a cell may have several)")
    lines.append("")
    lines.append("| witness rule | phantoms w/ rule | blocked | rate |")
    lines.append("|---|---|---|---|")
    by_rule = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["gt"] != "phantom":
            continue
        for w in set(r["witness_rules"]):
            by_rule[w][0] += 1
            by_rule[w][1] += int(r["blocked"])
    for w, (n, b) in sorted(by_rule.items(), key=lambda x: -x[1][0]):
        lines.append(f"| {w} | {n} | {b} | {b/n:.0%} |")

    # false blocks on wins: what did it flag?
    lines.append("")
    lines.append("## False BLOCKs on wins (should be empty)")
    lines.append("")
    for r in rows:
        if r["gt"] == "win" and r["blocked"]:
            lines.append(f"- {r['key'][0]}__{r['key'][1]}: "
                         + "; ".join(f"{c['id']}={c['status']} {c.get('note','')[:60]}"
                                     for c in r["bad"]))
    out = "\n".join(lines) + "\n"
    (PSV / "phase_c_summary.md").write_text(out)
    print(out)


if __name__ == "__main__":
    main()

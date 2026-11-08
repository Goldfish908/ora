#!/usr/bin/env python3
"""Phase-C gate verdicts for the P3 (semantic-memory) pilot round-1 code.

Identical check to scripts/psv_check_code.py, but reads gen.py from the P3
pilot sandboxes (runs/m1_pilot_priors3) and only checks cells that FAILED
round 1 (the only cells that enter the loop, hence the only ones whose
verdicts m1_presolve_loop --r1-checks will consume).

Output: runs/presolve/code_checks_p3.jsonl

Usage (from /home/hewj13/wm/ora):
    source ~/.leagent_env
    python3 scripts/psv_check_p3.py --limit 4    # smoke
    python3 scripts/psv_check_p3.py              # all failing cells
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.m1_feedback import failure_type  # noqa: E402
from scripts.psv_check_code import REQ, check_one  # noqa: E402

P3 = ROOT / "runs" / "m1_pilot_priors3"
OUT = ROOT / "runs" / "presolve" / "code_checks_p3.jsonl"


def load_code(scen: str, mode: str) -> str | None:
    cand = P3 / "sandbox" / f"schema_sol__{scen}__{mode}" / "gen.py"
    return cand.read_text() if cand.exists() else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    ledgers = {}
    for line in open(REQ):
        r = json.loads(line)
        if r.get("ledger"):
            ledgers[r["scenario_id"]] = r["ledger"]

    cells = []
    for f in sorted(P3.glob("m1_pilot_schema_sol_p3_v*.jsonl")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            scen, mode = r["scenario_id"], r["thinking"]
            if scen not in ledgers or failure_type(r) is None:
                continue
            code = load_code(scen, mode)
            if code:
                cells.append((scen, mode, code))

    done = set()
    if OUT.exists():
        for line in open(OUT):
            r = json.loads(line)
            if r.get("checks"):
                done.add((r["scenario_id"], r["thinking"]))
    todo = [c for c in cells if (c[0], c[1]) not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"cells={len(cells)} todo={len(todo)} cached={len(done)}", flush=True)

    with open(OUT, "a") as f:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for res in ex.map(lambda c: check_one(c[0], c[1], ledgers[c[0]], c[2]), todo):
                f.write(json.dumps(res) + "\n")
                f.flush()
                ok = "ok" if res["checks"] else f"ERR {res['error']}"
                print(f"{res['scenario_id']}__{res['thinking']}: {ok} "
                      f"{res['latency_s']}s", flush=True)


if __name__ == "__main__":
    main()

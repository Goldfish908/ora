#!/usr/bin/env python3
"""P-arm recovery: re-execute sandbox gen.py for the priors pilot.

The first P-arm run wrote LLM-generated code correctly but executed it via a
relative sandbox path, so every record is a spurious crash
("[Errno 2] No such file or directory"). Generation is expensive and already
done; this script re-runs execution + grade + witness with absolute paths and
rewrites the jsonl records in place (originals backed up as *.badexec.bak).

Usage (from /home/hewj13/wm/ora):
    python3 scripts/recover_priors_exec.py
"""

from __future__ import annotations

import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.m1_pilot import run_code, run_witness, grade, DATA  # noqa: E402

PRIORS = ROOT / "runs" / "m1_pilot_priors"


def recover(rec: dict, ds_rows: dict) -> dict:
    # already recovered, or a genuine (non-path) crash: keep as-is
    if (rec.get("exec_status") != "crash"
            or "No such file" not in (rec.get("stderr_tail") or "")):
        return rec
    sid, mode = rec["scenario_id"], rec["thinking"]
    sandbox = PRIORS / "sandbox" / f"schema_sol__{sid}__{mode}"
    gen = sandbox / "gen.py"
    if not gen.exists():
        rec.update(exec_status="crash", error="recovery: gen.py missing")
        rec["true_success"] = False
        return rec
    rec.update(run_code(gen.read_text(), sandbox))
    row = ds_rows[sid]
    rec["grade"] = grade(rec.get("objective"),
                         row["reference_objective"],
                         rec.get("solver_status"))
    rec.update(run_witness(row, sandbox))
    return rec


def main() -> None:
    ds_rows = {json.loads(l)["scenario_id"]: json.loads(l)
               for l in DATA.read_text().splitlines() if l.strip()}
    for path in sorted(PRIORS.glob("m1_pilot_schema_sol_priors_v*.jsonl")):
        bak = path.with_suffix(path.suffix + ".badexec.bak")
        if not bak.exists():
            shutil.copy2(path, bak)
        recs = [json.loads(l) for l in path.read_text().splitlines()
                if l.strip()]
        with ThreadPoolExecutor(max_workers=10) as ex:
            recs = list(ex.map(lambda r: recover(r, ds_rows), recs))
        with path.open("w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        ok = sum(1 for r in recs if r.get("exec_status") == "ok")
        print(f"{path.name}: {len(recs)} records, exec ok {ok}", flush=True)


if __name__ == "__main__":
    main()

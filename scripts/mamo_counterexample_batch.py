#!/usr/bin/env python3
"""Run independent integer counterexample review for every incorrect baseline."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--baseline-tag", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--memory-file", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    baseline = [json.loads(l) for l in Path(args.baseline).read_text().splitlines() if l.strip()]
    last = {}
    for r in baseline:
        if r["id"] not in last or r["round"] > last[r["id"]]["round"]:
            last[r["id"]] = r
    outdir = Path(args.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    summary = []
    for pid, r in sorted(last.items()):
        correct = r.get("objective") is not None and abs(r["objective"] - r["reference"]) <= 0.1
        if correct:
            summary.append({"id": pid, "status": "baseline_correct_win"})
            continue
        log = outdir / f"{pid}.json"
        cmd = [sys.executable, "scripts/mamo_counterexample_revise.py", "--id", str(pid),
               "--baseline", args.baseline, "--baseline-tag", args.baseline_tag,
               "--data", args.data, "--config", args.config,
               "--memory-file", args.memory_file, "--out-log", str(log)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        rec = json.loads(log.read_text()) if log.exists() else {"id": pid, "status": "runner_error"}
        summary.append({"id": pid, "status": rec.get("status"),
                        "continuous": rec.get("continuous"), "integer": rec.get("integer"),
                        "reference": rec.get("reference"), "returncode": p.returncode})
        print(pid, rec.get("status"), flush=True)
    (outdir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Re-evaluate saved witnesses after checker-output accounting changes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.memory_witness_cegis import evaluate, load_cells


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--artifacts", required=True)
    args = ap.parse_args()
    run_dir = Path(args.run_dir)
    grouped = load_cells(Path(args.artifacts) / "cells.jsonl", None)
    for path in sorted(run_dir.glob("*/final.json")):
        final = json.loads(path.read_text())
        pid = final["id"]
        if pid not in grouped:
            print(f"{pid}: skipped, excluded from independent reference artifacts")
            continue
        script = (path.parent / "witness.py").read_text()
        old = final["evaluation"]
        new = evaluate(script, grouped[pid])
        final.setdefault("legacy_evaluation", old)
        final["evaluation"] = new
        if final["status"] != "frozen-evaluation":
            final["status"] = "dev-passed" if new["dev_passed"] else "candidate"
        path.write_text(json.dumps(final, ensure_ascii=False, indent=1) + "\n")
        print(f"{pid}: det {old['detection']:.1%}->{new['detection']:.1%} "
              f"fp {old['false_positive']:.1%}->{new['false_positive']:.1%} "
              f"unknown {old['unknown']}->{new['unknown']}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Evaluate objective-only and direct RetailOpt witness controls on NLP4LP artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from m1_witness import retailopt


def load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def metrics(rows: list[dict]) -> dict:
    wrong = [r for r in rows if r["wrong"]]
    clean = [r for r in rows if not r["wrong"]]
    tp = sum(r["fired"] for r in wrong)
    fn = len(wrong) - tp
    fp = sum(r["fired"] for r in clean)
    tn = len(clean) - fp
    return {"n": len(rows), "tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "detection": tp / max(tp + fn, 1),
            "false_positive": fp / max(fp + tn, 1),
            "unknown": sum(r.get("unknown", False) for r in rows)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--mode", choices=["objective", "direct"], required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    cells = load(Path(args.artifacts) / "cells.jsonl")
    clean_obj = {c["id"]: c["solution"]["objective"] for c in cells if c["mutation"] == "clean"}
    rows = []
    for c in cells:
        rec = {"key": c["key"], "id": c["id"], "wrong": c["wrong"]}
        if args.mode == "objective":
            reference = clean_obj[c["id"]]
            error = abs(c["solution"]["objective"] - reference) / max(1.0, abs(reference))
            rec.update(fired=error > 1e-3, unknown=False, relative_error=error)
        else:
            try:
                result = retailopt.check({}, c["solution"])
                rec.update(fired=bool(result["violations"]), unknown=False)
            except Exception:
                rec.update(fired=False, unknown=True, witness="unknown_schema")
        rows.append(rec)
    result = {"mode": args.mode, "metrics": metrics(rows), "records": rows}
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(result["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()

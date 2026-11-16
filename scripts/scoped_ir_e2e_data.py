#!/usr/bin/env python3
"""Prepare the preregistered eight-task NLP4LP integration slice."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.nlp4lp_reference import load_rows

IDS = ("prob_016", "prob_021", "prob_047", "prob_055",
       "prob_058", "prob_060", "prob_104", "prob_229")


def normalized_rows() -> list[dict]:
    rows = []
    for raw in load_rows("validation"):
        row = dict(raw)
        for field in ("solution", "problem_info", "parameters"):
            if isinstance(row[field], str):
                row[field] = json.loads(row[field])
        row["model"] = row["problem_info"]
        rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="work/scoped_ir_e2e")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = [row for row in normalized_rows() if row["id"] in IDS]
    assert {row["id"] for row in rows} == set(IDS)
    rows.sort(key=lambda row: IDS.index(row["id"]))
    data = [{"id": row["id"], "en_question": row["description"],
             "en_answer": float(row["solution"]["objective"]),
             "difficulty": "historical_validation"} for row in rows]
    schema = {row["id"]: sorted(row["solution"]["variables"]) for row in rows}
    (out / "tasks.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    (out / "solution_schema.json").write_text(json.dumps(schema, indent=1) + "\n")
    manifest = {"ids": list(IDS), "n_tasks": len(rows),
                "tasks_sha256": hashlib.sha256(
                    (out / "tasks.json").read_bytes()).hexdigest(),
                "schema_sha256": hashlib.sha256(
                    (out / "solution_schema.json").read_bytes()).hexdigest(),
                "protocol": "docs/paper/scoped_ir_e2e_protocol_v0.3.md"}
    (out / "data_manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()

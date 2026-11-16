#!/usr/bin/env python3
"""Collect all reference statuses and select only protocol-qualified BWOR references."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dvsa_reference_select import select_reference  # noqa: E402


def collect(split):
    ids = (ROOT / f"data/dvsa/bwor/{split}.txt").read_text().splitlines()
    base = ROOT / f"work/dvsa/bwor_reference/{split}"
    records = []
    for problem_id in ids:
        target = base / problem_id
        initial_path = target / "result.json"
        if not initial_path.exists():
            records.append({"problem_id": problem_id, "final_status": "missing", "eligible": False})
            continue
        initial = json.loads(initial_path.read_text())
        syntax_path = target / "result_syntax_r1.json"
        final = json.loads(syntax_path.read_text()) if syntax_path.exists() else initial
        try:
            selected = select_reference(split, problem_id)
            eligible, revision = True, selected["revision"]
        except ValueError:
            eligible, revision = False, None
        usage = [initial.get("usage") or {}]
        syntax_latency = 0
        if syntax_path.exists():
            syntax = json.loads(syntax_path.read_text())
            usage.append(syntax.get("usage") or {})
            response_path = target / "syntax_response_r1.json"
            if response_path.exists():
                syntax_latency = json.loads(response_path.read_text()).get("latency_s", 0) or 0
        records.append({"problem_id": problem_id, "initial_status": initial["status"],
                        "final_status": final["status"], "eligible": eligible,
                        "eligible_revision": revision,
                        "objective_absolute_error": final.get("objective_absolute_error"),
                        "missing_sources_n": len(final.get("missing_sources", [])),
                        "solve_status": final.get("solve", {}).get("status"),
                        "solve_error": final.get("solve", {}).get("error"),
                        "llm_calls": initial.get("llm_calls", 0) + (final.get("llm_calls", 0) if syntax_path.exists() else 0),
                        "llm_latency_s": round((initial.get("llm_latency_s") or 0) + syntax_latency, 3),
                        "total_tokens": sum(item.get("total_tokens", 0) or 0 for item in usage)})
    eligible_ids = [row["problem_id"] for row in records if row["eligible"]]
    summary = {"split": split, "n": len(ids), "eligible_n": len(eligible_ids),
               "eligible_ids": eligible_ids,
               "ineligible_ids": [row["problem_id"] for row in records if not row["eligible"]],
               "initial_status_counts": dict(Counter(row.get("initial_status") for row in records)),
               "final_status_counts": dict(Counter(row["final_status"] for row in records)),
               "llm_calls": sum(row.get("llm_calls", 0) for row in records),
               "llm_latency_s": round(sum(row.get("llm_latency_s", 0) for row in records), 3),
               "total_tokens": sum(row.get("total_tokens", 0) for row in records),
               "manual_structural_revisions_allowed": False}
    return {"protocol": "dvsa-reference-coverage-v0.1", "summary": summary, "records": records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "validation", "frozen"], required=True)
    args = parser.parse_args()
    result = collect(args.split)
    out = ROOT / f"work/dvsa/bwor_reference/{args.split}/summary.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

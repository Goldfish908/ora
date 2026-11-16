#!/usr/bin/env python3
"""Re-score saved LLM judgments after artifact deduplication, without new calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.dvsa_model import extract_json  # noqa: E402
from scripts.dvsa_llm_judge import evaluate_verdicts, public_artifacts  # noqa: E402
from scripts.dvsa_reference_select import select_reference  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "validation"], default="dev")
    parser.add_argument("--ids", nargs="+", required=True)
    parser.add_argument("--arms", nargs="+", default=["no_memory", "text_memory"])
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    source = Path(args.source)
    out = Path(args.out)
    if not source.is_absolute():
        source = ROOT / source
    if not out.is_absolute():
        out = ROOT / out
    for problem_id in args.ids:
        reference = select_reference(args.split, problem_id)
        artifacts = public_artifacts(reference)
        for arm in args.arms:
            original_dir = source / problem_id / arm
            original = json.loads((original_dir / "result.json").read_text())
            raw = (original_dir / "response.json").read_bytes()
            response = json.loads(raw)
            proposal = extract_json(response.get("content"))
            summary, records = evaluate_verdicts(artifacts, proposal)
            target = out / problem_id / arm
            target.mkdir(parents=True, exist_ok=True)
            result = {"problem_id": problem_id, "split": args.split, "arm": arm,
                      "status": "reevaluated_existing_response_not_fresh",
                      "summary": summary, "llm_calls": 0,
                      "original_generation_llm_calls": original.get("llm_calls", 1),
                      "original_usage": original.get("usage"),
                      "original_llm_latency_s": original.get("llm_latency_s"),
                      "source_response_sha256": hashlib.sha256(raw).hexdigest(),
                      "source_result": str(original_dir / "result.json"),
                      "deduplicated_input_artifacts": len(artifacts)}
            (target / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            (target / "cells.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records))
            print(f"{problem_id}/{arm}: {json.dumps(summary, ensure_ascii=False)}")


if __name__ == "__main__":
    main()

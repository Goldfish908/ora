#!/usr/bin/env python3
"""Re-execute an existing artifact with a new deterministic guard, without any LLM call."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ora_agent.cleanroom_analysis import summarize_records
from ora_agent.oragentbench import (
    execute_solver,
    official_evaluate,
    official_metrics,
    prepare_workspace,
    read_json,
    write_json,
)
from scripts.cleanroom_experiment import load_tasks, proxy_match

ROOT = Path(__file__).resolve().parents[1]


def replay_guard(packet, source_record: dict, outdir: Path) -> dict:
    workspace = outdir / "app"
    artifacts = source_record.get("artifacts")
    if not artifacts:
        return {"status": "no_artifact", "source_record": source_record}
    prepare_workspace(packet, workspace, artifacts, api_guard=True)
    execution = execute_solver(workspace, outdir / "execution")
    official = official_evaluate(packet, workspace, outdir / "official")
    metrics = official_metrics(official)
    proxy = proxy_match(packet, official)
    guard_path = workspace / "api_guard.json"
    record = {**source_record, "execution": execution, "official": official, **metrics,
              "workspace": str(workspace), "proxy_match": proxy,
              "phantom_proxy": bool(proxy) and not metrics["true_correct"],
              "api_guard": read_json(guard_path) if guard_path.exists() else None,
              "generation_error": None, "replay_kind": "deterministic_api_guard_only"}
    write_json(outdir / "record.json", record)
    return {"status": "replayed", "source_record": source_record, "record": record}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--record", action="append", required=True)
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    outdir = (ROOT / args.run_dir).resolve()
    if outdir.exists() and any(outdir.iterdir()):
        raise ValueError("guard replay directory must be new")
    packets = {packet.name: packet for packet in load_tasks(ROOT / args.tasks)}
    results = []
    for index, record_arg in enumerate(args.record):
        source_path = (ROOT / record_arg).resolve()
        source_record = read_json(source_path)
        result = replay_guard(packets[source_record["task"]], source_record,
                              outdir / f"{index:02d}_{source_record['task']}")
        result["source_path"] = str(source_path)
        results.append(result)
    records = [result["record"] for result in results if "record" in result]
    summary = summarize_records(records, expected_tasks=len(args.record))
    summary.update(llm_calls=0, mode="deterministic_guard_replay", no_evolution=True,
                   original_candidate_sha256=sorted({record["candidate_sha256"] for record in records}))
    write_json(outdir / "guard_replay_result.json", summary)
    implementation = {"files": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                for name in ("ora_agent/api_guard.py", "ora_agent/oragentbench.py",
                                             "ora_agent/cleanroom_analysis.py",
                                             "scripts/cleanroom_guard_replay.py")},
                      "tasks_sha256": hashlib.sha256((ROOT / args.tasks).read_bytes()).hexdigest(),
                      "source_records": [result["source_path"] for result in results],
                      "llm_used": False}
    write_json(outdir / "implementation.json", implementation)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

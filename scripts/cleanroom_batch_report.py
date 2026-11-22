#!/usr/bin/env python3
"""Paired B0-B3 reporting with explicit coverage, repair provenance and costs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ora_agent.cleanroom_analysis import (
    USAGE_KEYS, diagnose_record, failure_class, pair_win_safe, summarize_records,
)
from ora_agent.oragentbench import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]


def load_replay(path: Path) -> dict:
    path = (ROOT / path).resolve()
    manifest_path = path / "run.json" if path.is_dir() else path
    manifest = read_json(manifest_path)
    records = []
    for item in manifest["records"]:
        record_path = Path(item["record_path"])
        if not record_path.is_absolute():
            record_path = manifest_path.parent / record_path
        records.append(read_json(record_path))
    replay_path = manifest_path.parent / "replay_result.json"
    replay = read_json(replay_path) if replay_path.exists() else {}
    return {"manifest_path": manifest_path, "manifest": manifest, "records": records,
            "specification_sha256": replay.get("specification_sha256"),
            "provenance": replay.get("provenance", (manifest.get("evaluation") or {}).get("provenance"))}


def empty_cost() -> dict:
    return {"llm_calls": 0, "missing_usage_calls": 0, "llm_latency_seconds": 0.0,
            **{key: 0 for key in USAGE_KEYS},
            "solver_execution_time": {"recorded_calls": 0, "missing_calls": 0, "seconds": None},
            "official_evaluation_time": {"recorded_calls": 0, "missing_calls": 0, "seconds": None}}


def add_cost(total: dict, part: dict) -> None:
    for key in ("llm_calls", "missing_usage_calls", "llm_latency_seconds", *USAGE_KEYS):
        total[key] += part.get(key, 0) or 0
    for key in ("solver_execution_time", "official_evaluation_time"):
        value = part.get(key) or {}
        target = total.setdefault(key, {"recorded_calls": 0, "missing_calls": 0, "seconds": None})
        target["recorded_calls"] += value.get("recorded_calls", 0)
        target["missing_calls"] += value.get("missing_calls", 0)
        if value.get("seconds") is not None:
            target["seconds"] = (target["seconds"] or 0) + value["seconds"]


def build_arm(label: str, replay: dict, repairs: list[Path], expected_tasks: list[str],
              repair_expected: bool) -> dict:
    direct = {record["task"]: record for record in replay["records"]}
    repair_map = {}
    for path in repairs:
        result = read_json((ROOT / path).resolve())
        repair_map[result["record"]["task"]] = result
    rows = []
    final_records = []
    final_cost = empty_cost()
    for task in expected_tasks:
        before = direct.get(task)
        result = repair_map.get(task)
        final = result["record"] if result else before if not repair_expected else None
        cost = result.get("cost") if result else None
        if cost is None and final is not None:
            cost = summarize_records([final])["cost"]
        if cost is not None:
            add_cost(final_cost, cost)
        row = {"task": task,
               "direct": diagnose_record(before, include_official_errors=True) if before else {"status": "not_run"},
               "final": diagnose_record(final, include_official_errors=True) if final else {"status": "not_run"},
               "repair_status": result.get("status") if result else "not_run" if repair_expected else "not_applicable",
               "attempts_used": result.get("attempts_used") if result else 0 if not repair_expected else None,
               "coverage": final is not None,
               "unknown": final is not None and failure_class(final) == "evaluation_unknown",
               "win_safe": None if final is None else not before["true_correct"] or final["true_correct"],
               "cost": cost}
        rows.append(row)
        if final is not None:
            final_records.append(final)
    direct_records = [direct[task] for task in expected_tasks if task in direct]
    comparison = pair_win_safe(direct_records, final_records)
    for key in ("llm_latency_seconds",):
        final_cost[key] = round(final_cost[key], 6)
    for key in ("solver_execution_time", "official_evaluation_time"):
        if final_cost[key]["seconds"] is not None:
            final_cost[key]["seconds"] = round(final_cost[key]["seconds"], 6)
    return {"arm": label, "n_expected": len(expected_tasks),
            "direct": summarize_records(direct_records, len(expected_tasks)),
            "final": summarize_records(final_records, len(expected_tasks)),
            "pair_win_safe": comparison, "cost": final_cost, "tasks": rows,
            "provenance": replay["provenance"],
            "specification_sha256": replay["specification_sha256"],
            "implementation": {"path": str(replay["manifest_path"]),
                               "sha256": hashlib.sha256(replay["manifest_path"].read_bytes()).hexdigest()},
            "repair_inputs": [str((ROOT / path).resolve()) for path in repairs]}


def build(b0: Path, b1: Path, b2: Path | None, b2_repairs: list[Path],
          b3: Path | None, b3_repairs: list[Path], out: Path) -> dict:
    inputs = {"B0_empty_specification": load_replay(b0), "B1_gepa_specification": load_replay(b1)}
    if b2:
        inputs["B2_gepa_residual_dag"] = load_replay(b2)
    if b3:
        inputs["B3_verified_memory"] = load_replay(b3)
    expected_tasks = sorted({task for replay in inputs.values()
                             for task in replay["manifest"]["evaluation"]["task_ids"]})
    arms = [build_arm("B0_empty_specification", inputs["B0_empty_specification"], [], expected_tasks, False),
            build_arm("B1_gepa_specification", inputs["B1_gepa_specification"], [], expected_tasks, False)]
    if b2:
        arms.append(build_arm("B2_gepa_residual_dag", inputs["B2_gepa_residual_dag"],
                              b2_repairs, expected_tasks, True))
    else:
        arms.append({"arm": "B2_gepa_residual_dag", "status": "not_run"})
    if b3:
        arms.append(build_arm("B3_verified_memory", inputs["B3_verified_memory"],
                              b3_repairs, expected_tasks, True))
    else:
        arms.append({"arm": "B3_verified_memory", "status": "not_run"})
    b1_specs = inputs["B1_gepa_specification"]["specification_sha256"]
    b3_specs = inputs.get("B3_verified_memory", {}).get("specification_sha256")
    identity = bool(b1_specs and b3_specs and b1_specs == b3_specs)
    result = {"expected_tasks": expected_tasks, "arms": arms,
              "b0_to_b1": pair_win_safe(inputs["B0_empty_specification"]["records"],
                                         inputs["B1_gepa_specification"]["records"]),
              "b3_same_generator_specification_as_b1": identity,
              "memory_interpretation": "Identical generator specifications do not establish an incremental memory effect."
              if identity else "Compare only equal task coverage and record the authorized memory scope.",
              "selection_or_heldout": "Read each arm's provenance; this report does not relabel selection tasks as held-out."}
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "batch_summary.json", result)
    lines = ["# Clean-room B0-B3 paired report", "",
             "Only equal task sets support paired comparisons. Missing arms/tasks are not_run, never zero-filled.", "",
             "| Arm | Coverage | Direct true | Direct phantom | Final true | Final phantom | UNKNOWN | Wins +/− | Attempts | Tokens |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for arm in arms:
        if "final" not in arm:
            lines.append(f"| {arm['arm']} | not_run | — | — | — | — | — | — | — | — |")
            continue
        direct, final = arm["direct"], arm["final"]
        pair = arm["pair_win_safe"]
        attempts = sum(row["attempts_used"] or 0 for row in arm["tasks"])
        lines.append(f"| {arm['arm']} | {final['n']}/{arm['n_expected']} | {direct['true_correct']} | "
                     f"{direct['phantom_proxy']} | {final['true_correct']} | {final['phantom_proxy']} | "
                     f"{final['unknown']} | +{len(pair['gained_true_correct'])}/−{len(pair['lost_true_correct'])} | "
                     f"{attempts} | {arm['cost']['total_tokens']} |")
    lines += ["", "## Per-task outcomes", "",
              "| Task | Arm | True direct→final | Phantom direct→final | UNKNOWN | Failure after | Repair status | Attempts | Win-safe | Tokens |",
              "|---|---|---|---|---|---|---|---:|---|---:|"]
    for arm in arms:
        for row in arm.get("tasks", []):
            direct, final = row["direct"], row["final"]
            true_text = f"{direct.get('true_correct', 'not_run')}→{final.get('true_correct', 'not_run')}"
            phantom_text = f"{direct.get('phantom_proxy', 'not_run')}→{final.get('phantom_proxy', 'not_run')}"
            tokens = row["cost"]["total_tokens"] if row["cost"] else "—"
            lines.append(f"| {row['task']} | {arm['arm']} | {true_text} | {phantom_text} | "
                         f"{row['unknown']} | {final.get('failure_class', 'not_run')} | {row['repair_status']} | "
                         f"{row['attempts_used'] if row['attempts_used'] is not None else '—'} | "
                         f"{row['win_safe']} | {tokens} |")
    lines += ["", "## Interpretation", "", result["memory_interpretation"], "",
              "Cost records include LLM tokens/latency and solver/evaluator wall time in batch_summary.json. "
              "Selection tasks are not held-out. See implementation manifests and per-task records for evidence."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b0", required=True)
    parser.add_argument("--b1", required=True)
    parser.add_argument("--b2")
    parser.add_argument("--b2-repair", action="append", default=[])
    parser.add_argument("--b3")
    parser.add_argument("--b3-repair", action="append", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if bool(args.b2) != bool(args.b2_repair):
        parser.error("--b2 and at least one --b2-repair must be supplied together")
    if bool(args.b3) != bool(args.b3_repair):
        parser.error("--b3 and at least one --b3-repair must be supplied together")
    result = build(ROOT / args.b0, ROOT / args.b1,
                   ROOT / args.b2 if args.b2 else None, args.b2_repair,
                   ROOT / args.b3 if args.b3 else None, args.b3_repair, ROOT / args.out)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

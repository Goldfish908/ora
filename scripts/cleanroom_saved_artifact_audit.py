#!/usr/bin/env python3
"""Audit saved repair artifacts without generation, solving or official re-evaluation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ora_agent.cleanroom_witness import has_genuine_incumbent, repair_route
from ora_agent.oragentbench import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]


def record_audit(record: dict, source: Path) -> dict:
    errors = (record.get("official") or {}).get("evaluation", {}).get("errors") or []
    return {
        "task": record.get("task"),
        "source": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "route": repair_route(record),
        "genuine_incumbent": has_genuine_incumbent(record),
        "execution_return_code": (record.get("execution") or {}).get("return_code"),
        "feasible": bool(record.get("feasible")),
        "quality": record.get("quality"),
        "objective": record.get("objective"),
        "true_correct": bool(record.get("true_correct")),
        "unknown": bool(record.get("unknown") or record.get("evaluation_unknown")),
        "business_error_count": len(errors),
        "business_rechecked": False,
    }


def _sense(record: dict) -> str | None:
    return ((record.get("official") or {}).get("reward_details") or {}).get("objective_sense")


def _objective_rank(record: dict, reference: dict) -> float:
    value = record.get("objective")
    other = reference.get("objective")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return 0.0
    if not isinstance(other, (int, float)) or isinstance(other, bool):
        return 1.0
    sense = _sense(record) or _sense(reference)
    if sense == "maximize":
        return value - other
    if sense == "minimize":
        return other - value
    return 0.0


def best_checkpoint(records: list[dict]) -> dict:
    if not records:
        raise ValueError("at least one candidate is required")
    baseline = records[0]

    def rank(record: dict) -> tuple:
        errors = (record.get("official") or {}).get("evaluation", {}).get("errors") or []
        return (
            bool(record.get("true_correct")) and not record.get("unknown"),
            bool(record.get("feasible")) and not record.get("phantom_proxy") and not record.get("unknown"),
            float(record.get("quality") or 0.0),
            (record.get("execution") or {}).get("return_code") == 0,
            not record.get("phantom_proxy"),
            -len(errors),
            _objective_rank(record, baseline),
        )

    return max(records, key=rank)


def repair_result_audit(result: dict, source: Path) -> dict:
    if isinstance(result.get("checkpoint_record"), dict):
        checkpoint = result["checkpoint_record"]
        checkpoint_source = Path(result.get("checkpoint_record_path") or source)
    else:
        records = [result["record"]]
        for item in result.get("attempt_record_paths") or []:
            path = Path(item)
            if path.exists():
                records.append(read_json(path))
        checkpoint = best_checkpoint(records)
        checkpoint_source = Path(checkpoint["workspace"]).parent / "record.json"
    audit = record_audit(checkpoint, checkpoint_source)
    audit.update({
        "task": result["record"].get("task"),
        "repair_result": str(source),
        "repair_result_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "repair_status": result.get("status"),
        "attempts_used": result.get("attempts_used"),
        "final_record_is_checkpoint": checkpoint is result["record"],
        "checkpoint_reconstructed_from_saved_attempts": "checkpoint_record" not in result,
    })
    return audit


def run(records: list[tuple[str, Path]], repair_results: list[tuple[str, Path]], out: Path) -> dict:
    payload = {
        "schema_version": "saved_artifact_audit_v0.1",
        "scope": "offline routing and checkpoint evidence only; no new business correctness result",
        "llm_calls": 0,
        "solver_calls": 0,
        "official_evaluation_calls": 0,
        "records": [{"label": label, **record_audit(read_json(path), path)} for label, path in records],
        "repair_results": [
            {"label": label, **repair_result_audit(read_json(path), path)}
            for label, path in repair_results
        ],
    }
    write_json(out / "audit.json", payload)
    lines = [
        "# Saved-artifact audit",
        "",
        "Offline routing and checkpoint evidence only. No LLM, solver or official evaluator was called; business correctness was not rechecked.",
        "",
        "| Item | Route | Genuine incumbent | Feasible | Quality | Business errors |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in payload["records"]:
        lines.append(f"| {row['label']} | {row['route']} | {row['genuine_incumbent']} | "
                     f"{row['feasible']} | {row['quality']} | {row['business_error_count']} |")
    for row in payload["repair_results"]:
        lines.append(f"| {row['label']} checkpoint | {row['route']} | {row['genuine_incumbent']} | "
                     f"{row['feasible']} | {row['quality']} | {row['business_error_count']} |")
    (out / "report.md").write_text("\n".join(lines) + "\n")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", action="append", default=[], help="label=record.json")
    parser.add_argument("--repair-result", action="append", default=[], help="label=repair_result.json")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    def parse(items):
        parsed = []
        for item in items:
            label, separator, value = item.partition("=")
            if not separator or not label or not value:
                raise ValueError("artifact arguments must use label=path")
            parsed.append((label, (ROOT / value).resolve()))
        return parsed

    payload = run(parse(args.record), parse(args.repair_result), (ROOT / args.out).resolve())
    print(json.dumps(payload, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

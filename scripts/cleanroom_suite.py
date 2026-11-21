#!/usr/bin/env python3
"""Run independent B0/B1 replay, memory review, residual repair and B2/B3 reporting."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from ora_agent import llm as llm_mod
from ora_agent.cleanroom import EvidenceMemory, restore_specifications
from ora_agent.cleanroom_witness import initialize_witness, repair_bounded
from scripts.cleanroom_experiment import digest, load_tasks
from scripts.cleanroom_memory import select_candidate
from scripts.cleanroom_repair import record_specification
from ora_agent.oragentbench import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]


def command(args: argparse.Namespace, script: str, *arguments: str) -> None:
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    subprocess.run([sys.executable, str(ROOT / script), *arguments], cwd=ROOT,
                   env=env, check=True)


def replay(args: argparse.Namespace, arm: str, source: Path | None = None,
           candidate: dict | None = None, compare_to: Path | None = None) -> Path:
    out = args.out / arm
    result_path = out / "replay_result.json"
    if args.resume and result_path.exists():
        return out / "run.json"
    arguments = ["--tasks", str(args.audit_tasks), "--run-dir", str(out),
                 "--workers", str(args.workers), "--seed", str(args.seed),
                 "--llm-timeout", str(args.llm_timeout), "--api-guard"]
    if args.resume:
        arguments.append("--resume")
    if source is not None and candidate is not None:
        arguments += ["--gepa-result", str(source), "--candidate-idx", str(candidate["candidate_idx"]),
                      "--candidate-sha256", candidate["candidate_sha256"]]
    elif source is not None:
        arguments += ["--memory", str(source)]
    if compare_to is not None:
        arguments += ["--compare-to", str(compare_to)]
    command(args, "scripts/cleanroom_replay.py", *arguments)
    return out / "run.json"


def repair_batch(args: argparse.Namespace, arm: str, packets: list, spec_source: Path,
                 candidate: dict | None) -> list[Path]:
    out = args.out / arm
    memory = EvidenceMemory()
    oracle_source = args.witness_source
    initialization = initialize_witness(memory, args.dev_packets, out / "witness", oracle_source)
    write_json(out / "witness_initialization.json", initialization)
    source = read_json(spec_source)
    if "candidates" not in source:
        restored = restore_specifications(source)
        for asset in restored.specifications.values():
            memory.register_specification(asset)
    config = llm_mod.load_config()
    results = []
    for packet in packets:
        manifest_path = args.out / ("B1" if arm == "B2" else "B3") / "run.json"
        manifest = read_json(manifest_path)
        row = next(row for row in manifest["records"] if row["task"] == packet.name)
        record_path = Path(row["record_path"])
        if not record_path.is_absolute():
            record_path = manifest_path.parent / record_path
        record = read_json(record_path)
        specification = record_specification(spec_source, record, packet, None)
        task_out = out / packet.name
        result_path = task_out / "repair_result.json"
        if args.resume and result_path.exists():
            results.append(result_path)
            continue
        if task_out.exists() and any(task_out.iterdir()):
            raise ValueError(f"partial repair cannot be silently repeated: {task_out}")
        result = repair_bounded(memory, packet, record, specification, config, task_out,
                                run_seed=args.seed, max_attempts=args.max_attempts, api_guard=True)
        write_json(result_path, result)
        write_json(task_out / "implementation.json", {
            "task": packet.name, "specification_sha256": digest(specification),
            "memory_source_sha256": hashlib.sha256(spec_source.read_bytes()).hexdigest(),
            "model": config.model, "max_attempts": args.max_attempts})
        results.append(result_path)
    if not memory.frozen:
        memory.freeze()
    write_json(out / "memory_frozen.json", memory.public_state())
    return results


def verified_promotion(memory_path: Path) -> dict:
    summary_path = memory_path.parent / "promotion_summary.json"
    if not summary_path.exists():
        raise ValueError("promoted memory requires its promotion_summary.json")
    summary = read_json(summary_path)
    audit = summary.get("audit") or {}
    if not summary.get("independent_replay") or summary.get("specification_status") != "promoted" \
            or not audit.get("changed_features_covered") or not audit.get("scope_confirmed"):
        raise ValueError("memory source has not passed independent replay and provenance audit")
    memory = restore_specifications(read_json(memory_path))
    if not any(asset.status == "promoted" for asset in memory.specifications.values()):
        raise ValueError("memory source contains no promoted specification")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gepa-run", required=True)
    parser.add_argument("--dev-tasks", required=True)
    parser.add_argument("--audit-tasks", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--witness-source")
    parser.add_argument("--memory-source")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-attempts", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--llm-timeout", type=float, default=600)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    args.gepa_run = (ROOT / args.gepa_run).resolve()
    args.dev_tasks = (ROOT / args.dev_tasks).resolve()
    args.audit_tasks = (ROOT / args.audit_tasks).resolve()
    args.witness_source = (ROOT / args.witness_source).resolve() if args.witness_source else None
    args.memory_source = (ROOT / args.memory_source).resolve() if args.memory_source else None
    args.out = (ROOT / args.out).resolve()
    if args.out.exists() and any(args.out.iterdir()) and not args.resume:
        raise ValueError("suite directory is not empty; use --resume")
    args.out.mkdir(parents=True, exist_ok=True)
    llm_mod.REQUEST_TIMEOUT_SEC = args.llm_timeout
    result_path = args.gepa_run / "gepa_result.json"
    analysis_path = args.gepa_run / "analysis.json"
    if not result_path.exists() or not analysis_path.exists():
        raise ValueError("GEPA run must be complete before starting the independent suite")
    result = read_json(result_path)
    analysis = read_json(analysis_path)
    implementation_path = args.gepa_run / "implementation.json"
    implementation = read_json(implementation_path)
    dev_sha256 = hashlib.sha256(args.dev_tasks.read_bytes()).hexdigest()
    audit_sha256 = hashlib.sha256(args.audit_tasks.read_bytes()).hexdigest()
    if implementation["tasks_sha256"] != dev_sha256:
        raise ValueError("development task config differs from the GEPA implementation")
    expected = {"gepa_implementation_sha256": hashlib.sha256(implementation_path.read_bytes()).hexdigest(),
                "dev_tasks_sha256": dev_sha256, "audit_tasks_sha256": audit_sha256,
                "memory_source_sha256": hashlib.sha256(args.memory_source.read_bytes()).hexdigest()
                if args.memory_source else None}
    previous_path = args.out / "suite_implementation.json"
    if args.resume and previous_path.exists():
        previous = read_json(previous_path)
        if any(previous.get(key) != value for key, value in expected.items()):
            raise ValueError("suite inputs changed while resuming")
    candidate = select_candidate(result_path, result, analysis)
    args.dev_packets = [packet for packet in load_tasks(args.dev_tasks) if packet.split == "dev"]
    audit_packets = load_tasks(args.audit_tasks)
    if not audit_packets or any(packet.split not in {"audit", "transfer"} for packet in audit_packets):
        raise ValueError("independent suite requires only audit/transfer tasks")
    selected_text = result["candidates"][candidate["candidate_idx"]]["conventions"]
    candidate["candidate_sha256"] = digest(selected_text)
    write_json(args.out / "candidate_selection.json", candidate)
    write_json(previous_path, {
        "script_sha256": hashlib.sha256((ROOT / "scripts/cleanroom_suite.py").read_bytes()).hexdigest(),
        **expected,
        "arguments": {key: str(value) if isinstance(value, Path) else value
                      for key, value in vars(args).items() if key != "dev_packets"}})

    b0_manifest = replay(args, "B0")
    b1_manifest = replay(args, "B1", result_path, candidate, b0_manifest)
    if args.memory_source:
        memory_path = args.memory_source
        memory_summary = verified_promotion(memory_path)
    else:
        memory_out = args.out / "memory_review"
        summary_path = memory_out / "promotion_summary.json"
        if not (args.resume and summary_path.exists()):
            command(args, "scripts/cleanroom_memory.py", "--tasks", str(args.dev_tasks),
                    "--gepa-result", str(result_path), "--analysis", str(analysis_path),
                    "--run-dir", str(memory_out), "--llm-timeout", str(args.llm_timeout),
                    "--independent-replay", str(b1_manifest), "--independent-baseline", str(b0_manifest))
        memory_summary = read_json(summary_path)
        memory_path = memory_out / "memory_promoted.json"
    promoted = memory_summary["specification_status"] == "promoted"
    b2_repairs = repair_batch(args, "B2", audit_packets, result_path, candidate)
    b3_manifest = None
    b3_repairs = []
    if promoted:
        b3_manifest = replay(args, "B3", memory_path)
        b3_repairs = repair_batch(args, "B3", audit_packets, memory_path)
    report_args = ["--b0", str(b0_manifest), "--b1", str(b1_manifest),
                   "--b2", str(b1_manifest)]
    for path in b2_repairs:
        report_args += ["--b2-repair", str(path)]
    if promoted:
        report_args += ["--b3", str(b3_manifest)]
        for path in b3_repairs:
            report_args += ["--b3-repair", str(path)]
    report_args += ["--out", str(args.out / "report")]
    command(args, "scripts/cleanroom_batch_report.py", *report_args)
    write_json(args.out / "suite_result.json", {
        "candidate": candidate, "memory_promoted": promoted,
        "b0": str(b0_manifest), "b1": str(b1_manifest),
        "b2_repairs": [str(path) for path in b2_repairs],
        "b3": str(b3_manifest) if b3_manifest else "not_run",
        "b3_repairs": [str(path) for path in b3_repairs],
        "report": str(args.out / "report/batch_summary.json")})
    print(json.dumps({"candidate_idx": candidate["candidate_idx"], "memory_promoted": promoted,
                      "report": str(args.out / "report/report.md")}, indent=1))


if __name__ == "__main__":
    main()

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
           candidate: dict | None = None, compare_to: Path | None = None,
           packets: list | None = None) -> Path:
    out = args.out / arm
    result_path = out / "replay_result.json"
    if args.resume and result_path.exists():
        return out / "run.json"
    task_path = args.audit_tasks
    if packets is not None:
        task_path = args.out / f"{arm.lower()}_tasks.json"
        write_json(task_path, {"version": f"{arm.lower()}_authorized_scope",
                               "tasks": [{"name": packet.name, "domain": packet.domain,
                                          "split": packet.split} for packet in packets]})
    arguments = ["--tasks", str(task_path), "--run-dir", str(out),
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
                 candidate: dict | None, baseline_arm: str | None = None) -> list[Path]:
    out = args.out / arm
    memory = EvidenceMemory()
    oracle_source = args.witness_source
    witness_packets = getattr(args, "witness_packets", None) or args.dev_packets
    initialization = initialize_witness(memory, witness_packets, out / "witness", oracle_source)
    write_json(out / "witness_initialization.json", initialization)
    source = read_json(spec_source)
    if "candidates" not in source:
        restored = restore_specifications(source)
        for asset in restored.specifications.values():
            memory.register_specification(asset)
    config = llm_mod.load_config()
    results = []
    for packet in packets:
        manifest_path = args.out / (baseline_arm or ("B1" if arm == "B2" else "B3")) / "run.json"
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
    if summary.get("memory_sha256") != hashlib.sha256(memory_path.read_bytes()).hexdigest():
        raise ValueError("promotion summary does not match the memory artifact")
    evidence_path = memory_path.parent / "independent_replay_evidence.json"
    if not evidence_path.exists() or summary.get("independent_replay_evidence_sha256") != \
            hashlib.sha256(evidence_path.read_bytes()).hexdigest():
        raise ValueError("promotion summary is not bound to independent replay evidence")
    evidence = read_json(evidence_path)
    comparison = evidence.get("paired_comparison") or {}
    if not evidence.get("passed") or not comparison.get("win_safe") or comparison.get("gained_phantom"):
        raise ValueError("independent replay evidence does not authorize promotion")
    for side, summary_key in (("candidate", "independent_replay_manifest_sha256"),
                              ("baseline", "independent_baseline_manifest_sha256")):
        manifest_path = Path(evidence.get(f"{side}_manifest_path", ""))
        expected_hash = evidence.get(f"{side}_manifest_sha256")
        if not manifest_path.is_file() or not expected_hash \
                or hashlib.sha256(manifest_path.read_bytes()).hexdigest() != expected_hash \
                or summary.get(summary_key) != expected_hash:
            raise ValueError(f"promotion evidence is not bound to the {side} manifest")
        manifest = read_json(manifest_path)
        if sorted(manifest.get("evaluation", {}).get("task_ids") or []) != evidence.get("task_ids"):
            raise ValueError(f"{side} replay tasks differ from the promotion evidence")
    memory = restore_specifications(read_json(memory_path))
    if not any(asset.status == "promoted" for asset in memory.specifications.values()):
        raise ValueError("memory source contains no promoted specification")
    return summary


def path_sha256(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        relative = str(item.relative_to(path))
        digest.update(relative.encode() + b"\0")
        if item.is_symlink():
            digest.update(b"symlink\0" + str(item.readlink()).encode() + b"\0")
        elif item.is_file():
            digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def packet_sha256(packet) -> str:
    digest = hashlib.sha256()
    digest.update(packet.instruction.encode() + b"\0" + packet.problem_statement.encode() + b"\0")
    for name, content in sorted(packet.public_files.items()):
        digest.update(name.encode() + b"\0" + content.encode() + b"\0")
    digest.update((path_sha256(packet.root / "tests") or "").encode())
    return digest.hexdigest()


def suite_source_hashes() -> dict[str, str]:
    names = [
        "ora_agent/llm.py", "ora_agent/cleanroom.py", "ora_agent/cleanroom_witness.py",
        "ora_agent/cleanroom_analysis.py", "ora_agent/oragentbench.py",
        "ora_agent/decision_repair.py", "ora_agent/api_guard.py",
        "scripts/cleanroom_suite.py", "scripts/cleanroom_replay.py",
        "scripts/cleanroom_experiment.py", "scripts/cleanroom_memory.py",
        "scripts/cleanroom_batch_report.py",
    ]
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def validate_suite_resume(previous_path: Path, expected: dict) -> None:
    if not previous_path.exists():
        raise ValueError("cannot resume an unbound suite directory")
    previous = read_json(previous_path)
    changed = sorted(key for key, value in expected.items() if previous.get(key) != value)
    if changed:
        raise ValueError("suite inputs changed while resuming: " + ", ".join(changed))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gepa-run", required=True)
    parser.add_argument("--dev-tasks", required=True)
    parser.add_argument("--audit-tasks", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--witness-tasks")
    parser.add_argument("--witness-source")
    parser.add_argument("--memory-source")
    parser.add_argument("--skip-memory-review", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-attempts", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--llm-timeout", type=float, default=600)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.memory_source and args.skip_memory_review:
        parser.error("--memory-source and --skip-memory-review are mutually exclusive")
    args.gepa_run = (ROOT / args.gepa_run).resolve()
    args.dev_tasks = (ROOT / args.dev_tasks).resolve()
    args.audit_tasks = (ROOT / args.audit_tasks).resolve()
    args.witness_tasks = (ROOT / args.witness_tasks).resolve() if args.witness_tasks else None
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
    witness_sha256 = hashlib.sha256(args.witness_tasks.read_bytes()).hexdigest() \
        if args.witness_tasks else None
    if implementation["tasks_sha256"] != dev_sha256:
        raise ValueError("development task config differs from the GEPA implementation")
    candidate = select_candidate(result_path, result, analysis)
    args.dev_packets = [packet for packet in load_tasks(args.dev_tasks) if packet.split == "dev"]
    args.witness_packets = load_tasks(args.witness_tasks) if args.witness_tasks else args.dev_packets
    audit_packets = load_tasks(args.audit_tasks)
    if not audit_packets or any(packet.split not in {"audit", "transfer"} for packet in audit_packets):
        raise ValueError("independent suite requires only audit/transfer tasks")
    overlap = sorted({packet.name for packet in args.witness_packets} & {packet.name for packet in audit_packets})
    if overlap:
        raise ValueError(f"Witness initialization and evaluation tasks overlap: {overlap}")
    selected_text = result["candidates"][candidate["candidate_idx"]]["conventions"]
    candidate["candidate_sha256"] = digest(selected_text)
    expected = {
        "script_sha256": hashlib.sha256((ROOT / "scripts/cleanroom_suite.py").read_bytes()).hexdigest(),
        "source_files": suite_source_hashes(),
        "gepa_implementation_sha256": hashlib.sha256(implementation_path.read_bytes()).hexdigest(),
        "gepa_result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "gepa_analysis_sha256": hashlib.sha256(analysis_path.read_bytes()).hexdigest(),
        "candidate_idx": candidate["candidate_idx"], "candidate_sha256": candidate["candidate_sha256"],
        "dev_tasks_sha256": dev_sha256, "audit_tasks_sha256": audit_sha256,
        "witness_tasks_sha256": witness_sha256,
        "dev_packet_sha256": {packet.name: packet_sha256(packet) for packet in args.dev_packets},
        "witness_packet_sha256": {packet.name: packet_sha256(packet) for packet in args.witness_packets},
        "audit_packet_sha256": {packet.name: packet_sha256(packet) for packet in audit_packets},
        "witness_source_sha256": path_sha256(args.witness_source),
        "memory_source_sha256": hashlib.sha256(args.memory_source.read_bytes()).hexdigest()
        if args.memory_source else None,
        "skip_memory_review": args.skip_memory_review, "workers": args.workers,
        "seed": args.seed, "max_attempts": args.max_attempts, "llm_timeout": args.llm_timeout,
    }
    previous_path = args.out / "suite_implementation.json"
    if args.resume:
        validate_suite_resume(previous_path, expected)
    write_json(args.out / "candidate_selection.json", candidate)
    write_json(previous_path, {
        **expected,
        "arguments": {key: str(value) if isinstance(value, Path) else value
                      for key, value in vars(args).items()
                      if key not in {"dev_packets", "witness_packets"}}})

    b0_manifest = replay(args, "B0")
    b1_manifest = replay(args, "B1", result_path, candidate, b0_manifest)
    memory_path = None
    if args.skip_memory_review:
        memory_summary = {"specification_status": "not_run", "independent_replay": False,
                          "review_skipped_by_protocol": True}
    elif args.memory_source:
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
    b3_packets = []
    if promoted:
        authorized_memory = restore_specifications(read_json(memory_path))
        b3_packets = [packet for packet in audit_packets
                      if authorized_memory.generator_specification(packet.scope) is not None]
        if b3_packets:
            b3_manifest = replay(args, "B3", memory_path, packets=b3_packets)
            b3_repairs = repair_batch(args, "B3", b3_packets, memory_path)
    report_args = ["--b0", str(b0_manifest), "--b1", str(b1_manifest),
                   "--b2", str(b1_manifest)]
    for path in b2_repairs:
        report_args += ["--b2-repair", str(path)]
    if b3_manifest is not None:
        report_args += ["--b3", str(b3_manifest)]
        for path in b3_repairs:
            report_args += ["--b3-repair", str(path)]
    report_args += ["--out", str(args.out / "report")]
    command(args, "scripts/cleanroom_batch_report.py", *report_args)
    write_json(args.out / "suite_result.json", {
        "candidate": candidate, "memory_promoted": promoted,
        "memory_review": memory_summary, "memory_source": str(memory_path) if memory_path else None,
        "b0": str(b0_manifest), "b1": str(b1_manifest),
        "b2_repairs": [str(path) for path in b2_repairs],
        "b3": str(b3_manifest) if b3_manifest else "not_run",
        "b3_repairs": [str(path) for path in b3_repairs],
        "b3_authorized_tasks": [packet.name for packet in b3_packets],
        "b3_not_run_tasks": [packet.name for packet in audit_packets
                             if packet not in b3_packets],
        "report": str(args.out / "report/batch_summary.json")})
    print(json.dumps({"candidate_idx": candidate["candidate_idx"], "memory_promoted": promoted,
                      "report": str(args.out / "report/report.md")}, indent=1))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Replay an explicit specification on a disjoint batch without evolution or feedback."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from ora_agent import llm as llm_mod
from ora_agent.cleanroom import restore_specifications
from ora_agent.cleanroom_analysis import pair_win_safe, summarize_records
from ora_agent.oragentbench import read_json, write_json
from scripts.cleanroom_experiment import CleanroomAdapter, digest, load_tasks, record_implementation

ROOT = Path(__file__).resolve().parents[1]


def selected_specifications(args: argparse.Namespace, packets: list) -> dict[str, str]:
    if args.gepa_result:
        result = read_json((ROOT / args.gepa_result).resolve())
        candidate = result["candidates"][args.candidate_idx]
        specification = candidate["conventions"]
        if args.candidate_sha256 and digest(specification) != args.candidate_sha256:
            raise ValueError("candidate hash does not match the selected specification")
        return {packet.name: specification for packet in packets}
    if args.memory:
        memory = restore_specifications(read_json((ROOT / args.memory).resolve()))
        memory.freeze()
        specifications = {}
        for packet in packets:
            asset = memory.generator_specification(packet.scope)
            if asset is None or (args.spec_id and asset.spec_id != args.spec_id):
                raise ValueError(f"no promoted specification authorized for {packet.name}")
            specifications[packet.name] = asset.text
        return specifications
    return {packet.name: "" for packet in packets}


def check_disjoint_from_gepa(gepa_result: Path | None, packets: list, allow_selection_replay: bool) -> str:
    if gepa_result is None:
        return "selection_replay" if allow_selection_replay else "frozen_replay"
    analysis_path = gepa_result.parent / "analysis.json"
    if not analysis_path.exists():
        raise ValueError("GEPA analysis is required to establish data provenance")
    analysis = read_json(analysis_path)
    selection_tasks = set(analysis["train_ids"]) | set(analysis["val_ids"])
    overlap = sorted(selection_tasks & {packet.name for packet in packets})
    if overlap and not allow_selection_replay:
        raise ValueError(f"batch overlaps GEPA selection tasks: {overlap}")
    return "selection_set_replay" if overlap else "subsequent_disjoint_replay"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--run-dir", required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--gepa-result")
    source.add_argument("--memory")
    parser.add_argument("--candidate-idx", type=int)
    parser.add_argument("--candidate-sha256")
    parser.add_argument("--spec-id")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--llm-timeout", type=float, default=600)
    parser.add_argument("--api-guard", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--allow-selection-replay", action="store_true")
    parser.add_argument("--compare-to")
    args = parser.parse_args()
    if args.gepa_result and args.candidate_idx is None:
        parser.error("--candidate-idx is required with --gepa-result")
    if args.candidate_idx is not None and not args.gepa_result:
        parser.error("--candidate-idx requires --gepa-result")
    if not args.gepa_result and args.candidate_sha256:
        parser.error("--candidate-sha256 requires --gepa-result")
    if args.spec_id and not args.memory:
        parser.error("--spec-id requires --memory")

    llm_mod.REQUEST_TIMEOUT_SEC = args.llm_timeout
    config = llm_mod.load_config()
    outdir = (ROOT / args.run_dir).resolve()
    if outdir.exists() and any(outdir.iterdir()) and not args.resume:
        raise ValueError("run directory is not empty; use --resume")
    outdir.mkdir(parents=True, exist_ok=True)
    record_implementation(outdir, args, config, args.resume)
    packets = load_tasks(ROOT / args.tasks)
    if not packets or len({packet.name for packet in packets}) != len(packets):
        raise ValueError("replay requires unique, non-empty task ids")
    specifications = selected_specifications(args, packets)
    provenance = check_disjoint_from_gepa((ROOT / args.gepa_result).resolve() if args.gepa_result else None,
                                          packets, args.allow_selection_replay)
    adapter = CleanroomAdapter(outdir, args.workers, args.seed, config, api_guard=args.api_guard)
    started = time.monotonic()
    records = [adapter._rollout(packet, {"conventions": specifications[packet.name]}) for packet in packets]
    summary = summarize_records(records, expected_tasks=len(packets))
    summary.update(arm="B0_empty_specification" if not args.gepa_result and not args.memory else
                   "B1_gepa_specification" if args.gepa_result else "B3_verified_memory",
                   provenance=provenance, evolution_performed=False, feedback_returned_to_generator=False,
                   candidate_idx=args.candidate_idx,
                   specification_sha256={name: digest(text) for name, text in specifications.items()},
                   wall_seconds=round(time.monotonic() - started, 3))
    write_json(outdir / "replay_result.json", summary)
    if args.compare_to:
        baseline_path = (ROOT / args.compare_to).resolve()
        manifest_path = baseline_path / "run.json" if baseline_path.is_dir() else baseline_path
        baseline_manifest = read_json(manifest_path)
        if "records" not in baseline_manifest:
            raise ValueError("comparison requires a replay run.json with per-task record paths")
        baseline = []
        for row in baseline_manifest["records"]:
            record_path = Path(row["record_path"])
            if not record_path.is_absolute():
                record_path = manifest_path.parent / record_path
            baseline.append(read_json(record_path))
        comparison = pair_win_safe(baseline, records)
        write_json(outdir / "paired_comparison.json", comparison)
        summary["paired_comparison"] = comparison

    manifest = read_json(outdir / "implementation.json")
    manifest["files"]["scripts/cleanroom_replay.py"] = hashlib.sha256(
        (ROOT / "scripts/cleanroom_replay.py").read_bytes()).hexdigest()
    manifest["files"]["ora_agent/cleanroom_analysis.py"] = hashlib.sha256(
        (ROOT / "ora_agent/cleanroom_analysis.py").read_bytes()).hexdigest()
    manifest["generation"].update(
        model_max_tokens=int(os.environ.get("ORA_CLEANROOM_MODEL_TOKENS", "4096")),
        model_max_words=int(os.environ.get("ORA_CLEANROOM_MODEL_WORDS", "1800")),
        temperature=0.6, protocol="two_phase_model_then_solver_v1")
    source_path = (ROOT / (args.gepa_result or args.memory)).resolve() if args.gepa_result or args.memory else None
    manifest["evaluation"] = {"provenance": provenance, "memory_frozen": bool(args.memory),
                              "task_ids": [packet.name for packet in packets],
                              "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest()
                              if source_path else None,
                              "reference_values_used_for_generation_or_reflection": False}
    manifest["records"] = [{"task": record["task"],
                            "record_path": str(Path(record["workspace"]).parent / "record.json")}
                           for record in records]
    write_json(outdir / "run.json", manifest)
    write_json(outdir / "replay_result.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

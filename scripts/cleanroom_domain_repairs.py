#!/usr/bin/env python3
"""Apply one domain-scoped Witness batch to records from a shared B1 replay."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ora_agent import llm as llm_mod
from ora_agent.oragentbench import read_json, write_json
from scripts.cleanroom_experiment import digest, load_tasks
from scripts.cleanroom_suite import repair_batch

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite-dir", required=True)
    parser.add_argument("--baseline-arm", default="B1")
    parser.add_argument("--arm", required=True)
    parser.add_argument("--audit-tasks", required=True)
    parser.add_argument("--witness-tasks", required=True)
    parser.add_argument("--witness-source")
    parser.add_argument("--gepa-result", required=True)
    parser.add_argument("--candidate-idx", type=int, required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-attempts", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--llm-timeout", type=float, default=600)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    args.suite_dir = (ROOT / args.suite_dir).resolve()
    args.audit_tasks = (ROOT / args.audit_tasks).resolve()
    args.witness_tasks = (ROOT / args.witness_tasks).resolve()
    args.witness_source = (ROOT / args.witness_source).resolve() if args.witness_source else None
    args.gepa_result = (ROOT / args.gepa_result).resolve()
    llm_mod.REQUEST_TIMEOUT_SEC = args.llm_timeout

    result = read_json(args.gepa_result)
    text = result["candidates"][args.candidate_idx]["conventions"]
    if digest(text) != args.candidate_sha256:
        raise ValueError("candidate hash does not match the selected specification")
    audit_packets = load_tasks(args.audit_tasks)
    witness_packets = load_tasks(args.witness_tasks)
    if not witness_packets or len({packet.domain for packet in witness_packets}) != 1:
        raise ValueError("domain repair requires one Witness domain")
    domain = witness_packets[0].domain
    packets = [packet for packet in audit_packets if packet.domain == domain]
    if not packets:
        raise ValueError(f"no B1 tasks match Witness domain: {domain}")
    namespace = argparse.Namespace(
        out=args.suite_dir, witness_packets=witness_packets, dev_packets=[],
        witness_source=args.witness_source, seed=args.seed,
        max_attempts=args.max_attempts, resume=args.resume)
    repairs = repair_batch(namespace, args.arm, packets, args.gepa_result,
                           {"candidate_idx": args.candidate_idx,
                            "candidate_sha256": args.candidate_sha256},
                           baseline_arm=args.baseline_arm)
    files = ["scripts/cleanroom_domain_repairs.py", "scripts/cleanroom_suite.py",
             "ora_agent/cleanroom.py", "ora_agent/cleanroom_witness.py",
             "ora_agent/oragentbench.py", "ora_agent/api_guard.py"]
    manifest = {
        "domain": domain,
        "audit_tasks_sha256": hashlib.sha256(args.audit_tasks.read_bytes()).hexdigest(),
        "witness_tasks_sha256": hashlib.sha256(args.witness_tasks.read_bytes()).hexdigest(),
        "gepa_result_sha256": hashlib.sha256(args.gepa_result.read_bytes()).hexdigest(),
        "candidate_idx": args.candidate_idx,
        "candidate_sha256": args.candidate_sha256,
        "baseline_manifest_sha256": hashlib.sha256(
            (args.suite_dir / args.baseline_arm / "run.json").read_bytes()).hexdigest(),
        "files": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
        "tasks": [packet.name for packet in packets],
        "repairs": [str(path) for path in repairs],
    }
    write_json(args.suite_dir / args.arm / "domain_repair_result.json", manifest)
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()

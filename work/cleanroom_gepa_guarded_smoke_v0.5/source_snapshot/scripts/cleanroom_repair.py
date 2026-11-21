#!/usr/bin/env python3
"""Initialize clean-room Witness assets and run one bounded residual repair."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ora_agent import llm as llm_mod
from ora_agent.cleanroom import EvidenceMemory
from ora_agent.cleanroom_witness import initialize_witness, repair_once
from scripts.cleanroom_experiment import digest, load_tasks
from ora_agent.oragentbench import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("witness", "repair"), required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--record")
    parser.add_argument("--spec-source")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--llm-timeout", type=float, default=180)
    parser.add_argument("--witness-source")
    parser.add_argument("--api-guard", action="store_true")
    args = parser.parse_args()
    if args.mode == "repair" and not args.record:
        parser.error("--record is required in repair mode")
    llm_mod.REQUEST_TIMEOUT_SEC = args.llm_timeout
    outdir = (ROOT / args.run_dir).resolve()
    if outdir.exists() and any(outdir.iterdir()):
        raise ValueError("repair run directory must be new")
    packets = load_tasks(ROOT / args.tasks)
    dev_packets = [packet for packet in packets if packet.split in {"dev", "audit"}]
    memory = EvidenceMemory()
    oracle_source = (ROOT / args.witness_source).resolve() if args.witness_source else None
    initialization = initialize_witness(memory, dev_packets, outdir / "witness", oracle_source)
    write_json(outdir / "memory.json", memory.public_state())
    if args.mode == "witness":
        print(json.dumps(initialization, ensure_ascii=False, indent=1))
        return

    record_path = (ROOT / args.record).resolve()
    record = read_json(record_path)
    if "record" in record and "task" not in record:
        record = record["record"]
    packet = next(packet for packet in packets if packet.name == record["task"])
    specification = ""
    if args.spec_source:
        source = read_json((ROOT / args.spec_source).resolve())
        specification = next(candidate["conventions"] for candidate in source["candidates"]
                             if digest(candidate["conventions"]) == record["candidate_sha256"])
    result = repair_once(memory, packet, record, specification, llm_mod.load_config(),
                         outdir, run_seed=args.seed, api_guard=args.api_guard)
    summary = {key: value for key, value in result.items() if key not in {"record", "dag"}}
    if "record" in result:
        summary["metrics"] = {key: result["record"].get(key) for key in
                              ("feasible", "quality", "true_correct", "objective")}
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

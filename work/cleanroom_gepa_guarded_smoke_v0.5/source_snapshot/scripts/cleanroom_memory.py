#!/usr/bin/env python3
"""Audit and optionally promote a GEPA specification into clean-room memory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ora_agent import llm as llm_mod
from ora_agent.cleanroom import EvidenceMemory, SpecificationAsset
from ora_agent.cleanroom_spec_audit import audit_specification
from scripts.cleanroom_experiment import load_tasks
from ora_agent.oragentbench import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--gepa-result", required=True)
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--llm-timeout", type=float, default=180)
    args = parser.parse_args()
    llm_mod.REQUEST_TIMEOUT_SEC = args.llm_timeout
    outdir = (ROOT / args.run_dir).resolve()
    if outdir.exists() and any(outdir.iterdir()):
        raise ValueError("memory promotion run directory must be new")
    result = read_json((ROOT / args.gepa_result).resolve())
    analysis = read_json((ROOT / args.analysis).resolve())
    packets = load_tasks(ROOT / args.tasks)
    dev_packets = [packet for packet in packets if packet.split == "dev"]
    curves = analysis["curves"]
    best = max(curves, key=lambda row: row["official_proxy_mean"])
    seed = curves[0]
    independent_replay = (
        best["candidate_idx"] > 0 and best["n"] == len(analysis["val_ids"])
        and best["generation_errors"] == 0
        and best["true_correct"] >= seed["true_correct"]
        and best["phantom_proxy"] <= seed["phantom_proxy"])

    memory = EvidenceMemory()
    for index, candidate in enumerate(result["candidates"]):
        parents = result["parents"][index]
        parent_id = f"spec_{parents[0]}" if parents and parents[0] is not None else None
        memory.register_specification(SpecificationAsset(
            f"spec_{index}", candidate["conventions"], {"dataset": "oragentbench"},
            parent_id=parent_id, source_refs=["dev_public_problem_statements"]))
    audit = {"changed_features_covered": False, "scope_confirmed": False,
             "coverage_note": "Independent replay did not justify an audit call."}
    if independent_replay:
        audit = audit_specification(dev_packets, result["candidates"][0]["conventions"],
                                    result["candidates"][best["candidate_idx"]]["conventions"],
                                    llm_mod.load_config(), outdir)
    memory.promote_specification(f"spec_{best['candidate_idx']}", {
        "independent_replay": independent_replay,
        "changed_features_covered": audit["changed_features_covered"],
        "scope_confirmed": audit["scope_confirmed"],
        "audit_scope": "dev_public_sources_and_transfer_official_replay"})
    write_json(outdir / "memory_promoted.json", memory.public_state(include_spec_text=True))
    summary = {"best_candidate_idx": best["candidate_idx"],
               "independent_replay": independent_replay,
               "specification_status": memory.specifications[f"spec_{best['candidate_idx']}"].status,
               "audit": audit}
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

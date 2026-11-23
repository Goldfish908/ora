#!/usr/bin/env python3
"""Audit and optionally promote a GEPA specification using disjoint replay evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ora_agent import llm as llm_mod
from ora_agent.cleanroom import EvidenceMemory, SpecificationAsset
from ora_agent.cleanroom_analysis import pair_win_safe, summarize_records
from ora_agent.cleanroom_spec_audit import audit_specification
from scripts.cleanroom_experiment import digest, load_tasks
from ora_agent.oragentbench import probe_pyscipopt_api, read_json, write_json

ROOT = Path(__file__).resolve().parents[1]


def _manifest(path: Path) -> tuple[Path, dict]:
    path = (ROOT / path).resolve()
    manifest_path = path / "run.json" if path.is_dir() else path
    return manifest_path, read_json(manifest_path)


def _records(manifest_path: Path, manifest: dict) -> list[dict]:
    records = []
    for item in manifest["records"]:
        path = Path(item["record_path"])
        if not path.is_absolute():
            path = manifest_path.parent / path
        records.append(read_json(path))
    return records


def replay_evidence(path: Path, specification: str, source_path: Path | None,
                    expected_provenance: str) -> dict:
    manifest_path, manifest = _manifest(path)
    evaluation = manifest.get("evaluation") or {}
    if evaluation.get("provenance") != expected_provenance:
        raise ValueError(f"invalid replay provenance: {evaluation.get('provenance')}")
    expected_source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest() if source_path else None
    if evaluation.get("source_sha256") != expected_source_hash:
        raise ValueError("replay source does not match the candidate artifact")
    records = _records(manifest_path, manifest)
    task_ids = evaluation.get("task_ids") or []
    if not records or sorted(record["task"] for record in records) != sorted(task_ids):
        raise ValueError("replay task coverage does not match its frozen manifest")
    candidate_hash = digest(specification)
    if any(record["candidate_sha256"] != candidate_hash for record in records):
        raise ValueError("replay contains a different specification")
    summary = summarize_records(records, expected_tasks=len(task_ids))
    return {"manifest_path": str(manifest_path), "manifest": manifest,
            "records": records, "summary": summary}


GENERATOR_FILES = ("ora_agent/llm.py", "ora_agent/cleanroom.py", "ora_agent/oragentbench.py",
                   "ora_agent/api_guard.py", "scripts/cleanroom_experiment.py")


def select_candidate(gepa_path: Path, result: dict, analysis: dict) -> dict:
    curves = analysis["curves"]
    top_transfer = max(row["official_proxy_mean"] for row in curves)
    contenders = [row for row in curves if row["official_proxy_mean"] == top_transfer]
    dev_scores = {}
    if len(contenders) > 1:
        if not analysis.get("train_ids"):
            raise ValueError("dev task ids are required to break a transfer-score tie")
        for row in contenders:
            candidate = result["candidates"][row["candidate_idx"]]
            candidate_hash = digest(candidate["conventions"])
            records = [read_json(gepa_path.parent / "rollouts" / candidate_hash / task / "attempt_0/record.json")
                       for task in analysis["train_ids"]]
            dev_scores[row["candidate_idx"]] = sum(record["proxy_score"] for record in records) / len(records)
    else:
        dev_scores[contenders[0]["candidate_idx"]] = None
    best = max(contenders, key=lambda row: (dev_scores[row["candidate_idx"]] is not None,
                                            dev_scores[row["candidate_idx"]] or 0,
                                            -row["candidate_idx"]))
    return {**best, "dev_proxy_mean": dev_scores[best["candidate_idx"]],
            "selection_rule": "transfer_proxy_desc_dev_proxy_desc_candidate_idx_asc"}


def _matching_implementation(gepa_path: Path, candidate: dict, baseline: dict) -> bool:
    implementation_path = gepa_path.parent / "implementation.json"
    if not implementation_path.exists():
        raise ValueError("GEPA implementation manifest is required for memory promotion")
    source = read_json(implementation_path)
    for replay in (candidate, baseline):
        manifest = replay["manifest"]
        if manifest["model"] != source["model"] or manifest["generation"] != source["generation"]:
            return False
        if bool(manifest["arguments"].get("api_guard")) != bool(source["arguments"].get("api_guard")):
            return False
        if any(manifest["files"].get(name) != source["files"][name] for name in GENERATOR_FILES):
            return False
    if candidate["manifest"]["generation"] != baseline["manifest"]["generation"]:
        return False
    if candidate["manifest"]["arguments"].get("api_guard") != baseline["manifest"]["arguments"].get("api_guard"):
        return False
    return True


def independent_replay(gepa_path: Path, specification: str, candidate_idx: int,
                       replay_path: Path | None, baseline_path: Path | None) -> tuple[bool, dict]:
    if replay_path is None:
        return False, {"reason": "missing_disjoint_replay", "candidate_idx": candidate_idx}
    candidate = replay_evidence(replay_path, specification, gepa_path, "subsequent_disjoint_replay")
    baseline = replay_evidence(baseline_path, "", None, "frozen_replay")
    if candidate["summary"]["coverage"] != 1.0 or candidate["summary"]["unknown"]:
        return False, {"reason": "incomplete_or_unknown_replay", "candidate": candidate["summary"]}
    if set(candidate["manifest"]["evaluation"]["task_ids"]) != set(baseline["manifest"]["evaluation"]["task_ids"]):
        raise ValueError("independent candidate and baseline must have identical task ids")
    comparison = pair_win_safe(baseline["records"], candidate["records"])
    same_implementation = _matching_implementation(gepa_path, candidate, baseline)
    before, after = baseline["summary"], candidate["summary"]
    passed = (candidate_idx > 0 and same_implementation and comparison["win_safe"]
              and not comparison["gained_phantom"] and after["true_correct"] >= before["true_correct"]
              and after["phantom_proxy"] <= before["phantom_proxy"]
              and all(record.get("generation_error") is None for record in candidate["records"]))
    evidence = {"candidate_idx": candidate_idx, "implementation_matches": same_implementation,
                "paired_comparison": comparison, "empty_specification": before,
                "gepa_specification": after, "passed": passed,
                "candidate_manifest_path": str(candidate["manifest_path"]),
                "baseline_manifest_path": str(baseline["manifest_path"]),
                "task_ids": sorted(candidate["manifest"]["evaluation"]["task_ids"]),
                "selection_tasks_reused": False}
    return passed, evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--gepa-result", required=True)
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--llm-timeout", type=float, default=600)
    parser.add_argument("--independent-replay")
    parser.add_argument("--independent-baseline")
    args = parser.parse_args()
    if bool(args.independent_replay) != bool(args.independent_baseline):
        parser.error("--independent-replay and --independent-baseline must be supplied together")
    llm_mod.REQUEST_TIMEOUT_SEC = args.llm_timeout
    outdir = (ROOT / args.run_dir).resolve()
    if outdir.exists() and any(outdir.iterdir()):
        raise ValueError("memory promotion run directory must be new")
    gepa_path = (ROOT / args.gepa_result).resolve()
    result = read_json(gepa_path)
    analysis = read_json((ROOT / args.analysis).resolve())
    packets = load_tasks(ROOT / args.tasks)
    dev_packets = [packet for packet in packets if packet.split == "dev"]
    domains = {packet.domain for packet in dev_packets}
    if len(domains) != 1:
        raise ValueError("memory promotion requires one demonstrated development domain")
    best = select_candidate(gepa_path, result, analysis)
    candidate_idx = best["candidate_idx"]
    candidate_text = result["candidates"][candidate_idx]["conventions"]
    independent, evidence = independent_replay(
        gepa_path, candidate_text, candidate_idx,
        (ROOT / args.independent_replay).resolve() if args.independent_replay else None,
        (ROOT / args.independent_baseline).resolve() if args.independent_baseline else None)
    evidence["candidate_selection"] = best
    for side in ("candidate", "baseline"):
        manifest_path = evidence.get(f"{side}_manifest_path")
        if manifest_path:
            evidence[f"{side}_manifest_sha256"] = hashlib.sha256(
                Path(manifest_path).read_bytes()).hexdigest()
    evidence_path = outdir / "independent_replay_evidence.json"
    write_json(evidence_path, evidence)

    scope = {"dataset": "oragentbench", "domain": dev_packets[0].domain}
    memory = EvidenceMemory()
    for index, candidate in enumerate(result["candidates"]):
        parents = result["parents"][index]
        parent_id = f"spec_{parents[0]}" if parents and parents[0] is not None else None
        memory.register_specification(SpecificationAsset(
            f"spec_{index}", candidate["conventions"], scope,
            parent_id=parent_id, source_refs=["dev_public_problem_statements"]))
    audit = {"changed_features_covered": False, "scope_confirmed": False,
             "coverage_note": "Independent replay did not justify an audit call."}
    if independent:
        contract = probe_pyscipopt_api(outdir / "api_contract")["stdout"]
        audit = audit_specification(dev_packets, result["candidates"][0]["conventions"],
                                    candidate_text, llm_mod.load_config(), outdir,
                                    environment_contract=contract)
    memory.promote_specification(f"spec_{candidate_idx}", {
        "independent_replay": independent,
        "changed_features_covered": audit["changed_features_covered"],
        "scope_confirmed": audit["scope_confirmed"],
        "audit_scope": "disjoint_official_replay_and_public_sources_with_verified_api_probe"})
    memory.freeze()
    memory_path = outdir / "memory_promoted.json"
    write_json(memory_path, memory.public_state(include_spec_text=True))
    summary = {"best_candidate_idx": candidate_idx,
               "independent_replay": independent,
               "specification_status": memory.specifications[f"spec_{candidate_idx}"].status,
               "specification_scope": scope, "audit": audit,
               "memory_sha256": hashlib.sha256(memory_path.read_bytes()).hexdigest(),
               "independent_replay_evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
               "independent_replay_manifest_sha256": evidence.get("candidate_manifest_sha256"),
               "independent_baseline_manifest_sha256": evidence.get("baseline_manifest_sha256")}
    write_json(outdir / "promotion_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

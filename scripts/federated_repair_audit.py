#!/usr/bin/env python3
"""Reproduce federated neighborhood repairs and independently re-evaluate emitted decisions."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ora_agent.declarative_neighborhood import DecisionArtifact
from ora_agent.federated_neighborhood import FederatedNeighborhoodRepair
from ora_agent.federated_public_ir import (
    CLIENT_UNIQUE,
    GPU_BUDGET,
    PRIVACY_BUDGET,
    STREAM_CLIENTS,
    STREAM_ENCLAVES,
    STREAM_EXAMPLES,
    UPLOAD_BUDGET,
    decisions_to_artifact,
    load_public_files,
    load_public_problem,
    pair_key,
    solution_file_to_artifact,
)
from ora_agent.oragentbench import (
    TaskPacket,
    official_evaluate,
    official_metrics,
    prepare_workspace,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
CLEAN_PATH = ROOT / "tests/fixtures/federated_solution.csv"


def with_selection(clean: DecisionArtifact, selected: dict, public_files: dict) -> DecisionArtifact:
    return decisions_to_artifact({"selected": selected, "_mapping_violations": []}, public_files)


def duplicate_client(clean: DecisionArtifact, problem, public_files: dict) -> DecisionArtifact:
    selected = dict(clean.decisions["selected"])
    chosen = next(pair for pair in problem.pair_order if selected[pair_key(*pair)] == 1)
    alternate = next(pair for pair in problem.by_client[chosen[0]] if selected[pair_key(*pair)] == 0)
    selected[pair_key(*alternate)] = 1
    return with_selection(clean, selected, public_files)


def stream_minimums(clean: DecisionArtifact, problem, public_files: dict) -> DecisionArtifact:
    selected = dict(clean.decisions["selected"])
    for pair in problem.by_stream["home_energy"]:
        selected[pair_key(*pair)] = 0
    return with_selection(clean, selected, public_files)


def all_budgets(clean: DecisionArtifact, problem, public_files: dict) -> DecisionArtifact:
    selected = dict(clean.decisions["selected"])
    clients_used = {pair[0] for pair in problem.pair_order if selected[pair_key(*pair)]}
    counts = {
        stream_id: sum(selected[pair_key(*pair)] for pair in pairs)
        for stream_id, pairs in problem.by_stream.items()
    }
    config = problem.config

    def usage():
        chosen = [pair for pair in problem.pair_order if selected[pair_key(*pair)]]
        return (
            sum(float(problem.clients[pair[0]]["privacy_cost"]) for pair in chosen),
            sum(float(problem.scores[pair]["upload_mb"]) for pair in chosen),
            sum(float(problem.scores[pair]["gpu_minutes"]) for pair in chosen),
        )

    for pair in problem.pair_order:
        privacy, upload, gpu = usage()
        if (privacy > float(config["privacy_budget"])
                and upload > float(config["upload_budget_mb"])
                and gpu > float(config["gpu_minutes_budget"])):
            break
        if selected[pair_key(*pair)] or pair[0] in clients_used:
            continue
        if counts[pair[1]] >= int(problem.streams[pair[1]]["max_clients"]):
            continue
        selected[pair_key(*pair)] = 1
        clients_used.add(pair[0])
        counts[pair[1]] += 1
    return with_selection(clean, selected, public_files)


def evaluate(packet: TaskPacket, artifact: DecisionArtifact, out: Path) -> dict:
    workspace = out / "app"
    prepare_workspace(packet, workspace, {
        "model_md": "offline federated repair audit",
        "solve_py": "# decision-only audit; no solver is invoked\n",
        "solve_log_md": "offline federated repair audit",
    }, validate=False)
    (workspace / "submissions/solution.csv").write_bytes(artifact.raw_bytes)
    official = official_evaluate(packet, workspace, out / "official")
    return {"metrics": official_metrics(official), "official": official}


def run(out: Path, evaluate_official: bool) -> dict:
    public_files = load_public_files()
    problem = load_public_problem(public_files)
    clean = solution_file_to_artifact(CLEAN_PATH, public_files)
    packet = TaskPacket.load(
        ROOT / "ORAgentBench/harbor_tasks/federated_learning_cohort_selection",
        "logistics", "transfer",
    )
    scenarios = {
        "duplicate_client": duplicate_client(clean, problem, public_files),
        "stream_minimums": stream_minimums(clean, problem, public_files),
        "all_budgets": all_budgets(clean, problem, public_files),
    }
    expected = {
        "duplicate_client": {CLIENT_UNIQUE},
        "stream_minimums": {STREAM_CLIENTS, STREAM_EXAMPLES, STREAM_ENCLAVES},
        "all_budgets": {PRIVACY_BUDGET, UPLOAD_BUDGET, GPU_BUDGET},
    }
    repair = FederatedNeighborhoodRepair(public_files, time_limit_seconds=60.0, relative_gap=0.0005)
    rows = []
    for label, parent in scenarios.items():
        parent_report = repair.checker.check(parent.decisions)
        present = {row["requirement_id"] for row in parent_report["violations"]}
        if not expected[label].issubset(present):
            raise ValueError(f"scenario {label} is missing expected requirements: {sorted(present)}")
        raw = {}

        def solve(spec):
            outcome = repair.solve(spec)
            raw.update(outcome)
            return outcome

        result = repair.repair(parent, solver=solve)
        row = {
            "scenario": label,
            "accepted": result.accepted,
            "reason": result.reason,
            "parent_public_status": result.parent_report["business_status"],
            "selected_public_status": result.candidate_report["business_status"]
            if result.candidate_report else None,
            "parent_public_objective": result.parent_report["objective"],
            "selected_public_objective": result.candidate_report["objective"]
            if result.candidate_report else None,
            "parent_violations": len(result.parent_report["violations"]),
            "fixed_violations": len(result.fixed_violations),
            "introduced_violations": len(result.introduced_violations),
            "remaining_violations": len(result.remaining_violations),
            "released_variables": len(result.spec.released_variables) if result.spec else 0,
            "fixed_variables": len(result.spec.fixed_variables) if result.spec else 0,
            "scip_status": raw.get("solver_status"),
            "scip_nodes": raw.get("node_count"),
            "scip_seconds": raw.get("solve_seconds"),
            "selected_sha256": result.selected.sha256,
        }
        if evaluate_official:
            row["official_before"] = evaluate(packet, parent, out / label / "before")["metrics"]
            row["official_after"] = evaluate(packet, result.selected, out / label / "after")["metrics"]
        rows.append(row)
    clean_result = repair.repair(clean)
    clean_row = {
        "scenario": "clean_control",
        "accepted": clean_result.accepted,
        "reason": clean_result.reason,
        "selected_sha256": clean_result.selected.sha256,
        "unchanged": clean_result.selected.raw_bytes == clean.raw_bytes,
    }
    if evaluate_official:
        clean_row["official"] = evaluate(packet, clean_result.selected, out / "clean_control")["metrics"]
    payload = {
        "schema_version": "federated_repair_audit_v0.1",
        "llm_calls": 0,
        "official_feedback_used_for_candidate_selection": False,
        "clean_sha256": clean.sha256,
        "clean_selected_objective": repair.checker.check(clean.decisions)["objective"],
        "implementation_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "ora_agent/declarative_neighborhood.py",
                "ora_agent/federated_public_ir.py",
                "ora_agent/federated_neighborhood.py",
                "scripts/federated_repair_audit.py",
            )
        },
        "public_file_sha256": repair.checker.check(clean.decisions)["public_file_sha256"],
        "clean_control": clean_row,
        "scenarios": rows,
        "accepted_repairs": sum(row["accepted"] for row in rows),
        "introduced_violations": sum(row["introduced_violations"] for row in rows),
        "official_true_correct_after": sum(
            row.get("official_after", {}).get("true_correct") is True for row in rows
        ),
        "official_true_correct_before": sum(
            row.get("official_before", {}).get("true_correct") is True for row in rows
        ),
        "note": "Predeclared repair-only scenarios. Public checks are not official business truth; no global optimality or cross-benchmark claim.",
    }
    write_json(out / "audit.json", payload)
    lines = [
        "# Federated declarative repair audit",
        "",
        "Zero LLM calls. Official outcomes are used only for final independent scoring, not candidate selection.",
        "",
        "| Scenario | Public before → after | Official true before → after | Official feasible after | Official quality after | Objective before → after | SCIP seconds |",
        "|---|---|---|---|---:|---|---:|",
    ]
    for row in rows:
        before = row.get("official_before", {})
        after = row.get("official_after", {})
        lines.append(
            f"| {row['scenario']} | {row['parent_public_status']} → {row['selected_public_status']} | "
            f"{before.get('true_correct')} → {after.get('true_correct')} | {after.get('feasible')} | "
            f"{after.get('quality')} | {row['parent_public_objective']:.6f} → "
            f"{row['selected_public_objective']:.6f} | {row['scip_seconds']:.3f} |"
        )
    (out / "report.md").write_text("\n".join(lines) + "\n")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--skip-official", action="store_true")
    args = parser.parse_args()
    payload = run((ROOT / args.out).resolve(), not args.skip_official)
    print(json.dumps(payload, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

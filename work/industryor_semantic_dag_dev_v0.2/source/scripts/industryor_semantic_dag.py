#!/usr/bin/env python3
"""Controlled single-line versus same-parent evidence-DAG repair on fixed candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod
from ora_agent.acceptance import can_accept
from ora_agent.evidence_dag import DagBudget, Proposal
from ora_agent.semantic_dag import SemanticDAGExecutor as EvidenceDAGExecutor
from ora_agent.semantic_binding import propose_binding, reconcile_binding, semantic_contract, validate_binding
from scripts.industryor_next_stage import instrument_code, score_solution
from scripts.industryor_scoped_loop import (
    binding_for,
    domain_binding_for,
    indicator_binding_for,
    repair_model,
)
from scripts.m1_pilot import extract_code, run_code

SOURCE = ROOT / "work/industryor_full_qwen_v0.1"
BINDINGS = ROOT / "work/industryor_semantic_inner8_dev_v0.1"
DATA = ROOT / "data/industryor/IndustryOR.json"
PROTOCOL = ROOT / "docs/paper/industryor_semantic_inner_protocol_v0.1.md"
LOCAL_IDS = (9, 19, 20, 21)
ARMS = ("bind_only", "single_line", "branch_dag")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def independent_score(problem_id: int, solution: dict | None) -> dict:
    if not isinstance(solution, dict) or solution.get("solution_count", 0) < 1:
        return {"audit_status": "no_solution", "business_correct": False, "violations": []}
    return score_solution(problem_id, solution)


def audit_record(score: dict) -> dict:
    if score.get("audit_status") != "complete":
        unknown = score.get("blocking_reasons") or score.get("violations") or [score.get("audit_status")]
        return {"status": "unknown", "reason": score.get("audit_status"), "fired": False,
                "violations": [], "unknown_evidence": unknown, "rejected": []}
    violations = [{"rule": "independent_business", "detail": detail}
                  for detail in score.get("violations", [])]
    return {"status": "ok", "fired": bool(violations), "violations": violations,
            "unknown_evidence": [], "rejected": []}


def execute_candidate(problem_id: int, code: str, aliases: dict, directory: Path) -> tuple[dict, dict | None, dict]:
    directory.mkdir(parents=True, exist_ok=True)
    try:
        instrumented = instrument_code(code, aliases)
        record = run_code(instrumented, directory)
    except (ValueError, TypeError, SyntaxError, OSError) as exc:
        record = {"status": "error", "exec_status": "crash", "solver_status": None,
                  "error": f"{type(exc).__name__}: {exc}", "solution": None}
        (directory / "gen.py").write_text(code)
    solution_path = directory / "solution.json"
    solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
    score = independent_score(problem_id, solution)
    try:
        runtime_gate = validate_binding(problem_id, code, aliases, solution)
    except (ValueError, TypeError, SyntaxError) as exc:
        runtime_gate = {"status": "error", "accepted_for_execution": False,
                        "business_correct": False, "error": f"{type(exc).__name__}: {exc}"}
    record.update(code_sha256=digest(code), aliases_sha256=digest(json.dumps(aliases, sort_keys=True)),
                  binding_gate=runtime_gate)
    write_json(directory / "execution.json", record)
    write_json(directory / "score.json", score)
    return record, solution, score


def generation(messages: list[dict], path: Path, config) -> dict:
    if path.exists():
        record = json.loads(path.read_text())
        if record["messages"] != messages:
            raise ValueError("shared regeneration cache has different messages")
        record["new_llm_calls"] = 0
        record["reused"] = True
        return record
    try:
        response = llm_mod.chat(messages, max_tokens=32768, temperature=0.6,
                                extra={"reasoning_effort": "medium"}, config=config)
        if response.get("model") != config.model:
            raise ValueError(f"returned model differs from requested model: {response.get('model')}")
        record = {"messages": messages, "response": response, "new_llm_calls": 1, "reused": False}
    except Exception as exc:
        response = {"request_attempts": getattr(exc, "request_attempts", [])}
        record = {"messages": messages, "response": response, "new_llm_calls": 1, "reused": False,
                  "error": f"{type(exc).__name__}: {exc}"}
    write_json(path, record)
    return record


def repair_prompt(question: str, code: str, gate: dict, score: dict, problem_id: int) -> str:
    failed_checks = [{"rule": item.get("rule"), "observed": item.get("observed"), "expected": item.get("expected")}
                     for item in score.get("constraint_checks", []) if not item.get("passed")]
    evidence = {"pre_solve_status": gate["status"], "missing_semantic_names": gate.get("missing_semantic_names"),
                "domain_mismatches": gate.get("domain_mismatches"), "audit_status": score.get("audit_status"),
                "violations": score.get("violations"), "failed_business_constraints": failed_checks}
    return ("Repair a PySCIPOpt optimization model using independent semantic evidence.\n"
            "Do not use or guess a reference objective. Preserve existing solver variable names when their "
            "business role is unchanged. If a required role is absent, add the corresponding model variable "
            "and constraints instead of merely renaming output fields.\n\n"
            f"[QUESTION]\n{question}\n\n[PREVIOUS CODE]\n{code}\n\n"
            f"[REQUIRED BUSINESS VARIABLES]\n{json.dumps(semantic_contract(problem_id), ensure_ascii=False)}\n\n"
            f"[INDEPENDENT EVIDENCE]\n{json.dumps(evidence, ensure_ascii=False)}\n\n"
            "Return ONLY the COMPLETE executable Python script. Do not delete violated business requirements.")


def local_proposal(problem_id: int, question: str, code: str, gate: dict,
                   directory: Path, done: bool) -> Proposal | None:
    if problem_id not in LOCAL_IDS:
        return None
    try:
        patched = repair_model(code, binding_for(problem_id, question),
                               indicator_binding_for(problem_id, question),
                               domain_binding_for(problem_id, question), gate["repair_aliases"])
    except (ValueError, TypeError, SyntaxError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        return Proposal("local_patch", code, "pyscipopt_code",
                        lambda: ({"status": "error", "exec_status": "crash", "error": error}, None),
                        lambda solution: independent_score(problem_id, solution),
                        binding_audit=lambda solution: audit_record(independent_score(problem_id, solution)),
                        binding_sha256=digest(json.dumps(gate["aliases"], sort_keys=True)),
                        solver_runs=0, llm_calls=0, done=done)
    if patched == code:
        return None
    return Proposal("local_patch", patched, "pyscipopt_code",
                    lambda: execute_candidate(problem_id, patched, gate["aliases"], directory)[:2],
                    lambda solution: independent_score(problem_id, solution),
                    binding_audit=lambda solution: audit_record(independent_score(problem_id, solution)),
                    binding_sha256=digest(json.dumps(gate["aliases"], sort_keys=True)),
                    solver_runs=1, llm_calls=0, done=done)


def regenerated_proposal(problem_id: int, question: str, code: str, gate: dict, score: dict,
                         directory: Path, shared: Path, config, done: bool) -> tuple[Proposal, list[dict]]:
    messages = [{"role": "user", "content": repair_prompt(question, code, gate, score, problem_id)}]
    response_record = generation(messages, shared / f"{digest(json.dumps(messages, sort_keys=True))}.json", config)
    records = [response_record]
    response = response_record["response"]
    candidate = extract_code(response.get("content") or "") if not response_record.get("error") else ""
    duplicate = bool(candidate.strip()) and candidate.strip() == code.strip()
    if duplicate:
        candidate_gate = gate
    elif candidate.strip():
        candidate_gate = reconcile_binding(problem_id, candidate, gate["aliases"])
        if candidate_gate["status"] == "needs_binding_evidence":
            binding_record = propose_binding(problem_id, question, candidate, None,
                                             shared / "bindings" / f"{digest(candidate)}.json", config)
            records.append(binding_record)
            candidate_gate = binding_record["gate"]
    else:
        candidate_gate = {"status": "error", "aliases": {}, "repair_aliases": {},
                          "accepted_for_execution": False, "business_correct": False}
    if duplicate:
        candidate = code
    proposal = Proposal("regenerate", candidate, "pyscipopt_code",
                        (lambda: ({"status": "duplicate", "exec_status": "duplicate", "solution": None}, None))
                        if duplicate else
                        (lambda: execute_candidate(problem_id, candidate, candidate_gate["aliases"], directory)[:2]),
                        lambda solution: independent_score(problem_id, solution),
                        binding_audit=lambda solution: audit_record(independent_score(problem_id, solution)),
                        binding_sha256=digest(json.dumps(candidate_gate["aliases"], sort_keys=True)),
                        solver_runs=0 if duplicate or not candidate.strip() else 1,
                        llm_calls=len(records), done=done)
    return proposal, records


def choose_node(executor: EvidenceDAGExecutor, root_id: str):
    accepted = executor.dag.accepted()
    if not accepted:
        return executor.nodes[root_id], "no_accepted_preserve_root"
    return min(accepted, key=lambda node: (node.llm_calls, node.solver_runs, node.depth, node.node_id)), \
        "accepted_min_llm_solver_depth"


def run_arm(problem_id: int, arm: str, question: str, code: str, gate: dict,
            root_payload: dict, case: Path, shared: Path, config) -> dict:
    record, solution, score = root_payload["record"], root_payload["solution"], root_payload["score"]
    executor = EvidenceDAGExecutor(DagBudget(max_nodes=6, max_depth=2, max_solver_runs=4, max_llm_calls=2),
                                   stop_on_accept=arm != "branch_dag")
    root = executor.root(code, "pyscipopt_code", {**record, "solution": solution}, score,
                         "validated" if can_accept(audit_record(score), "accepted") else "rejected",
                         digest(json.dumps(gate["aliases"], sort_keys=True)))
    root.solver_runs = 0 if root_payload["reused"] else 1
    generation_records = []
    if arm == "bind_only" or root in executor.dag.accepted():
        executor.dag.mark_done(root.node_id, "accepted" if root in executor.dag.accepted() else "bind_only")
    elif arm == "single_line":
        local = local_proposal(problem_id, question, code, gate, case / "local", done=False)
        parent = root
        if local is not None:
            added = executor.expand(root.node_id, [local])
            parent = added[0]
            if parent in executor.dag.accepted():
                parent = None
        if parent is not None and not executor.dag.accepted():
            parent_gate = gate if parent.node_id == "root" else dict(gate)
            parent_score = parent.business_audit
            parent_code = parent.snapshot
            proposal, records = regenerated_proposal(problem_id, question, parent_code, parent_gate, parent_score,
                                                     case / "regenerate", shared, config, done=True)
            generation_records.extend(records)
            executor.expand(parent.node_id, [proposal])
    else:
        local = local_proposal(problem_id, question, code, gate, case / "local", done=True)
        regenerated, records = regenerated_proposal(problem_id, question, code, gate, score,
                                                    case / "regenerate", shared, config, done=True)
        generation_records.extend(records)
        proposals = ([local] if local is not None else []) + [regenerated]
        executor.expand(root.node_id, proposals)
    selected, selection_reason = choose_node(executor, root.node_id)
    selected_solution = selected.execution.get("solution")
    selected_score = selected.business_audit
    selected_objective = (selected_solution or {}).get("objective")
    result = {
        "id": problem_id, "arm": arm, "initial_code": code, "final_code": selected.snapshot,
        "pre_solve": gate, "root_score": score, "final_score": selected_score,
        "root_objective": (solution or {}).get("objective"), "objective": selected_objective,
        "accepted": selected in executor.dag.accepted(), "selected_node_id": selected.node_id,
        "selection_reason": selection_reason, "accepted_node_ids": [node.node_id for node in executor.dag.accepted()],
        "business_recovered": bool(score.get("audit_status") == "complete" and not score.get("business_correct")
                                   and selected_score.get("business_correct")),
        "new_llm_calls": sum(record["new_llm_calls"] for record in generation_records),
        "logical_repair_llm_calls": len(generation_records),
        "rebinding_llm_calls": sum("problem_id" in record for record in generation_records),
        "new_rebinding_llm_calls": sum(record["new_llm_calls"] for record in generation_records
                                       if "problem_id" in record),
        "usage": [record["response"].get("usage") or {} for record in generation_records],
        "api_attempts": sum(len(record["response"].get("request_attempts") or [None])
                            for record in generation_records),
        "completion_tokens": sum((record["response"].get("usage") or {}).get("completion_tokens", 0) or 0
                                 for record in generation_records),
        "total_tokens": sum((record["response"].get("usage") or {}).get("total_tokens", 0) or 0
                            for record in generation_records),
        "llm_latency_s": sum((record["response"].get("request_wall_s")
                              or record["response"].get("latency_s") or 0) for record in generation_records),
        "new_llm_latency_s": sum((record["response"].get("request_wall_s")
                                  or record["response"].get("latency_s") or 0)
                                 for record in generation_records if record["new_llm_calls"]),
        "root_reused": root_payload["reused"], "dag": executor.dag.to_dict(),
        "binding_reused": True, "binding_new_llm_calls": 0,
        "reference_answer_used_for_selection": False,
    }
    write_json(case / "dag.json", result["dag"])
    return result


def run_one(row: dict, outdir: Path, config: dict, resume: bool) -> list[dict]:
    problem_id = row["id"]
    source_result = json.loads((SOURCE / f"prob_{problem_id:03d}/result.json").read_text())
    code = source_result["initial_code"]
    initial_solution_path = SOURCE / f"prob_{problem_id:03d}/round_0/solution.json"
    initial_solution = json.loads(initial_solution_path.read_text()) if initial_solution_path.exists() else None
    binding = json.loads((BINDINGS / f"prob_{problem_id:03d}/binding.json").read_text())
    gate = validate_binding(problem_id, code, binding["gate"]["aliases"], initial_solution)
    shared_root = outdir / "shared" / f"prob_{problem_id:03d}"
    root_result_path = shared_root / "root.json"
    if root_result_path.exists():
        root_payload = json.loads(root_result_path.read_text())
        expected_aliases = digest(json.dumps(gate["aliases"], sort_keys=True))
        if (root_payload["record"].get("code_sha256") != digest(code)
                or root_payload["record"].get("aliases_sha256") != expected_aliases):
            raise ValueError("shared root cache has a different code or binding hash")
        root_payload["reused"] = True
    else:
        record, solution, score = execute_candidate(problem_id, code, gate["aliases"], shared_root)
        root_payload = {"record": record, "solution": solution, "score": score, "reused": False}
        write_json(root_result_path, root_payload)
    results = []
    for arm in ARMS:
        case = outdir / f"prob_{problem_id:03d}" / arm
        case.mkdir(parents=True, exist_ok=True)
        result_path = case / "result.json"
        if resume and result_path.exists():
            previous = json.loads(result_path.read_text())
            if previous["run_config"] != config["public"]:
                raise ValueError("cached result has a different configuration")
            results.append(previous)
            continue
        result = run_arm(problem_id, arm, row["en_question"], code, gate, root_payload,
                         case, outdir / "shared_generations", config["llm_config"])
        result.update(run_config=config["public"], reference=float(row["en_answer"]),
                      initial_score=business_score_or_none(problem_id, initial_solution),
                      initial_objective=source_result.get("initial_objective"),
                      initial_objective_match_abs_0_1=source_result.get("initial_objective_match_abs_0_1", False),
                      root_objective_match_abs_0_1=result["root_objective"] is not None
                      and abs(result["root_objective"] - float(row["en_answer"])) <= 0.1,
                      binding_preserved_objective=result["root_objective"] is not None
                      and source_result.get("initial_objective") is not None
                      and abs(result["root_objective"] - source_result["initial_objective"]) <= 1e-7,
                      objective_match_abs_0_1=result["objective"] is not None
                      and abs(result["objective"] - float(row["en_answer"])) <= 0.1)
        result["status"] = "completed"
        write_json(result_path, result)
        results.append(result)
        root_payload["reused"] = True
    return results


def safe_one(row: dict, outdir: Path, config: dict, resume: bool) -> list[dict]:
    if resume:
        for arm in ARMS:
            path = outdir / f"prob_{row['id']:03d}" / arm / "result.json"
            if path.exists() and json.loads(path.read_text())["run_config"] != config["public"]:
                raise ValueError("cached result has a different configuration")
    try:
        return run_one(row, outdir, config, resume)
    except Exception as exc:
        results = []
        for arm in ARMS:
            case = outdir / f"prob_{row['id']:03d}" / arm
            root_path = outdir / "shared" / f"prob_{row['id']:03d}" / "root.json"
            root = json.loads(root_path.read_text()) if root_path.exists() else {}
            failure = {"audit_status": "runner_error", "business_correct": False}
            result = {"id": row["id"], "arm": arm, "run_config": config["public"],
                      "status": "runner_error", "error": f"{type(exc).__name__}: {exc}",
                      "reference": float(row["en_answer"]), "initial_score": None,
                      "pre_solve": {}, "root_score": root.get("score", failure), "final_score": failure,
                      "root_objective": None, "objective": None, "objective_match_abs_0_1": False,
                      "accepted": False, "business_recovered": False, "selected_node_id": None,
                      "selection_reason": "runner_error", "accepted_node_ids": [],
                      "new_llm_calls": 0, "logical_repair_llm_calls": 0, "usage": [], "llm_latency_s": 0,
                      "root_reused": bool(root), "binding_reused": True, "binding_new_llm_calls": 0,
                      "reference_answer_used_for_selection": False,
                      "dag": {"nodes": [], "events": [], "total_solver_runs": 0, "total_llm_calls": 0}}
            write_json(case / "error.json", result)
            results.append(result)
        return results


def business_score_or_none(problem_id: int, solution: dict | None) -> dict | None:
    if not isinstance(solution, dict) or solution.get("solution_count", 0) < 1:
        return None
    return score_solution(problem_id, solution)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", type=int, nargs="+", default=[4, 8, 9, 19, 20, 21, 25, 48])
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--out", default="work/industryor_semantic_dag_dev_v0.1")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--replay-generations-from")
    args = parser.parse_args()
    rows = [row for row in json.loads(DATA.read_text()) if row["id"] in set(args.ids)]
    if len(rows) != len(set(args.ids)):
        raise ValueError("not all requested IDs are registered")
    outdir = ROOT / args.out
    if outdir.exists() and any(outdir.iterdir()) and not args.resume:
        raise ValueError("nonempty output directory; use --resume or a new directory")
    outdir.mkdir(parents=True, exist_ok=True)
    replay_metadata = None
    if args.replay_generations_from:
        replay_source = (ROOT / args.replay_generations_from).resolve()
        replay_metadata = {"source": str(replay_source.relative_to(ROOT)), "files": {}}
        for path in sorted(replay_source.glob("*.json")):
            record = json.loads(path.read_text())
            destination = outdir / "shared_generations" / path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and destination.read_bytes() != path.read_bytes():
                raise ValueError("regeneration replay cache differs")
            destination.write_bytes(path.read_bytes())
            replay_metadata["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if not replay_metadata["files"]:
            raise ValueError("regeneration replay source is empty")
    llm_config = llm_mod.load_config()
    public = {"ids": [row["id"] for row in rows], "arms": list(ARMS), "model": llm_config.model,
              "base_url": llm_config.base_url, "temperature": 0.6, "reasoning_effort": "medium",
              "max_tokens": 32768, "max_regenerations_per_arm": 1, "max_llm_calls_per_arm": 2,
              "max_depth": 2, "max_solver_runs": 4,
              "branch_stop_on_accept": False, "local_repair_ids": list(LOCAL_IDS),
              "exposure": "development_replay_not_heldout", "binding_reused_for_all_arms": True,
              "source_analysis_sha256": hashlib.sha256((SOURCE / "analysis.json").read_bytes()).hexdigest(),
              "binding_analysis_sha256": hashlib.sha256((BINDINGS / "analysis.json").read_bytes()).hexdigest(),
              "business_manifest_sha256": hashlib.sha256(
                  (ROOT / "assets/industryor_next_stage/manifest.json").read_bytes()).hexdigest(),
              "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
              "implementation_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                        for name in ("scripts/industryor_semantic_dag.py",
                                                     "ora_agent/semantic_binding.py", "ora_agent/evidence_dag.py",
                                                     "ora_agent/semantic_dag.py",
                                                     "scripts/industryor_scoped_loop.py", "scripts/industryor_next_stage.py",
                                                     "scripts/m1_pilot.py", "ora_agent/llm.py", "ora_agent/acceptance.py")}}
    if replay_metadata is not None:
        public["regeneration_replay"] = replay_metadata
    config = {"llm_config": llm_config, "public": public}
    write_json(outdir / "run_config.json", public)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        nested = list(pool.map(lambda row: safe_one(row, outdir, config, args.resume), rows))
    results = [result for group in nested for result in group]
    summary = {"n_problems": len(rows), "scope": "development replay; no outer-loop evolution",
               "wall_seconds": round(time.monotonic() - started, 3), "arms": {}}
    for arm in ARMS:
        arm_rows = [row for row in results if row["arm"] == arm]
        summary["arms"][arm] = {
            "n": len(arm_rows), "runner_errors": sum(row["status"] == "runner_error" for row in arm_rows),
            "initial_objective_matches_abs_0_1": sum(row.get("initial_objective_match_abs_0_1", False)
                                                       for row in arm_rows),
            "root_objective_matches_abs_0_1": sum(row.get("root_objective_match_abs_0_1", False)
                                                    for row in arm_rows),
            "binding_preserved_objective": sum(row.get("binding_preserved_objective", False) for row in arm_rows),
            "root_business_correct": sum(row["root_score"].get("business_correct", False) for row in arm_rows),
            "final_business_correct": sum(row["final_score"].get("business_correct", False) for row in arm_rows),
            "business_recoveries": sum(row["business_recovered"] for row in arm_rows),
            "objective_matches_abs_0_1": sum(row["objective_match_abs_0_1"] for row in arm_rows),
            "accepted": sum(row["accepted"] for row in arm_rows),
            "new_llm_calls": sum(row["new_llm_calls"] for row in arm_rows),
            "logical_repair_llm_calls": sum(row["logical_repair_llm_calls"] for row in arm_rows),
            "rebinding_llm_calls": sum(row.get("rebinding_llm_calls", 0) for row in arm_rows),
            "new_rebinding_llm_calls": sum(row.get("new_rebinding_llm_calls", 0) for row in arm_rows),
            "shared_regeneration_reuses": sum(row["logical_repair_llm_calls"] - row["new_llm_calls"]
                                               for row in arm_rows),
            "api_attempts": sum(row.get("api_attempts", 0) for row in arm_rows),
            "completion_tokens": sum(row.get("completion_tokens", 0) for row in arm_rows),
            "total_tokens": sum(row.get("total_tokens", 0) for row in arm_rows),
            "llm_latency_s": round(sum(row.get("llm_latency_s", 0) for row in arm_rows), 3),
            "new_llm_latency_s": round(sum(row.get("new_llm_latency_s", 0) for row in arm_rows), 3),
            "candidate_evaluations": sum(len(row["dag"]["nodes"]) for row in arm_rows),
            "multi_branch_cases": sum(bool(row["dag"]["nodes"])
                                      and len(row["dag"]["nodes"][0]["children"]) > 1 for row in arm_rows),
            "solver_runs": sum(row["dag"]["total_solver_runs"] for row in arm_rows),
            "accepted_actions": sorted({node["action"] for row in arm_rows
                                        for node in row["dag"]["nodes"] if node["node_id"] in row["accepted_node_ids"]}),
        }
    write_json(outdir / "analysis.json", {"run_config": public, "summary": summary, "results": results})
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

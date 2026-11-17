#!/usr/bin/env python3
"""Structured iterative formulation, code generation and optional evidence-DAG repair."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod
from ora_agent.structured_models import (
    code_prompt,
    evaluation_prompt,
    model_prompt,
    parse_json,
    select_max_min,
    validate_evaluation,
    validate_model,
)
from scripts.industryor_full_pipeline import MAX_ROUNDS
from scripts.industryor_k3_pipeline import call_llm, costs, execute_candidate
from scripts.industryor_semantic_dag import (
    LOCAL_IDS,
    REGISTERED_AUDIT_IDS,
    audit_record,
    digest,
    choose_node,
    execute_candidate as execute_semantic_candidate,
    independent_score,
    local_proposal,
    regenerated_proposal,
)
from ora_agent.evidence_dag import DagBudget, Proposal
from ora_agent.repair_controller import ProgressController, repair_scip_sense
from ora_agent.semantic_dag import SemanticDAGExecutor
from ora_agent.trigger_memory import memory_for, registry_digest
from scripts.m1_pilot import extract_code
from scripts.m3_industryor import SCIP_CONTRACT, load_priors

DATA = ROOT / "data/industryor/IndustryOR.json"
PROTOCOL = ROOT / "docs/paper/industryor_full_chain_protocol_v0.1.md"
ARMS = ("structured", "structured_dag", "structured_dag_trigger", "structured_dag_full")
IMPLEMENTATION = ("scripts/industryor_structured_pipeline.py", "ora_agent/structured_models.py",
                  "scripts/industryor_k3_pipeline.py", "scripts/industryor_semantic_dag.py",
                  "ora_agent/semantic_dag.py", "ora_agent/semantic_binding.py", "ora_agent/trigger_memory.py",
                  "ora_agent/repair_controller.py", "scripts/industryor_full_pipeline.py",
                  "scripts/industryor_next_stage.py", "scripts/m1_pilot.py", "scripts/m3_industryor.py",
                  "ora_agent/llm.py")


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def generate_formations(question: str, case: Path, config) -> tuple[list[dict], list[dict]]:
    history = []
    candidates = []
    for index in range(3):
        model_record = call_llm([{"role": "user", "content": model_prompt(question, history)}],
                                case / f"model_{index}.json", config, 0.6, 32768)
        if model_record.get("error"):
            model = {}
            schema_errors = [model_record["error"]]
        else:
            try:
                model = parse_json(model_record["response"].get("content") or "")
                schema_errors = validate_model(model, question)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                model = {}
                schema_errors = [f"{type(exc).__name__}: {exc}"]
        evaluation_record = call_llm([{"role": "user", "content": evaluation_prompt(question, model)}],
                                     case / f"evaluation_{index}.json", config, 0.2, 16384)
        if evaluation_record.get("error"):
            evaluation = {"scores": {}, "weak_points": [evaluation_record["error"]]}
            schema_errors.append(evaluation_record["error"])
        else:
            try:
                evaluation = validate_evaluation(parse_json(evaluation_record["response"].get("content") or ""))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                evaluation = {"scores": {}, "weak_points": [f"{type(exc).__name__}: {exc}"]}
                schema_errors.append(f"{type(exc).__name__}: {exc}")
        if not evaluation["scores"]:
            schema_errors.append("no valid confidence scores")
        candidate = {"candidate_id": chr(ord("A") + index), "model": model,
                     "schema_errors": schema_errors, "evaluation": evaluation,
                     "model_record": model_record, "evaluation_record": evaluation_record}
        candidates.append(candidate)
        history.append({"model": model, "evaluation": evaluation})
    return candidates, history


def generate_code(problem_id: int, question: str, candidate: dict, case: Path, config) -> dict:
    prompt = load_priors() + "\n\n" + SCIP_CONTRACT + code_prompt(question, candidate["model"])
    record = call_llm([{"role": "user", "content": prompt}], case / f"code_{candidate['candidate_id']}.json",
                      config, 0.6, 32768)
    if record.get("error"):
        raise RuntimeError(record["error"])
    code = extract_code(record["response"].get("content") or "")
    (case / f"code_{candidate['candidate_id']}.py").write_text(code)
    execution, audit = execute_candidate(problem_id, code, case / f"execution_{candidate['candidate_id']}", config)
    objective = audit["solution"].get("objective") if isinstance(audit["solution"], dict) else execution.get("objective")
    accepted = bool(audit["score"] and audit["score"].get("business_correct")
                    and audit["gate"].get("status") == "ready")
    return {"code": code, "record": execution, "audit": audit, "objective": objective,
            "business_accepted": accepted, "code_record": record,
            "binding_record": audit.get("binding_record")}


def needs_repair(problem_id: int, result: dict) -> bool:
    if result["business_accepted"]:
        return False
    if problem_id in REGISTERED_AUDIT_IDS:
        return True
    record = result["record"]
    return bool(record.get("exec_status") != "ok" or record.get("solver_status") in {"infeasible", "unbounded"}
                or result["objective"] is None or record.get("export_error"))


def node_objective(node) -> float | None:
    solution = node.execution.get("solution")
    value = solution.get("objective") if isinstance(solution, dict) else node.execution.get("objective")
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def execution_complete(node) -> bool:
    solution = node.execution.get("solution")
    return bool(node.execution.get("exec_status") == "ok"
                and node.execution.get("solver_status") == "optimal"
                and isinstance(solution, dict) and solution.get("solution_count", 0) >= 1
                and (solution.get("export") or {}).get("complete") is True
                and node_objective(node) is not None)


def choose_integrated_node(executor: SemanticDAGExecutor, root_id: str, problem_id: int):
    selected, reason = choose_node(executor, root_id)
    if executor.dag.accepted() or problem_id in REGISTERED_AUDIT_IDS:
        return selected, reason
    root = executor.nodes[root_id]
    if execution_complete(root):
        return root, reason
    recovered = [node for node in executor.nodes.values() if execution_complete(node)]
    if not recovered:
        return root, reason
    selected = min(recovered, key=lambda node: (node.llm_calls, node.solver_runs, node.depth, node.node_id))
    return selected, "execution_recovered_business_unverified"


def run_dag(problem_id: int, question: str, result: dict, case: Path, shared: Path,
            config, memory_text: str | None = None) -> dict:
    record = result["record"]
    audit = result["audit"]
    score = audit["score"] or independent_score(problem_id, audit["solution"])
    executor = SemanticDAGExecutor(DagBudget(max_nodes=6, max_depth=MAX_ROUNDS - 1, max_solver_runs=4,
                                             max_llm_calls=2 * (MAX_ROUNDS - 1)),
                                   stop_on_accept=False)
    root = executor.root(result["code"], "pyscipopt_code",
                         {**record, "solution": audit["solution"], "binding_gate": audit["gate"]}, score,
                         "validated" if result["business_accepted"] else "rejected",
                         digest(json.dumps(audit["gate"]["aliases"], sort_keys=True)))
    root.solver_runs = 0
    repair_records = []
    controller = ProgressController()
    controller_trace = []
    current = root
    while True:
        if current in executor.dag.accepted():
            if not current.done:
                executor.dag.mark_done(current.node_id, "accepted")
            break
        solution = current.execution.get("solution")
        current_score = current.business_audit if solution is not None else independent_score(problem_id, None)
        probe = {"business_accepted": False, "record": current.execution,
                 "objective": node_objective(current)}
        if not needs_repair(problem_id, probe):
            executor.dag.mark_done(current.node_id, "business_unverified")
            break
        remaining = MAX_ROUNDS - 1 - current.depth
        if remaining <= 0:
            executor.dag.mark_done(current.node_id, "budget_exhausted")
            break
        current_audit = audit_record(current_score)
        decision = controller.decide(current.snapshot, current.execution, current_audit, remaining)
        trace_entry = {"node_id": current.node_id, "depth": current.depth,
                       "decision": decision.__dict__}
        controller_trace.append(trace_entry)
        if decision.action == "stop":
            executor.dag.mark_done(current.node_id, decision.reason)
            break
        action = decision.action
        gate = current.execution.get("binding_gate") or audit["gate"]
        proposal = None
        records = []
        directory = case / f"depth_{current.depth + 1}"
        if action == "local_patch" and problem_id in LOCAL_IDS:
            proposal = local_proposal(problem_id, question, current.snapshot, gate,
                                      directory / "local", done=False)
            if proposal is None:
                action = "regenerate"
        elif action == "specialized_api_repair":
            try:
                patched = repair_scip_sense(current.snapshot, decision.failure_signature.rsplit(":", 1)[-1])
                proposal = Proposal(
                    "specialized_api_repair", patched, "pyscipopt_code",
                    lambda: execute_semantic_candidate(problem_id, patched, gate["aliases"],
                                                       directory / "specialized")[:2],
                    lambda value: independent_score(problem_id, value),
                    binding_audit=lambda value: audit_record(independent_score(problem_id, value)),
                    binding_sha256=digest(json.dumps(gate["aliases"], sort_keys=True)),
                    solver_runs=1, llm_calls=0, done=False)
            except (ValueError, TypeError, SyntaxError) as exc:
                trace_entry["specialized_patch_error"] = f"{type(exc).__name__}: {exc}"
                action = "regenerate"
        if proposal is None:
            action = "regenerate"
            proposal, records = regenerated_proposal(
                problem_id, question, current.snapshot, gate, current_score,
                directory / "regenerate", shared, config, False,
                record=current.execution, memory_text=memory_text)
        repair_records.extend(records)
        effective_decision = replace(decision, action=action)
        trace_entry["effective_action"] = action
        added = executor.expand(current.node_id, [proposal])
        controller.record(effective_decision, proposal.candidate)
        if not current.done:
            executor.dag.mark_done(current.node_id, "expanded")
        if not added:
            break
        current = added[0]
        trace_entry["next_node_id"] = current.node_id
    selected, selection_reason = choose_integrated_node(executor, root.node_id, problem_id)
    solution = selected.execution.get("solution")
    return {"code": selected.snapshot, "record": selected.execution, "solution": solution,
            "score": selected.business_audit, "objective": node_objective(selected),
            "accepted": selected in executor.dag.accepted(), "selected_node_id": selected.node_id,
            "selection_reason": selection_reason, "dag": executor.dag.to_dict(),
            "repair_records": repair_records, "controller_trace": controller.trace(),
            "repair_decisions": controller_trace, "stop_reason": current.stop_reason,
            "candidate_rounds": max(node.depth for node in executor.nodes.values()) + 1}


def run_problem(row: dict, outdir: Path, config: dict, resume: bool) -> list[dict]:
    problem_id = row["id"]
    case = outdir / f"prob_{problem_id:03d}"
    case.mkdir(parents=True, exist_ok=True)
    if resume:
        cached = []
        for arm in ARMS:
            path = case / f"{arm}_result.json"
            if path.exists():
                previous = json.loads(path.read_text())
                if previous["run_config"] != config["public"]:
                    raise ValueError("cached result has a different configuration")
                cached.append(previous)
        if len(cached) == len(ARMS):
            return cached
    question = row["en_question"]
    candidates, history = generate_formations(question, case, config["llm_config"])
    selected_index, minima, selection_method = select_max_min(candidates)
    first = generate_code(problem_id, question, candidates[0], case, config["llm_config"])
    selected = first if selected_index == 0 else generate_code(problem_id, question, candidates[selected_index], case,
                                                               config["llm_config"])
    shared_records = [record for candidate in candidates
                      for record in (candidate["model_record"], candidate["evaluation_record"])]
    shared_records.extend([first["code_record"], first.get("binding_record")])
    if selected_index != 0:
        shared_records.extend([selected["code_record"], selected.get("binding_record")])
    shared_records = [record for record in shared_records if record]
    reference = float(row["en_answer"])
    results = []
    for arm in ARMS:
        if arm == "structured":
            final = selected
            repair_records = []
            dag = None
            selection_reason = selection_method
            memory = {"text": "", "asset_ids": [], "memory_sha256": None}
        else:
            mode = {"structured_dag": None, "structured_dag_trigger": "trigger",
                    "structured_dag_full": "full"}[arm]
            memory = memory_for(problem_id, selected["audit"]["gate"], selected["audit"]["score"] or {},
                                mode) if mode else {"text": "", "asset_ids": [], "memory_sha256": None}
            final = run_dag(problem_id, question, selected, case / arm,
                            outdir / "shared_generations", config["llm_config"], memory["text"] or None)
            repair_records = final.pop("repair_records")
            dag = final.pop("dag")
            selection_reason = final["selection_reason"]
        objective = final["objective"]
        result = {"id": problem_id, "arm": arm, "run_config": config["public"],
                  "status": "completed", "selected_index": selected_index,
                  "selection_method": selection_reason, "min_confidence": minima,
                  "selected_node_id": final.get("selected_node_id"),
                  "stop_reason": final.get("stop_reason"),
                  "candidate_rounds": final.get("candidate_rounds", 1),
                  "controller_trace": final.get("controller_trace", []),
                  "repair_decisions": final.get("repair_decisions", []),
                  "memory": memory, "memory_applied": bool(memory["text"] and repair_records),
                  "first_objective": first["objective"],
                  "first_match": first["objective"] is not None and abs(first["objective"] - reference) <= 0.1,
                  "objective": objective, "reference": reference,
                  "match": objective is not None and abs(objective - reference) <= 0.1,
                  "first_business_correct": first["business_accepted"],
                  "business_correct": final.get("business_accepted", final.get("accepted", False)),
                  "business_unverified": problem_id not in REGISTERED_AUDIT_IDS,
                  "selected_code": final["code"], "final_record": final["record"],
                  "final_solution": final["audit"]["solution"] if arm == "structured" else final["solution"],
                  "final_score": final["audit"]["score"] if arm == "structured" else final["score"],
                  "candidates": [{key: value for key, value in candidate.items()
                                  if key not in {"model_record", "evaluation_record"}} for candidate in candidates],
                  "first_code": first["code"], "first_record": first["record"],
                  "dag": dag, "cost": costs(shared_records + repair_records),
                  "shared_cost": costs(shared_records), "repair_cost": costs(repair_records),
                  "public_answer_used_for_selection": False}
        write_json(case / f"{arm}_result.json", result)
        (case / f"{arm}_error.json").unlink(missing_ok=True)
        results.append(result)
    return results


def safe_problem(row: dict, outdir: Path, config: dict, resume: bool) -> list[dict]:
    try:
        return run_problem(row, outdir, config, resume)
    except Exception as exc:
        case = outdir / f"prob_{row['id']:03d}"
        paths = (list(case.glob("model_*.json")) + list(case.glob("evaluation_*.json"))
                 + list(case.glob("code_*.json")) + list(case.glob("execution_*/binding.json")))
        records = [json.loads(path.read_text()) for path in paths]
        shared_dir = outdir / "shared_generations"
        if shared_dir.exists():
            for path in shared_dir.rglob("*.json"):
                record = json.loads(path.read_text())
                if any(row["en_question"] in message.get("content", "")
                       for message in record.get("messages", [])):
                    records.append(record)
        results = []
        for arm in ARMS:
            result = {"id": row["id"], "arm": arm, "run_config": config["public"],
                      "status": "runner_error", "error": f"{type(exc).__name__}: {exc}",
                      "reference": float(row["en_answer"]), "match": False, "first_match": False,
                      "first_business_correct": False, "business_correct": False,
                      "business_unverified": row["id"] not in REGISTERED_AUDIT_IDS,
                      "public_answer_used_for_selection": False, "cost": costs(records),
                      "cost_accounting_complete": False, "cost_source": "saved_artifacts"}
            write_json(case / f"{arm}_error.json", result)
            results.append(result)
        return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", type=int, nargs="*")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--out", default="work/industryor_structured_dev_v0.2")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    rows = json.loads(DATA.read_text())
    if args.ids:
        rows = [row for row in rows if row["id"] in set(args.ids)]
    if not rows:
        raise ValueError("no problems selected")
    outdir = ROOT / args.out
    if outdir.exists() and any(outdir.iterdir()) and not args.resume:
        raise ValueError("nonempty output directory; use --resume or a new directory")
    outdir.mkdir(parents=True, exist_ok=True)
    llm_config = llm_mod.load_config()
    public = {"ids": [row["id"] for row in rows], "arms": list(ARMS), "model": llm_config.model,
              "base_url": llm_config.base_url, "exposure": "development_new_samples_not_heldout",
              "method": "COOPA-inspired structured iterative formulation; not an official COOPA run",
              "max_candidate_rounds": MAX_ROUNDS, "max_repair_generations": MAX_ROUNDS - 1,
              "repair_controller": "ProgressController",
              "execution_fallback": "unregistered_only_when_root_incomplete",
              "memory_mode": "static_read_only", "memory_registry_sha256": registry_digest(),
              "dataset_sha256": hashlib.sha256(DATA.read_bytes()).hexdigest(),
              "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
              "implementation_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                        for name in IMPLEMENTATION}}
    config = {"llm_config": llm_config, "public": public}
    write_json(outdir / "run_config.json", public)
    for name in (*IMPLEMENTATION, "docs/paper/industryor_full_chain_protocol_v0.1.md"):
        destination = outdir / "source" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        nested = list(pool.map(lambda row: safe_problem(row, outdir, config, args.resume), rows))
    results = [result for group in nested for result in group]
    summary = {"n_problems": len(rows), "wall_seconds": round(time.monotonic() - started, 3), "arms": {}}
    for arm in ARMS:
        arm_rows = [row for row in results if row["arm"] == arm]
        cost_keys = ("logical_llm_calls", "new_llm_calls", "api_attempts", "completion_tokens",
                     "total_tokens", "llm_latency_s", "new_llm_latency_s")
        summary["arms"][arm] = {
            "n": len(arm_rows), "runner_errors": sum(row["status"] == "runner_error" for row in arm_rows),
            "first_matches": sum(row["first_match"] for row in arm_rows),
            "selected_matches": sum(row["match"] for row in arm_rows),
            "first_business_correct": sum(row["first_business_correct"] for row in arm_rows),
            "business_correct": sum(row["business_correct"] for row in arm_rows),
            "business_unverified": sum(row["business_unverified"] for row in arm_rows),
            "cost": {key: sum(row["cost"][key] for row in arm_rows) for key in cost_keys}}
    write_json(outdir / "analysis.json", {"run_config": public, "summary": summary, "results": results})
    write_json(outdir / "manifest.json", {"run_config": public, "registered_n": len(rows),
                                          "accounted_n": len(results),
                                          "public_answer_used_for_selection": False,
                                          "model_files": len(list(outdir.glob("prob_*/model_*.json"))),
                                          "evaluation_files": len(list(outdir.glob("prob_*/evaluation_*.json"))),
                                          "code_files": len(list(outdir.glob("prob_*/code_*.json")))})
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

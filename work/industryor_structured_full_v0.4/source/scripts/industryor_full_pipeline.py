#!/usr/bin/env python3
"""Run all registered IndustryOR problems with auditable generation and repair."""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import math
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod
from ora_agent.acceptance import can_accept
from ora_agent.evidence_dag import CandidateNode, EvidenceDAG
from ora_agent.repair_controller import ProgressController, repair_scip_sense
from ora_agent.scoped_assets import compile_asset, load_asset
from ora_agent.scoped_ir import evaluate_spec
from scripts.industryor_next_stage import instrument_code, load_problem, score_solution
from scripts.industryor_scoped_loop import (
    DOMAIN_TEMPLATE,
    INDICATOR_TEMPLATE,
    TEMPLATE,
    binding_for,
    domain_binding_for,
    indicator_binding_for,
    repair_model,
    validation_cells,
)
from scripts.m1_pilot import extract_code, run_code
from scripts.m3_industryor import SCIP_CONTRACT, feedback_msg, load_priors
from scripts.scoped_ir_e2e import current_cell
from scripts.scoped_ir_gate import gate

DATA = ROOT / "data/industryor/IndustryOR.json"
REPAIR_IDS = (19, 20, 21)
AUDIT_IDS = (4, 8, 9, 19, 20, 21, 25, 48)
MAX_ROUNDS = 3
TOY_LOCAL_ALIASES = {
    "x1": "R", "x2": "C", "x3": "B", "x4": "D",
    "y1": "y", "y2": "z", "y3": "y3", "y4": "y4",
}
TOY_EXPORT_ALIASES = {"R": "x1", "C": "x2", "B": "x3", "D": "x4", "y": "y1", "z": "y2"}
IMPLEMENTATION_PATHS = (
    "scripts/industryor_full_pipeline.py", "scripts/industryor_scoped_loop.py",
    "scripts/industryor_next_stage.py", "scripts/m1_pilot.py", "scripts/m3_industryor.py",
    "scripts/scoped_ir_e2e.py", "scripts/scoped_ir_gate.py",
    "ora_agent/llm.py", "ora_agent/evidence_dag.py", "ora_agent/repair_controller.py",
    "ora_agent/acceptance.py", "ora_agent/scoped_ir.py", "ora_agent/scoped_assets.py",
)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def public_config(config: dict) -> dict:
    return {key: value for key, value in config.items() if key != "llm_config"}


def baseline_records() -> dict[int, dict[str, dict]]:
    result = {}
    for arm in ("z0", "z1", "z2"):
        records = {}
        for path in sorted((ROOT / "runs/industryor").glob(f"m3_{arm}_s[0-9].jsonl")):
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row["id"] not in records or row["round"] > records[row["id"]]["round"]:
                    records[row["id"]] = row
        for problem_id, row in records.items():
            result.setdefault(problem_id, {})[arm] = {
                key: row.get(key) for key in (
                    "objective", "exec_status", "solver_status", "round", "exec_s",
                    "llm_latency_s", "completion_tokens", "reasoning_tokens",
                )
            }
    return result


def baseline() -> dict:
    rows = json.loads(DATA.read_text())
    refs = {row["id"]: float(row["en_answer"]) for row in rows}
    per_problem = baseline_records()
    result = {}
    for arm in ("z0", "z1", "z2"):
        records = {problem_id: values[arm] for problem_id, values in per_problem.items() if arm in values}
        scored = [(problem_id, row) for problem_id, row in records.items() if row.get("objective") is not None]
        result[arm] = {
            "n": len(records),
            "objective_matches_abs_0_1": sum(abs(row["objective"] - refs[problem_id]) <= 0.1
                                             for problem_id, row in scored),
            "objective_matches_relative_1pct": sum(
                abs(row["objective"] - refs[problem_id]) / max(abs(refs[problem_id]), 1e-9) <= 0.01
                for problem_id, row in scored),
            "exec_ok": sum(row.get("exec_status") == "ok" for row in records.values()),
            "optimal": sum(row.get("solver_status") == "optimal" for row in records.values()),
            "llm_calls": sum(row["round"] for row in records.values()),
        }
    return result


def scoped_assets(problem_id: int) -> tuple[dict, dict, str]:
    if problem_id not in REPAIR_IDS:
        return {}, {}, "unvalidated"
    manifest = json.loads((ROOT / "assets/industryor_next_stage/manifest.json").read_text())
    question = next(row["question"] for row in manifest["problems"] if row["id"] == problem_id)
    objective = binding_for(problem_id, question)
    indicator = indicator_binding_for(problem_id, question)
    spec = compile_asset(load_asset(TEMPLATE), objective)
    spec["invariants"].extend(compile_asset(load_asset(INDICATOR_TEMPLATE), indicator)["invariants"])
    domain = domain_binding_for(problem_id, question)
    if domain:
        spec["invariants"].extend(compile_asset(load_asset(DOMAIN_TEMPLATE), domain)["invariants"])
    cells = validation_cells(problem_id, load_problem(problem_id).solution)
    result = gate(spec, question, cells, str(problem_id))
    return spec, {"objective": objective, "indicator": indicator, "domain": domain}, result["status"]


def business_audit(problem_id: int, solution: dict | None, spec: dict,
                   question: str) -> tuple[dict, dict | None]:
    if not isinstance(solution, dict) or solution.get("solution_count", 0) < 1:
        return {"status": "unknown", "reason": "no_solution", "fired": False,
                "violations": [], "unknown_evidence": [], "rejected": []}, None
    if problem_id not in AUDIT_IDS:
        return {"status": "unknown", "reason": "business_unverified", "fired": False,
                "violations": [], "unknown_evidence": [{"detail": "no registered business auditor"}],
                "rejected": []}, None
    score = score_solution(problem_id, solution)
    if score["audit_status"] == "blocked":
        return {"status": "unknown", "reason": "business_audit_blocked", "fired": False,
                "violations": [], "unknown_evidence": score["blocking_reasons"], "rejected": []}, score
    if score["audit_status"] != "complete":
        return {"status": "unknown", "reason": "no_solution", "fired": False,
                "violations": [], "unknown_evidence": score.get("violations", []), "rejected": []}, score
    violations = []
    for item in score["constraint_checks"]:
        if not item["passed"]:
            violations.append({"rule": item["rule"], "detail": item["expected"]})
    for name, item in score["variable_audit"].items():
        if not item["passed"]:
            violations.append({"rule": f"domain_{name}", "detail": item["domain"]})
    if not score["model_objective_consistent"]:
        violations.append({"rule": "business_objective", "delta": (score.get("business_objective") or 0)
                           - (solution.get("objective") or 0)})
    if score["optimality"] == "suboptimal":
        violations.append({"rule": "independent_optimality", "detail": score["optimality"]})
    record = {"status": "ok", "fired": bool(violations), "violations": violations,
              "unknown_evidence": [], "rejected": []}
    if spec:
        record = evaluate_spec(spec, question, [current_cell(solution)], str(problem_id))["records"][0]
    return record, score


def toy_aliases(code: str) -> tuple[dict, dict]:
    tree = ast.parse(code)
    declared = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "addVar"):
            declared.update(target.id for target in node.targets if isinstance(target, ast.Name))
    semantic = {f"x{i}" for i in range(1, 5)} | {"y1", "y2"}
    if semantic <= declared:
        return {"y3": "y3", "y4": "y4"}, {}
    required = {"R", "C", "B", "D", "y", "z"}
    if required <= declared and not (semantic & declared):
        return TOY_LOCAL_ALIASES, TOY_EXPORT_ALIASES
    return {}, {}


def generation(case_dir: Path, index: int, messages: list[dict], config: dict,
               initial_path: Path | None = None) -> tuple[dict, dict]:
    path = case_dir / f"generation_{index:02d}.json"
    if path.exists():
        record = json.loads(path.read_text())
        if record["messages"] != messages or record.get("error"):
            raise ValueError(f"cached generation is incompatible: {case_dir.name}/{index}")
        record["reused"] = True
        record["invoked_this_run"] = False
        return record["response"], record
    if index == 0 and initial_path and initial_path.exists():
        response = json.loads(initial_path.read_text())
        if response.get("prompt_sha256") != digest(messages[0]["content"]):
            raise ValueError(f"saved prompt differs for {case_dir.name}")
        record = {"messages": messages, "response": response, "invoked_this_run": False,
                  "reused": True, "recovered_legacy_cache": True,
                  "retry_accounting_complete": "request_attempts" in response}
        write_json(path, record)
        return response, record
    request = {"model": config["llm_config"].model, "temperature": 0.6,
               "reasoning_effort": "medium", "max_tokens": 32768}
    started = time.monotonic()
    try:
        response = llm_mod.chat(messages, max_tokens=32768, temperature=0.6,
                                extra={"reasoning_effort": "medium"}, config=config["llm_config"])
    except Exception as exc:
        record = {"messages": messages, "request": request, "invoked_this_run": True,
                  "reused": False, "error": f"{type(exc).__name__}: {exc}",
                  "request_attempts": getattr(exc, "request_attempts", []),
                  "wall_s": time.monotonic() - started}
        write_json(path, record)
        raise
    response["prompt_sha256"] = digest(messages[0]["content"])
    record = {"messages": messages, "request": request, "response": response,
              "invoked_this_run": True, "reused": False, "retry_accounting_complete": True}
    write_json(path, record)
    if index == 0 and initial_path:
        write_json(initial_path, response)
    if response.get("model") != config["llm_config"].model:
        raise ValueError(f"returned model differs from requested model: {response.get('model')}")
    return response, record


def repair_feedback(record: dict, audit: dict) -> str:
    parts = []
    execution_feedback = feedback_msg(record)
    if execution_feedback:
        parts.append(execution_feedback)
    if record.get("export_error"):
        parts.append("The deterministic solution exporter failed: " + record["export_error"])
    violations = audit.get("violations", [])
    if violations:
        parts.append("Business evidence violations (not target objectives):\n"
                     + json.dumps(violations[:8], ensure_ascii=False))
    if not parts:
        parts.append("The previous program did not provide a complete auditable solution. "
                     "Check the model and output contract; rewrite the COMPLETE script.")
    return "\n\n".join(parts) + "\nOutput ONLY executable Python code."


def cached_execution(sandbox: Path, code: str, instrumented: str) -> dict | None:
    path = sandbox / "execution.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    if record.get("code_sha256") != digest(code) or record.get("instrumented_sha256") != digest(instrumented):
        return None
    if record.get("solution_exists") and not (sandbox / "solution.json").exists():
        return None
    return record


def objective_of(record: dict, solution: dict | None):
    if isinstance(solution, dict) and isinstance(solution.get("objective"), (int, float)):
        value = solution["objective"]
        if math.isfinite(value):
            return float(value)
    value = record.get("objective")
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def failure_classification(row: dict) -> str:
    if row.get("status") == "runner_error":
        return "runner_error"
    score = row.get("final_score") or {}
    if score.get("audit_status") == "blocked":
        return "business_audit_blocked"
    if row.get("exec_status") in {"crash", "timeout"}:
        return row["exec_status"]
    if row.get("objective_match_abs_0_1"):
        if score.get("business_correct"):
            return "business_correct"
        if row.get("business_unverified"):
            return "objective_matched_business_unverified"
        if score.get("audit_status") == "complete":
            return "objective_matched_business_rejected"
        return "objective_matched_business_unknown"
    if row.get("objective") is None:
        return "no_objective"
    if score.get("audit_status") == "complete" and not score.get("business_correct"):
        return "business_semantics_rejected"
    if row.get("business_unverified"):
        return "objective_mismatch_or_suboptimal"
    return "objective_mismatch_business_unknown"


def run_problem(row: dict, outdir: Path, config: dict, resume: bool) -> dict:
    problem_id = row["id"]
    case_dir = outdir / f"prob_{problem_id:03d}"
    case_dir.mkdir(parents=True, exist_ok=True)
    result_path = case_dir / "result.json"
    if resume and result_path.exists():
        previous = json.loads(result_path.read_text())
        if previous.get("run_config") != public_config(config):
            raise ValueError(f"configuration changed for {problem_id}; use a new output directory")
        return previous
    question = row["en_question"]
    prompt = load_priors() + "\n\n" + SCIP_CONTRACT + question
    (case_dir / "prompt.txt").write_text(prompt)
    initial_path = case_dir / "initial_response.json"
    response, generation_record = generation(case_dir, 0, [{"role": "user", "content": prompt}],
                                             config, initial_path)
    generations = [generation_record]
    initial_code = extract_code(response.get("content") or "")
    (case_dir / "initial.py").write_text(initial_code)
    spec, bindings, checker = scoped_assets(problem_id)
    root_node = CandidateNode("root", digest(initial_code), None, "seed", None, "unvalidated",
                              {"status": "not_run"}, {"business_correct": False},
                              snapshot=initial_code, candidate_kind="pyscipopt_code")
    dag = EvidenceDAG()
    dag.add(root_node)
    controller = ProgressController()
    code = initial_code
    history = []
    accepted = None
    accepted_round = None
    stop_reason = None
    deterministic_transforms = 0
    failed_deterministic_transforms = 0
    action = "initial"
    initial_record = initial_solution = initial_score = None
    record = {}
    solution = score = None
    for round_idx in range(MAX_ROUNDS):
        aliases, export_aliases = toy_aliases(code) if problem_id == 20 else ({}, {})
        sandbox = (case_dir / f"round_{round_idx}").resolve()
        sandbox.mkdir(parents=True, exist_ok=True)
        try:
            instrumented = instrument_code(code, export_aliases)
            export_error = None
        except (ValueError, TypeError, SyntaxError) as exc:
            instrumented, export_error = code, f"{type(exc).__name__}: {exc}"
        record = cached_execution(sandbox, code, instrumented)
        reused_execution = record is not None
        solution_path = sandbox / "solution.json"
        if record is None:
            solution_path.unlink(missing_ok=True)
            record = run_code(instrumented, sandbox)
            record.update(code_sha256=digest(code), instrumented_sha256=digest(instrumented))
            record["solution_exists"] = solution_path.exists()
            write_json(sandbox / "execution.json", record)
        record = dict(record, export_error=export_error, export_aliases=export_aliases,
                      repair_aliases=aliases)
        solution = None
        if solution_path.exists():
            try:
                solution = json.loads(solution_path.read_text())
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                record["solution_parse_error"] = f"{type(exc).__name__}: {exc}"
        audit, score = business_audit(problem_id, solution, spec, question)
        acceptance_ok = can_accept(audit, checker) and bool(score and score.get("business_correct"))
        binding_status = "validated" if acceptance_ok else "rejected"
        if problem_id not in AUDIT_IDS:
            binding_status = "unvalidated"
        node = CandidateNode(f"r{round_idx}", digest(code), "root" if round_idx == 0 else f"r{round_idx - 1}",
                             action, None, binding_status, {**record, "solution": solution},
                             score or {"business_correct": False},
                             solver_runs=0 if reused_execution else 1,
                             llm_calls=0 if round_idx == 0 and generations[0]["reused"] else
                             (1 if round_idx == 0 else int(not generations[-1]["reused"])),
                             snapshot=code, candidate_kind="pyscipopt_code")
        dag.add(node)
        dag.events.append({"type": "candidate_evaluated", "node_id": node.node_id,
                           "parent_id": node.parent_id, "action": action,
                           "candidate_hash": node.candidate_hash})
        entry = {"round": round_idx, "action": action, "code": code,
                 "record": record, "audit": audit, "score": score,
                 "generation_artifact": f"generation_{round_idx:02d}.json",
                 "generation_reused": generations[-1]["reused"],
                 "execution_reused": reused_execution}
        history.append(entry)
        write_json(sandbox / "audit.json", audit)
        if score is not None:
            write_json(sandbox / "score.json", score)
        write_json(case_dir / "trace.json", history)
        write_json(case_dir / "dag.json", dag.to_dict())
        if initial_record is None:
            initial_record, initial_solution, initial_score = record, solution, score
            root_node.execution = {**record, "solution": solution}
            root_node.business_audit = score or {"business_correct": False}
            root_node.binding_status = binding_status
        if acceptance_ok:
            accepted = {"code": code, "solution": solution, "record": record,
                        "score": score, "node_id": node.node_id}
            accepted_round = round_idx
            stop_reason = "accepted"
            dag.mark_done(node.node_id, stop_reason)
            break
        if audit.get("reason") == "business_unverified":
            stop_reason = "business_unverified"
            dag.mark_done(node.node_id, stop_reason)
            break
        if audit.get("reason") == "business_audit_blocked":
            stop_reason = "business_audit_blocked"
            dag.mark_done(node.node_id, stop_reason)
            break
        if not spec and score is not None and score.get("audit_status") == "complete":
            stop_reason = "business_audit_complete_no_registered_repair"
            dag.mark_done(node.node_id, stop_reason)
            break
        if round_idx >= MAX_ROUNDS - 1:
            stop_reason = "budget_exhausted"
            dag.mark_done(node.node_id, stop_reason)
            break
        decision = controller.decide(code, record, audit, MAX_ROUNDS - 1 - round_idx, checker)
        entry["controller_decision"] = decision.__dict__
        if decision.action == "local_patch" and problem_id not in REPAIR_IDS:
            decision = replace(decision, action="regenerate", reason="no_registered_local_patch")
            entry["effective_decision"] = decision.__dict__
        if decision.action == "stop":
            stop_reason = decision.reason
            dag.mark_done(node.node_id, stop_reason)
            break
        previous_code = code
        new_action = decision.action
        if decision.action == "local_patch" and problem_id in REPAIR_IDS:
            try:
                code = repair_model(code, bindings["objective"], bindings["indicator"],
                                    bindings["domain"], aliases)
                deterministic_transforms += 1
            except (ValueError, TypeError, SyntaxError) as exc:
                failed_deterministic_transforms += 1
                entry["deterministic_patch_error"] = f"{type(exc).__name__}: {exc}"
                new_action = "regenerate"
        elif decision.action == "specialized_api_repair":
            try:
                code = repair_scip_sense(code, decision.failure_signature.rsplit(":", 1)[-1])
                deterministic_transforms += 1
            except (ValueError, TypeError, SyntaxError) as exc:
                failed_deterministic_transforms += 1
                entry["deterministic_patch_error"] = f"{type(exc).__name__}: {exc}"
                new_action = "regenerate"
        elif decision.action != "regenerate":
            stop_reason = decision.action + "_unavailable"
            dag.mark_done(node.node_id, stop_reason)
            break
        if new_action == "regenerate":
            messages = [{"role": "user", "content": prompt},
                        {"role": "assistant", "content": previous_code},
                        {"role": "user", "content": repair_feedback(record, audit)}]
            response, generation_record = generation(case_dir, round_idx + 1, messages, config)
            generations.append(generation_record)
            code = extract_code(response.get("content") or "")
        if new_action != decision.action:
            decision = replace(decision, action=new_action,
                               reason=decision.reason + "; deterministic_patch_failed" if
                               entry.get("deterministic_patch_error") else decision.reason)
            entry["effective_decision"] = decision.__dict__
        controller.record(decision, code)
        entry["next_action"] = new_action
        entry["before_sha256"] = digest(previous_code)
        entry["after_sha256"] = digest(code)
        if code == previous_code:
            stop_reason = "duplicate_candidate"
            entry["duplicate_candidate"] = True
            dag.events.append({"type": "duplicate_rejected", "node_id": node.node_id,
                               "candidate_hash": digest(code), "action": new_action})
            dag.mark_done(node.node_id, stop_reason)
            break
        action = new_action
        write_json(case_dir / "trace.json", history)
    if accepted is None and initial_score and initial_score.get("business_correct"):
        restored = dag.rollback(f"r{len(history) - 1}", "root")
        if restored != initial_code:
            raise ValueError("rollback snapshot differs from the initial code")
        code, solution, score = restored, copy.deepcopy(initial_solution), initial_score
        record = initial_record
        stop_reason = "baseline_fallback"
    final_code = accepted["code"] if accepted else code
    final_solution = accepted["solution"] if accepted else solution
    final_score = accepted["score"] if accepted else score
    final_record = accepted["record"] if accepted else record
    (case_dir / "final.py").write_text(final_code)
    if final_solution is not None:
        write_json(case_dir / "solution.json", final_solution)
    objective = objective_of(final_record, final_solution)
    initial_objective = objective_of(initial_record, initial_solution)
    reference = float(row["en_answer"])
    usages = [item["response"].get("usage") or {} for item in generations]
    latencies = [(item["response"].get("request_wall_s")
                  or item["response"].get("latency_s") or 0) for item in generations]
    z2 = baseline_records().get(problem_id, {}).get("z2", {})
    result = {
        "id": problem_id, "run_config": public_config(config),
        "status": "completed", "prompt_sha256": digest(prompt),
        "initial_code": initial_code, "final_code": final_code,
        "initial_score": initial_score, "final_score": final_score,
        "initial_objective": initial_objective,
        "initial_objective_match_abs_0_1": initial_objective is not None and abs(initial_objective - reference) <= 0.1,
        "objective": objective, "printed_objective": final_record.get("objective"),
        "reference": reference,
        "objective_match_abs_0_1": objective is not None and abs(objective - reference) <= 0.1,
        "objective_error": abs(objective - reference) if objective is not None else None,
        "objective_below_reference": objective is not None and objective < reference - 0.1,
        "objective_above_reference": objective is not None and objective > reference + 0.1,
        "exec_status": final_record.get("exec_status"), "solver_status": final_record.get("solver_status"),
        "accepted": accepted is not None, "accepted_round": accepted_round,
        "accepted_but_business_incorrect": accepted is not None and not (final_score or {}).get("business_correct", False),
        "harmed_win": bool(initial_score and initial_score.get("business_correct")
                           and not (final_score or {}).get("business_correct", False)),
        "business_unverified": problem_id not in AUDIT_IDS,
        "stop_reason": stop_reason, "history": history,
        "controller_trace": controller.trace(),
        "deterministic_transforms": deterministic_transforms,
        "failed_deterministic_transforms": failed_deterministic_transforms,
        "generation_artifacts": [{"path": f"generation_{index:02d}.json", "reused": item["reused"]}
                                 for index, item in enumerate(generations)],
        "llm_calls": len(generations), "new_llm_calls": sum(item["invoked_this_run"] for item in generations),
        "api_attempts": sum(len(item["response"].get("request_attempts") or [None]) for item in generations),
        "retry_accounting_complete": all("request_attempts" in item["response"] for item in generations),
        "usage": usages, "prompt_tokens": sum(row.get("prompt_tokens", 0) or 0 for row in usages),
        "completion_tokens": sum(row.get("completion_tokens", 0) or 0 for row in usages),
        "total_tokens": sum(row.get("total_tokens", 0) or 0 for row in usages),
        "reasoning_tokens": sum((row.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
                                for row in usages),
        "llm_latency_s": round(sum(latencies), 3),
        "new_llm_latency_s": round(sum(latency for latency, item in zip(latencies, generations)
                                       if item["invoked_this_run"]), 3),
        "candidate_evaluations": len(history),
        "solver_runs": sum(not item["execution_reused"] for item in history),
        "reused_candidate_evaluations": sum(item["execution_reused"] for item in history),
        "dag": dag.to_dict(), "final_solution": final_solution,
        "baseline_z2": z2,
        "objective_match_delta_vs_z2": int(objective is not None and abs(objective - reference) <= 0.1)
        - int(z2.get("objective") is not None and abs(z2["objective"] - reference) <= 0.1),
        "public_answer_hidden_from_prompt": True,
    }
    result["failure_class"] = failure_classification(result)
    write_json(result_path, result)
    write_json(case_dir / "dag.json", result["dag"])
    write_json(case_dir / "trace.json", history)
    (case_dir / "error.json").unlink(missing_ok=True)
    return result


def safe_problem(row: dict, outdir: Path, config: dict, resume: bool) -> dict:
    case_dir = outdir / f"prob_{row['id']:03d}"
    result_path = case_dir / "result.json"
    if resume and result_path.exists():
        previous = json.loads(result_path.read_text())
        if previous.get("run_config") != public_config(config):
            raise ValueError(f"configuration changed for {row['id']}; use a new output directory")
        return previous
    try:
        return run_problem(row, outdir, config, resume)
    except Exception as exc:
        generation_records = []
        for path in sorted(case_dir.glob("generation_[0-9][0-9].json")):
            generation_records.append(json.loads(path.read_text()))
        generations = [record for record in generation_records if record.get("response")]
        history_path = case_dir / "trace.json"
        history = json.loads(history_path.read_text()) if history_path.exists() else []
        usages = [item["response"].get("usage") or {} for item in generations]
        latencies = [(item["response"].get("request_wall_s")
                      or item["response"].get("latency_s") or 0) for item in generations]
        failed_attempts = sum(len(item.get("request_attempts") or [])
                              for item in generation_records if item.get("error"))
        result = {
            "id": row["id"], "run_config": public_config(config),
            "status": "runner_error", "error": f"{type(exc).__name__}: {exc}",
            "initial_score": history[0].get("score") if history else None,
            "final_score": history[-1].get("score") if history else None,
            "objective": None, "reference": float(row["en_answer"]),
            "objective_match_abs_0_1": False, "objective_error": None,
            "objective_below_reference": False, "objective_above_reference": False,
            "exec_status": "runner_error", "solver_status": None,
            "accepted": False, "accepted_round": None, "accepted_but_business_incorrect": False,
            "harmed_win": False, "business_unverified": row["id"] not in AUDIT_IDS,
            "stop_reason": "runner_error", "history": history, "controller_trace": [],
            "deterministic_transforms": 0, "failed_deterministic_transforms": 0,
            "generation_artifacts": [{"path": path.name} for path in sorted(case_dir.glob("generation_*.json"))],
            "llm_calls": len(generations),
            "new_llm_calls": sum(item["invoked_this_run"] for item in generations),
            "api_attempts": sum(len(item["response"].get("request_attempts") or [None])
                                for item in generations) + failed_attempts,
            "retry_accounting_complete": all("request_attempts" in item["response"] for item in generations),
            "usage": usages,
            "prompt_tokens": sum(row.get("prompt_tokens", 0) or 0 for row in usages),
            "completion_tokens": sum(row.get("completion_tokens", 0) or 0 for row in usages),
            "total_tokens": sum(row.get("total_tokens", 0) or 0 for row in usages),
            "reasoning_tokens": sum((row.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
                                    for row in usages),
            "llm_latency_s": round(sum(latencies), 3),
            "new_llm_latency_s": round(sum(latency for latency, item in zip(latencies, generations)
                                           if item["invoked_this_run"]), 3),
            "candidate_evaluations": len(history),
            "solver_runs": sum(not item.get("execution_reused", False) for item in history),
            "reused_candidate_evaluations": sum(item.get("execution_reused", False) for item in history),
            "dag": json.loads((case_dir / "dag.json").read_text()) if (case_dir / "dag.json").exists() else {},
            "final_solution": None, "public_answer_hidden_from_prompt": True,
            "failure_class": "runner_error",
        }
        case_dir.mkdir(parents=True, exist_ok=True)
        write_json(case_dir / "error.json", result)
        return result


def manifest(config: dict, results: list[dict], outdir: Path) -> dict:
    entries = []
    for row in results:
        case_dir = outdir / f"prob_{row['id']:03d}"
        initial_path = case_dir / "generation_00.json"
        initial = json.loads(initial_path.read_text()) if initial_path.exists() else None
        entries.append({
            "id": row["id"], "terminal_status": row["status"],
            "result_path": str((case_dir / ("result.json" if row["status"] == "completed" else "error.json")).relative_to(ROOT)),
            "initial_generation_present": bool(initial and initial.get("response")),
            "initial_model": (initial or {}).get("response", {}).get("model"),
            "llm_calls": row["llm_calls"], "api_attempts": row["api_attempts"],
            "candidate_evaluations": row["candidate_evaluations"],
            "failure_class": row["failure_class"],
        })
    return {
        "schema_version": "industryor.full_pipeline.manifest.v0.1",
        "run_config": public_config(config), "registered_n": len(config["ids"]),
        "accounted_n": len(entries), "initial_generation_n": sum(row["initial_generation_present"] for row in entries),
        "completed_n": sum(row["terminal_status"] == "completed" for row in entries),
        "runner_error_n": sum(row["terminal_status"] == "runner_error" for row in entries),
        "business_semantics": "only the eight independently registered audit IDs; other problems are business_unverified",
        "answer_visibility": "en_answer is used only for final objective grading and baseline deltas",
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="work/industryor_full_qwen_v0.1")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids", type=int, nargs="*")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    rows = json.loads(DATA.read_text())
    if len(rows) != 100 or len({row["id"] for row in rows}) != 100:
        raise ValueError("IndustryOR must contain exactly 100 unique registered problems")
    if args.ids:
        selected = set(args.ids)
        rows = [row for row in rows if row["id"] in selected]
    if args.limit is not None:
        rows = rows[:args.limit]
    if not rows or args.workers < 1:
        raise ValueError("the run needs at least one registered problem and one worker")
    outdir = (ROOT / args.out).resolve()
    if outdir.exists() and any(outdir.iterdir()) and not args.resume:
        raise ValueError("output directory is not empty; use --resume or a new directory")
    outdir.mkdir(parents=True, exist_ok=True)
    protocol = ROOT / "docs/paper/industryor_full_pipeline_protocol_v0.1.md"
    llm_config = llm_mod.load_config()
    config = {
        "llm_config": llm_config,
        "llm": {"model": llm_config.model, "base_url": llm_config.base_url},
        "dataset": str(DATA.relative_to(ROOT)), "dataset_sha256": hashlib.sha256(DATA.read_bytes()).hexdigest(),
        "protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "ids": [row["id"] for row in rows], "max_rounds": MAX_ROUNDS,
        "temperature": 0.6, "reasoning_effort": "medium", "max_tokens": 32768,
        "prior_sha256": digest(load_priors()), "seed": None,
        "metric": "absolute_error_at_most_0.1",
        "independent_business_audit_ids": list(AUDIT_IDS),
        "implementation_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                  for path in IMPLEMENTATION_PATHS},
    }
    write_json(outdir / "run_config.json", public_config(config))
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda row: safe_problem(row, outdir, config, args.resume), rows))
    results.sort(key=lambda row: row["id"])
    if len(results) != len(rows) or {row["id"] for row in results} != {row["id"] for row in rows}:
        raise RuntimeError("not all registered problems are accounted for")
    matches = sum(row["objective_match_abs_0_1"] for row in results)
    audit_rows = [row for row in results if row["id"] in AUDIT_IDS]
    baseline_summary = baseline()
    z2_same_ids_matches = sum(
        row["baseline_z2"].get("objective") is not None
        and abs(row["baseline_z2"]["objective"] - row["reference"]) <= 0.1
        for row in results)
    summary = {
        "n": len(results), "registered_n": len(rows),
        "runner_errors": sum(row["status"] == "runner_error" for row in results),
        "objective_matches_abs_0_1": matches, "objective_match_rate": matches / len(results),
        "initial_objective_matches_abs_0_1": sum(row.get("initial_objective_match_abs_0_1", False) for row in results),
        "exec_ok": sum(row["exec_status"] == "ok" for row in results),
        "optimal": sum(row["solver_status"] == "optimal" for row in results),
        "accepted": sum(row["accepted"] for row in results),
        "accepted_but_business_incorrect": sum(row["accepted_but_business_incorrect"] for row in results),
        "harmed_win": sum(row["harmed_win"] for row in results),
        "objective_below_reference": sum(row["objective_below_reference"] for row in results),
        "objective_above_reference": sum(row["objective_above_reference"] for row in results),
        "llm_calls": sum(row["llm_calls"] for row in results),
        "new_llm_calls": sum(row["new_llm_calls"] for row in results),
        "api_attempts": sum(row["api_attempts"] for row in results),
        "retry_accounting_complete": all(row["retry_accounting_complete"] for row in results),
        "prompt_tokens": sum(row["prompt_tokens"] for row in results),
        "completion_tokens": sum(row["completion_tokens"] for row in results),
        "total_tokens": sum(row["total_tokens"] for row in results),
        "reasoning_tokens": sum(row["reasoning_tokens"] for row in results),
        "llm_latency_s": round(sum(row["llm_latency_s"] for row in results), 3),
        "new_llm_latency_s": round(sum(row["new_llm_latency_s"] for row in results), 3),
        "candidate_evaluations": sum(row["candidate_evaluations"] for row in results),
        "solver_runs": sum(row["solver_runs"] for row in results),
        "reused_candidate_evaluations": sum(row["reused_candidate_evaluations"] for row in results),
        "deterministic_transforms": sum(row["deterministic_transforms"] for row in results),
        "failed_deterministic_transforms": sum(row["failed_deterministic_transforms"] for row in results),
        "rollbacks": sum(event["type"] == "rollback" for row in results
                         for event in row.get("dag", {}).get("events", [])),
        "duplicate_candidate_stops": sum(row["stop_reason"] == "duplicate_candidate" for row in results),
        "business_audit": {
            "n": len(audit_rows),
            "initial_business_correct": sum((row["initial_score"] or {}).get("business_correct", False)
                                            for row in audit_rows),
            "final_business_correct": sum((row["final_score"] or {}).get("business_correct", False)
                                          for row in audit_rows),
            "unverified_or_blocked": sum((row["final_score"] or {}).get("audit_status") != "complete"
                                         for row in audit_rows),
            "blocked": sum((row["final_score"] or {}).get("audit_status") == "blocked" for row in audit_rows),
        },
        "business_unverified": sum(row["business_unverified"] for row in results),
        "failure_classes": dict(sorted(Counter(row["failure_class"] for row in results).items())),
        "stop_reasons": dict(sorted(Counter(row["stop_reason"] for row in results).items())),
        "baseline_z2_same_ids_n": len(results),
        "baseline_z2_same_ids_abs_0_1": z2_same_ids_matches,
        "delta_vs_z2_abs_0_1": matches - z2_same_ids_matches,
        "improved_vs_z2": sum(row["objective_match_delta_vs_z2"] > 0 for row in results),
        "worsened_vs_z2": sum(row["objective_match_delta_vs_z2"] < 0 for row in results),
        "wall_seconds": round(time.monotonic() - started, 3),
    }
    analysis = {"run_config": public_config(config), "summary": summary,
                "baseline": baseline_summary, "results": results}
    write_json(outdir / "analysis.json", analysis)
    write_json(outdir / "manifest.json", manifest(config, results, outdir))
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    main()

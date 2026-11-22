"""Witness initialization and target-aware residual repair for clean ORAgentBench runs."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from . import llm as llm_mod
from .cleanroom import (
    FAIL,
    PASS,
    UNKNOWN,
    AuditCase,
    CleanCheckAsset,
    EvidenceMemory,
    RepairDAG,
    TrustController,
    Verdict,
)
from .oragentbench import (
    TaskPacket,
    execute_solver,
    generate_artifacts,
    official_evaluate,
    official_metrics,
    prepare_workspace,
    probe_pyscipopt_api,
    proxy_match,
    read_json,
    run_oracle,
    write_json,
)


def solution_exists(workspace: Path) -> bool:
    submissions = workspace / "submissions"
    return (submissions / "solution.csv").exists() or (submissions / "solution.json").exists()


class ExecutionContract:
    def __call__(self, artifact: dict) -> Verdict:
        execution = artifact.get("execution")
        if execution is None:
            return Verdict(UNKNOWN, "missing execution record")
        if execution.get("return_code") == 0 and solution_exists(artifact["workspace"]):
            return Verdict(PASS, "solver completed and a decision artifact exists")
        return Verdict(FAIL, "solver failed or no decision artifact exists")


class OfficialTaskPass:
    def __call__(self, artifact: dict) -> Verdict:
        official = artifact.get("official")
        if official is None:
            packet = artifact["packet"]
            workspace = artifact["workspace"]
            official = official_evaluate(packet, workspace, artifact["audit_out"])
        metrics = official_metrics(official)
        if metrics["true_correct"]:
            return Verdict(PASS, "official feasibility and quality threshold passed")
        if metrics["objective"] is None and not metrics["feasible"]:
            return Verdict(FAIL, "official evaluator rejected or found no solution")
        return Verdict(FAIL, "official feasibility or quality threshold failed")


def evaluate_witness(memory: EvidenceMemory, packet: TaskPacket, workspace: Path,
                     execution: dict, official: dict | None, outdir: Path) -> dict[str, str]:
    artifact = {"packet": packet, "workspace": workspace, "execution": execution,
                "official": official, "audit_out": outdir}
    verdicts = {}
    for asset in memory.authorized_checks(packet.scope):
        try:
            verdict = asset.evaluator(artifact)
        except Exception as exc:
            verdict = Verdict(UNKNOWN, f"{type(exc).__name__}: {exc}")
        verdicts[asset.check_id] = verdict.status
    return verdicts


def _wrong_workspace(source: Path, destination: Path, mutation: str) -> Path:
    shutil.copytree(source, destination, dirs_exist_ok=True)
    submissions = destination / "submissions"
    solution = submissions / "solution.csv"
    if mutation == "missing_solution":
        for candidate in (solution, submissions / "solution.json"):
            if candidate.exists():
                candidate.unlink()
    elif mutation == "invalid_schema":
        solution.write_text("wrong,columns\n1,2,3\n")
    elif mutation == "empty_solution":
        solution.write_text("")
    else:
        raise ValueError(mutation)
    return destination


def initialize_witness(memory: EvidenceMemory, packets: list[TaskPacket], outdir: Path,
                       oracle_source: Path | None = None) -> dict:
    if len(packets) < 3:
        raise ValueError("at least three independent dev/audit tasks are required")
    if len({packet.domain for packet in packets}) != 1:
        raise ValueError("one witness initialization batch must share a domain")
    if any(packet.split not in {"dev", "audit"} for packet in packets):
        raise ValueError("oracle references are only allowed in dev/audit")
    outdir.mkdir(parents=True, exist_ok=True)
    domain = packets[0].domain
    source_document = "\n".join(packet.instruction + "\n" + packet.problem_statement for packet in packets)
    source_quote = "required solution file"
    if source_quote not in source_document:
        raise ValueError("common output-contract source was not found")
    if "execution_contract" not in memory.checks:
        memory.register_check(CleanCheckAsset("execution_contract", ExecutionContract(),
                                              {"dataset": "oragentbench"}, source_quote, source_document))
        execution_cases = []
        for index in range(3):
            execution_cases.append(AuditCase(f"exec_clean_{index}", {
                "execution": {"return_code": 0}, "workspace": outdir / "fake_clean_workspace"}, PASS))
            execution_cases.append(AuditCase(f"exec_wrong_{index}", {
                "execution": {"return_code": 1}, "workspace": outdir / "fake_wrong_workspace"}, FAIL))
        (outdir / "fake_clean_workspace/submissions").mkdir(parents=True, exist_ok=True)
        (outdir / "fake_clean_workspace/submissions/solution.csv").write_text("placeholder")
        execution_audit = memory.authorize_check("execution_contract", execution_cases)
    else:
        execution_audit = None

    check_id = f"{domain}_official_task_pass"
    if check_id in memory.checks:
        return {"execution_audit": execution_audit, "official_audit": None}
    memory.register_check(CleanCheckAsset(check_id, OfficialTaskPass(),
                                          {"dataset": "oragentbench", "domain": domain},
                                          source_quote, source_document))
    cases = []
    for packet in packets:
        oracle_dir = (oracle_source / packet.name / "oracle") if oracle_source is not None \
            else (outdir / packet.name / "oracle")
        oracle_app = oracle_dir / "app"
        result_path = oracle_dir / "result.json"
        if result_path.exists():
            oracle = read_json(result_path)
        else:
            oracle = run_oracle(packet, oracle_app)
            write_json(result_path, oracle)
        if not oracle["metrics"]["true_correct"]:
            raise ValueError(f"oracle does not pass the official threshold: {packet.name}")
        clean_artifact = {"packet": packet, "workspace": oracle_app,
                          "execution": {"return_code": 0}, "official": oracle["official"]}
        cases.append(AuditCase(f"{packet.name}:clean", clean_artifact, PASS))
        for mutation in ("missing_solution", "invalid_schema", "empty_solution"):
            cached_app = oracle_source / packet.name / mutation / "app" if oracle_source is not None else None
            cached_result = oracle_source / packet.name / mutation / "official/official_evaluation.json" \
                if oracle_source is not None else None
            if cached_result is not None and cached_result.exists():
                wrong_app = cached_app
                wrong_official = read_json(cached_result)
            else:
                wrong_app = _wrong_workspace(oracle_app, outdir / packet.name / mutation / "app", mutation)
                wrong_official = official_evaluate(packet, wrong_app, outdir / packet.name / mutation / "official")
            wrong_artifact = {"packet": packet, "workspace": wrong_app,
                              "execution": {"return_code": 0}, "official": wrong_official}
            cases.append(AuditCase(f"{packet.name}:{mutation}", wrong_artifact, FAIL))
    official_audit = memory.authorize_check(check_id, cases)
    write_json(outdir / "witness_initialization.json", {
        "domain": domain, "n_tasks": len(packets), "n_cases": len(cases),
        "execution_audit": execution_audit, "official_audit": official_audit,
        "scope_note": "Official task evaluators are used only in dev/audit. This is not a universal cross-domain Witness."})
    return {"execution_audit": execution_audit, "official_audit": official_audit}


def semantic_findings(record: dict, workspace: Path) -> list[dict]:
    errors = record.get("official", {}).get("evaluation", {}).get("errors") or []
    if "activation violated" not in " ".join(errors):
        return []
    variables = set()
    solution_path = workspace / "submissions/solution.csv"
    if solution_path.exists():
        with solution_path.open(newline="") as handle:
            variables = {row["variable"] for row in csv.DictReader(handle)}
    code = record["artifacts"]["solve_py"]
    findings = []
    for variable in ("use_plant_dc", "use_dc_customer"):
        if variable not in code:
            findings.append({"type": "missing_activation_variable_in_model_and_output",
                             "variable": variable})
        elif variable not in variables:
            findings.append({"type": "missing_activation_row_in_output", "variable": variable})
    return findings


def repair_once(memory: EvidenceMemory, packet: TaskPacket, record: dict, specification: str,
                config: llm_mod.LLMConfig, outdir: Path, run_seed: int = 0,
                api_guard: bool = False, dag: RepairDAG | None = None,
                parent_id: str = "root", attempt: int = 1) -> dict:
    if record["true_correct"]:
        return {"status": "preserved_win", "record": record}
    if packet.split not in {"dev", "audit", "transfer"}:
        raise ValueError("Witness feedback repair is not allowed on final evaluation tasks")
    if not record.get("artifacts"):
        return {"status": "no_artifact", "record": record}
    execution = record["execution"]
    root_workspace = Path(record["workspace"])
    before = evaluate_witness(memory, packet, root_workspace, execution,
                              record.get("official"), outdir / "before")
    if not before:
        return {"status": "no_authorized_check", "before": before}
    target = "execution_contract" if before.get("execution_contract") == FAIL \
        else f"{packet.domain}_official_task_pass"
    if target not in before:
        return {"status": "no_authorized_target", "target": target, "before": before}

    if dag is None:
        dag = RepairDAG(TrustController(memory))
    if not dag.nodes:
        dag.add_root(record["artifacts"]["solve_py"], before)
    controller = dag.controller
    execution_diagnostics = dict(execution)
    for stream in ("stderr", "stdout"):
        path = root_workspace.parent / f"execution/{stream}.txt"
        if path.exists():
            execution_diagnostics[f"{stream}_tail"] = path.read_text(errors="replace")[-4000:]
    if "pyscipopt" in execution_diagnostics.get("stderr_tail", "").lower():
        evidence_api = probe_pyscipopt_api(outdir / "api_probe")
        execution_diagnostics["api_contract"] = evidence_api["stdout"]
    evidence = {
        "target_check": target,
        "execution": execution_diagnostics,
        "witness_verdicts": before,
        "official_errors": (record.get("official", {}).get("evaluation", {}).get("errors") or [])[:20],
        "semantic_findings": semantic_findings(record, root_workspace),
        "search_guidance": {
            "attempt": attempt,
            "alternate_branch": attempt > 1,
            "regenerate_from_evidence": attempt > 1 and execution.get("return_code") == 0
            and not execution.get("timed_out"),
            "instruction": "Earlier attempts did not establish verified progress. Do not repeat the previous code or make cosmetic edits. Rebuild the decision structure around every unmet public requirement, and explicitly verify every demand, service, route and output coordinate before writing the decision artifact."
            if attempt > 1 and execution.get("return_code") == 0 and not execution.get("timed_out")
            else "Preserve unrelated business requirements and address the target evidence. For a runtime failure, repair the observed cause in the current solver rather than replacing its working model. Assemble solver terms in ordinary Python lists and test the list before calling quicksum; never compare a PySCIPOpt expression with !=, <, or >. Check that a solution exists before reading its objective.",
        },
    }
    base = outdir / "repair_1"
    phase = "generation"
    try:
        artifacts = generate_artifacts(packet, specification, config, base / "generation", run_seed,
                                       repair={"artifacts": record["artifacts"], "evidence": evidence})
        phase = "workspace"
        workspace = base / "app"
        prepare_workspace(packet, workspace, artifacts, api_guard=api_guard)
        phase = "execution"
        child_execution = execute_solver(workspace, base / "execution")
        phase = "official_evaluation"
        child_official = official_evaluate(packet, workspace, base / "official")
    except Exception as exc:
        result = {"status": "repair_failed", "phase": phase,
                  "error": f"{type(exc).__name__}: {exc}", "before": before,
                  "dag": dag.to_dict()}
        write_json(outdir / "repair_result.json", result)
        return result
    after = evaluate_witness(memory, packet, workspace, child_execution, child_official, base / "after")
    metrics = official_metrics(child_official)
    proxy = proxy_match(packet, child_official)
    guard_path = workspace / "api_guard.json"
    child_record = {**record, "attempt": attempt, "artifacts": artifacts, "execution": child_execution,
                    "official": child_official, **metrics, "workspace": str(workspace),
                    "proxy_match": proxy, "phantom_proxy": bool(proxy) and not metrics["true_correct"],
                    "unknown": metrics["evaluation_unknown"],
                    "api_guard": read_json(guard_path) if guard_path.exists() else None,
                    "generation_error": None}
    write_json(base / "record.json", child_record)
    try:
        node = dag.add_repair(parent_id, artifacts["solve_py"], target, before, after, packet.scope)
    except ValueError as exc:
        result = {"status": "duplicate_repair", "error": str(exc), "before": before, "after": after,
                  "record": child_record, "dag": dag.to_dict()}
        write_json(outdir / "repair_result.json", result)
        return result
    final_accept, final_reasons = controller.final_accept(packet.scope, after)
    result = {"status": "accepted" if node.accepted and final_accept
              else "partial_progress" if node.accepted else "rejected",
              "target": target, "before": before, "after": after,
              "node_id": node.node_id, "edge_accepted": node.accepted, "edge_reasons": node.reasons,
              "final_accept": final_accept, "final_reasons": final_reasons,
              "record": child_record, "record_path": str(base / "record.json"), "dag": dag.to_dict()}
    write_json(outdir / "repair_result.json", result)
    return result


def _evidence_transition(current: dict, child: dict) -> str:
    def errors(record):
        return (record.get("official", {}).get("evaluation", {}).get("errors") or [])

    comparisons = (
        (bool(current.get("true_correct")), bool(child.get("true_correct"))),
        (current.get("execution", {}).get("return_code") == 0,
         child.get("execution", {}).get("return_code") == 0),
        (bool(current.get("feasible")), bool(child.get("feasible"))),
        (not current.get("phantom_proxy"), not child.get("phantom_proxy")),
        (not (current.get("unknown") or current.get("evaluation_unknown")),
         not (child.get("unknown") or child.get("evaluation_unknown"))),
    )
    if any(old and not new for old, new in comparisons):
        return "regression"
    old_errors, new_errors = len(errors(current)), len(errors(child))
    old_quality, new_quality = current.get("quality") or 0.0, child.get("quality") or 0.0
    if new_errors > old_errors or new_quality < old_quality:
        return "regression"
    if any(new and not old for old, new in comparisons) \
            or new_errors < old_errors or new_quality > old_quality:
        return "progress"
    return "unchanged"


def repair_bounded(memory: EvidenceMemory, packet: TaskPacket, record: dict, specification: str,
                   config: llm_mod.LLMConfig, outdir: Path, run_seed: int = 0,
                   max_attempts: int = 3, api_guard: bool = False) -> dict:
    from .cleanroom_analysis import USAGE_KEYS, generation_cost, pair_win_safe, summarize_records

    if not 1 <= max_attempts <= 3:
        raise ValueError("repair budget must be between one and three attempts")
    if record["true_correct"]:
        result = {"status": "preserved_win", "record": record, "attempts_used": 0,
                  "win_safe": True, "final_accept": True}
        write_json(outdir / "repair_result.json", result)
        return result
    if packet.split not in {"dev", "audit", "transfer"}:
        raise ValueError("Witness feedback repair is not allowed on final evaluation tasks")
    memory.freeze()
    baseline = record
    current = record
    before = evaluate_witness(memory, packet, Path(record["workspace"]), record["execution"],
                              record.get("official"), outdir / "root")
    dag = RepairDAG(TrustController(memory))
    if record.get("artifacts"):
        dag.add_root(record["artifacts"]["solve_py"], before)
    history = []
    attempt_records = []
    parent_id = "root"
    final_record = baseline
    final_verdicts = before
    stop_reason = "bounded_failure"
    unchanged_streak = 0
    for attempt in range(1, max_attempts + 1):
        result = repair_once(memory, packet, current, specification, config,
                             outdir / f"attempt_{attempt}", run_seed + attempt - 1,
                             api_guard=api_guard, dag=dag, parent_id=parent_id, attempt=attempt)
        history.append({key: value for key, value in result.items() if key not in {"record", "dag"}})
        child = result.get("record")
        if child is not None and child["workspace"] != current["workspace"]:
            attempt_records.append(child)
        if result["status"] == "accepted":
            history[-1]["evidence_transition"] = _evidence_transition(current, child)
            final_record = result["record"]
            final_verdicts = result["after"]
            stop_reason = "accepted"
            break
        if result["status"] in {"preserved_win", "no_artifact", "no_authorized_check",
                                "no_authorized_target", "duplicate_repair"}:
            stop_reason = result["status"]
            break
        if result["status"] == "repair_failed":
            stop_reason = result["status"]
            continue
        child = result["record"]
        transition = _evidence_transition(current, child)
        history[-1]["evidence_transition"] = transition
        if transition == "unchanged":
            previous_execution = current.get("execution") or {}
            child_execution = child.get("execution") or {}
            previous_error = previous_execution.get("stderr") or previous_execution.get("stderr_tail")
            child_error = child_execution.get("stderr") or child_execution.get("stderr_tail")
            new_runtime_diagnostic = (previous_execution.get("return_code") != 0
                                      and child_execution.get("return_code") != 0
                                      and bool(previous_error) and bool(child_error)
                                      and previous_error != child_error)
            if new_runtime_diagnostic:
                unchanged_streak = 0
                current = child
                parent_id = result["node_id"]
                stop_reason = "bounded_failure"
                history[-1]["working_branch_advanced"] = True
                history[-1]["verified_progress"] = False
                continue
            unchanged_streak += 1
            stop_reason = "no_verified_progress"
            if unchanged_streak >= 2:
                break
            continue
        unchanged_streak = 0
        if transition == "regression":
            stop_reason = "rejected_regression"
            continue
        current = child
        parent_id = result["node_id"]
        stop_reason = "bounded_failure"
    accepted = stop_reason == "accepted"
    generation_costs = [generation_cost(baseline)]
    generation_costs += [generation_cost({"workspace": outdir / f"attempt_{index}/repair_1/app"})
                         for index in range(1, len(history) + 1)]
    cost = summarize_records([baseline, *attempt_records])["cost"]
    for key in ("llm_calls", "missing_usage_calls", "llm_latency_seconds", *USAGE_KEYS):
        cost[key] = sum(part[key] for part in generation_costs)
    cost["llm_latency_seconds"] = round(cost["llm_latency_seconds"], 6)
    comparison = pair_win_safe([baseline], [final_record])
    result = {"status": stop_reason, "record": final_record, "before": before, "after": final_verdicts,
              "final_accept": accepted, "edge_accepted": history[-1].get("edge_accepted", False)
              if history else False,
              "attempts_used": len(history), "max_attempts": max_attempts,
              "history": history,
              "attempt_record_paths": [str(Path(path["workspace"]).parent / "record.json")
                                       for path in attempt_records],
              "pair_win_safe": comparison, "win_safe": comparison["win_safe"], "cost": cost,
              "memory_frozen": memory.frozen, "dag": dag.to_dict()}
    write_json(outdir / "repair_result.json", result)
    return result

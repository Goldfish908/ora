"""Witness initialization and target-aware residual repair for clean ORAgentBench runs."""
from __future__ import annotations

import csv
import hashlib
import json
import math
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
from .decision_repair import (
    decision_artifact_path,
    decision_artifact_sha256,
    execute_decision_repair,
    generate_decision_code_patch,
    generate_decision_repair,
    prepare_decision_repair_workspace,
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
        if metrics["evaluation_unknown"]:
            return Verdict(UNKNOWN, "official evaluation is missing, invalid or contradictory")
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
    elif mutation in {"invalid_schema", "empty_solution"}:
        for candidate in (solution, submissions / "solution.json"):
            if candidate.exists():
                candidate.unlink()
        solution.write_text("wrong,columns\n1,2,3\n" if mutation == "invalid_schema" else "")
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
    required_variables = ("use_plant_dc", "use_dc_customer")
    public_documents = "\n".join((record.get("problem") or {}).get("public_files", {}).values())
    if any(variable not in public_documents for variable in required_variables):
        return []
    variables = set()
    solution_path = workspace / "submissions/solution.csv"
    if solution_path.exists():
        with solution_path.open(newline="") as handle:
            variables = {row.get("variable") for row in csv.DictReader(handle)}
    code = record["artifacts"]["solve_py"]
    findings = []
    for variable in required_variables:
        if variable not in code:
            findings.append({"type": "missing_activation_variable_in_model_and_output",
                             "variable": variable})
        elif variable not in variables:
            findings.append({"type": "missing_activation_row_in_output", "variable": variable})
    return findings


def has_genuine_incumbent(record: dict) -> bool:
    if record.get("true_correct") or record.get("feasible"):
        return True
    path = decision_artifact_path(Path(record["workspace"]))
    if path is None:
        return False
    try:
        if path.suffix == ".csv":
            with path.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            if not rows:
                return False
            if all((row.get("row_type") or "").strip().lower() == "unmet" for row in rows):
                return False
            markers = ("value", "quantity", "amount", "flow", "served", "unmet", "module", "open", "count")
            values = []
            for row in rows:
                for name, raw in row.items():
                    if raw is None or not any(marker in (name or "").lower() for marker in markers):
                        continue
                    try:
                        value = float(raw)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(value):
                        values.append(value)
            return not values or any(abs(value) > 1e-12 for value in values)
        payload = json.loads(path.read_text())
        if payload in ({}, []):
            return False

        def numbers(value):
            if isinstance(value, bool):
                return []
            if isinstance(value, (int, float)) and math.isfinite(value):
                return [float(value)]
            if isinstance(value, dict):
                return [number for item in value.values() for number in numbers(item)]
            if isinstance(value, list):
                return [number for item in value for number in numbers(item)]
            return []

        values = numbers(payload)
        return not values or any(abs(value) > 1e-12 for value in values)
    except (OSError, ValueError, TypeError, csv.Error, json.JSONDecodeError):
        return False


def repair_route(record: dict) -> str:
    if _record_unknown(record):
        return "evaluation_unknown"
    if record.get("true_correct"):
        return "preserved_win"
    if (record.get("execution") or {}).get("return_code") != 0:
        return "model_runtime_repair"
    if record.get("feasible"):
        return "objective_optimization"
    if not has_genuine_incumbent(record):
        return "model_diagnosis"
    errors = record.get("official", {}).get("evaluation", {}).get("errors") or []
    return "decision_repair" if errors else "model_diagnosis"


def _decision_repair_eligible(record: dict) -> bool:
    if record.get("true_correct") or record.get("feasible"):
        return False
    if (record.get("execution") or {}).get("return_code") != 0:
        return False
    errors = (record.get("official", {}).get("evaluation", {}).get("errors") or [])
    return bool(errors) and has_genuine_incumbent(record)


def _decision_repair_code_eligible(record: dict) -> bool:
    execution = record.get("execution") or {}
    return "repair_solution_py" in (record.get("artifacts") or {}) \
        and execution.get("return_code") not in {0, None} and not execution.get("timed_out") \
        and bool(execution.get("stderr") or execution.get("stderr_tail"))


def _decision_repair_result_eligible(record: dict) -> bool:
    if record.get("true_correct") or record.get("feasible"):
        return False
    if (record.get("execution") or {}).get("return_code") != 0:
        return False
    if "repair_solution_py" not in (record.get("artifacts") or {}):
        return False
    errors = record.get("official", {}).get("evaluation", {}).get("errors") or []
    return bool(errors) and has_genuine_incumbent(record)


def _decision_repair_mode(record: dict, attempt: int) -> str | None:
    if attempt == 1 and _decision_repair_eligible(record):
        return "decision_repair"
    if attempt > 1 and _decision_repair_code_eligible(record):
        return "decision_runtime_patch"
    if attempt == 2 and _decision_repair_result_eligible(record):
        return "decision_repair"
    return None


def _regenerate_from_evidence(record: dict, attempt: int,
                              previous_generation_failure: str | None) -> bool:
    if attempt <= 1:
        return False
    execution = record.get("execution") or {}
    if execution.get("return_code") == 0 and not execution.get("timed_out"):
        return True
    return bool(record.get("generation_error") and previous_generation_failure)


def _record_unknown(record: dict) -> bool:
    if record.get("unknown") or record.get("evaluation_unknown"):
        return True
    official = record.get("official")
    return bool(isinstance(official, dict) and "runner" in official
                and official_metrics(official)["evaluation_unknown"])


def _without_unknown_business_claims(record: dict) -> dict:
    if not _record_unknown(record):
        return record
    return {**record, "feasible": False, "quality": 0.0, "true_correct": False,
            "objective": None, "phantom_proxy": False, "unknown": True}


def repair_once(memory: EvidenceMemory, packet: TaskPacket, record: dict, specification: str,
                config: llm_mod.LLMConfig, outdir: Path, run_seed: int = 0,
                api_guard: bool = False, dag: RepairDAG | None = None,
                parent_id: str = "root", attempt: int = 1,
                previous_generation_failure: str | None = None) -> dict:
    record = _without_unknown_business_claims(record)
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
    if _record_unknown(record) or UNKNOWN in before.values():
        return {"status": "evaluation_unknown", "record": record, "before": before,
                "final_accept": False}
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
    decision_mode = _decision_repair_mode(record, attempt)
    evidence = {
        "target_check": target,
        "execution": execution_diagnostics,
        "witness_verdicts": before,
        "official_errors": (record.get("official", {}).get("evaluation", {}).get("errors") or [])[:20],
        "observed_metrics": {key: record.get(key) for key in
                             ("feasible", "quality", "objective", "proxy_match", "phantom_proxy")},
        "semantic_findings": semantic_findings(record, root_workspace),
        "search_guidance": {
            "attempt": attempt,
            "alternate_branch": attempt > 1,
            "regenerate_from_evidence": _regenerate_from_evidence(
                record, attempt, previous_generation_failure),
            "repair_kind": decision_mode or ("runtime_patch" if execution.get("return_code") not in {0, None}
            and not execution.get("timed_out")
            and (execution.get("stderr") or execution.get("stderr_tail")) else "complete_artifacts"),
            "instruction": "Repair only the incumbent decisions using public data. Preserve every hard requirement and unrelated correct decision, and recompute all constraints and the objective from the emitted solution."
            if decision_mode is not None
            else "Earlier attempts did not establish verified progress. Do not repeat the previous code or make cosmetic edits. Rebuild the decision structure around every unmet public requirement, and explicitly verify every demand, service, route and output coordinate before writing the decision artifact."
            if _regenerate_from_evidence(record, attempt, previous_generation_failure)
            else "Preserve unrelated business requirements and address the target evidence. For a runtime failure, repair the observed cause in the current solver rather than replacing its working model. Assemble solver terms in ordinary Python lists and test the list before calling quicksum; never compare a PySCIPOpt expression with !=, <, or >. Check that a solution exists before reading its objective.",
        },
    }
    quality_guidance = _quality_guidance(record)
    if quality_guidance:
        evidence["quality_guidance"] = quality_guidance
    if previous_generation_failure:
        evidence["previous_generation_failure"] = previous_generation_failure
    base = outdir / "repair_1"
    phase = "generation"
    try:
        repair_input = {"artifacts": record["artifacts"], "evidence": evidence}
        if decision_mode is not None:
            incumbent_path = decision_artifact_path(root_workspace)
            if incumbent_path is None:
                for name in ("solution_original.csv", "solution_original.json"):
                    candidate = root_workspace / "submissions" / name
                    if candidate.exists():
                        incumbent_path = candidate
                        break
            if incumbent_path is None:
                raise ValueError("decision repair requires an agent-generated incumbent")
            repair_input["decision_artifact"] = incumbent_path.read_text()
        if decision_mode == "decision_runtime_patch":
            artifacts = generate_decision_code_patch(packet, specification, config, base / "generation",
                                                    run_seed, repair_input)
        elif decision_mode == "decision_repair":
            artifacts = generate_decision_repair(packet, specification, config, base / "generation",
                                                run_seed, repair_input)
        else:
            artifacts = generate_artifacts(packet, specification, config, base / "generation", run_seed,
                                           repair=repair_input)
        phase = "workspace"
        workspace = base / "app"
        if decision_mode is not None:
            prepare_decision_repair_workspace(packet, workspace, artifacts, root_workspace,
                                              api_guard=api_guard)
            phase = "execution"
            child_execution = execute_decision_repair(workspace, base / "execution")
        else:
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
                    "candidate_sha256": hashlib.sha256(specification.encode()).hexdigest(),
                    "official": child_official, **metrics, "workspace": str(workspace),
                    "proxy_match": proxy, "phantom_proxy": bool(proxy) and not metrics["true_correct"],
                    "unknown": metrics["evaluation_unknown"],
                    "decision_artifact_sha256": decision_artifact_sha256(workspace)
                    if decision_mode is not None else None,
                    "api_guard": read_json(guard_path) if guard_path.exists() else None,
                    "generation_error": None}
    write_json(base / "record.json", child_record)
    repair_identity = artifacts["solve_py"]
    if "repair_solution_py" in artifacts:
        repair_identity += "\n" + artifacts["repair_solution_py"]
    try:
        node = dag.add_repair(parent_id, repair_identity, target, before, after, packet.scope)
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


def _quality_guidance(record: dict) -> dict | None:
    if record.get("true_correct") or not record.get("feasible"):
        return None
    details = (record.get("official") or {}).get("reward_details") or {}
    return {"status": "quality_shortfall", "objective": record.get("objective"),
            "quality": record.get("quality"), "required_quality": "greater than 0.4",
            "quality_status": details.get("quality_status"),
            "objective_sense": details.get("objective_sense"),
            "instruction": "The solution is feasible but below the official quality threshold. Preserve every hard constraint and the exact output schema while improving the modeled objective. Recompute the objective from the emitted decisions and check its consistency with the solver objective; do not sacrifice feasibility or fabricate a reference objective."}


def _finite_objective(record: dict) -> float | None:
    value = record.get("objective")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value) else None


def _objective_transition(current: dict, child: dict) -> str | None:
    old, new = _finite_objective(current), _finite_objective(child)
    if old is None or new is None:
        return None
    if old == new:
        return "same"
    current_details = (current.get("official") or {}).get("reward_details") or {}
    child_details = (child.get("official") or {}).get("reward_details") or {}
    sense = child_details.get("objective_sense") or current_details.get("objective_sense")
    if sense == "minimize":
        return "better" if new < old else "worse"
    if sense == "maximize":
        return "better" if new > old else "worse"
    return None


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
    objective_transition = _objective_transition(current, child)
    execution_recovered = ((current.get("execution", {}).get("return_code") != 0)
                           and (child.get("execution", {}).get("return_code") == 0)
                           and not current.get("feasible") and current.get("objective") is None
                           and new_quality >= old_quality)
    if execution_recovered:
        return "progress"
    if new_errors > old_errors or new_quality < old_quality or objective_transition == "worse":
        return "regression"
    if any(new and not old for old, new in comparisons) \
            or new_errors < old_errors or new_quality > old_quality or objective_transition == "better":
        return "progress"
    return "unchanged"


def _best_effort_fallback(baseline: dict, candidate: dict) -> bool:
    if candidate is baseline or baseline.get("true_correct") or candidate.get("true_correct"):
        return False
    if not baseline.get("phantom_proxy") or candidate.get("phantom_proxy") or not candidate.get("feasible"):
        return False
    if candidate.get("unknown") or candidate.get("evaluation_unknown"):
        return False
    if (candidate.get("execution") or {}).get("return_code") != 0:
        return False
    old_objective, new_objective = _finite_objective(baseline), _finite_objective(candidate)
    if old_objective is not None and new_objective is None:
        return False
    if old_objective is not None and new_objective is not None \
            and _objective_transition(baseline, candidate) not in {"same", "better"}:
        return False
    return (candidate.get("quality") or 0.0) >= (baseline.get("quality") or 0.0)


def repair_bounded(memory: EvidenceMemory, packet: TaskPacket, record: dict, specification: str,
                   config: llm_mod.LLMConfig, outdir: Path, run_seed: int = 0,
                   max_attempts: int = 3, api_guard: bool = False,
                   allow_empty_spec_regeneration: bool = True) -> dict:
    from .cleanroom_analysis import USAGE_KEYS, generation_cost, pair_win_safe, summarize_records

    if not 1 <= max_attempts <= 3:
        raise ValueError("repair budget must be between one and three attempts")
    record = _without_unknown_business_claims(record)
    root_unknown = _record_unknown(record)
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
    root_unknown = root_unknown or UNKNOWN in before.values()
    dag = RepairDAG(TrustController(memory))
    if record.get("artifacts"):
        dag.add_root(record["artifacts"]["solve_py"], before)
    history = []
    attempt_records = []
    parent_id = "root"
    final_record = baseline
    final_verdicts = before
    current_verdicts = before
    stop_reason = "evaluation_unknown" if root_unknown else "bounded_failure"
    unchanged_streak = 0
    previous_generation_failure = None
    for attempt in range(1, max_attempts + 1) if not root_unknown else []:
        branch_specification = specification
        if allow_empty_spec_regeneration and attempt == 2 \
                and _regenerate_from_evidence(current, attempt, previous_generation_failure):
            branch_specification = ""
        result = repair_once(memory, packet, current, branch_specification, config,
                             outdir / f"attempt_{attempt}", run_seed + attempt - 1,
                             api_guard=api_guard, dag=dag, parent_id=parent_id, attempt=attempt,
                             previous_generation_failure=previous_generation_failure)
        history.append({key: value for key, value in result.items() if key not in {"record", "dag"}})
        history[-1]["specification_sha256"] = hashlib.sha256(branch_specification.encode()).hexdigest()
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
            previous_generation_failure = result.get("error")
            continue
        previous_generation_failure = None
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
                current_verdicts = result["after"]
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
        current_verdicts = result["after"]
        parent_id = result["node_id"]
        stop_reason = "bounded_failure"
    if stop_reason != "accepted" and _best_effort_fallback(baseline, current):
        final_record = current
        final_verdicts = current_verdicts
        stop_reason = "best_effort_fallback"
    accepted = stop_reason == "accepted"
    generation_costs = [generation_cost(baseline)]
    generation_costs += [generation_cost({"workspace": outdir / f"attempt_{index}/repair_1/app"})
                         for index in range(1, len(history) + 1)]
    cost = summarize_records([baseline, *attempt_records])["cost"]
    for key in ("llm_calls", "api_requests", "missing_usage_calls", "llm_latency_seconds", *USAGE_KEYS):
        cost[key] = sum(part[key] for part in generation_costs)
    cost["llm_latency_seconds"] = round(cost["llm_latency_seconds"], 6)
    comparison = pair_win_safe([baseline], [final_record])
    checkpoint = final_record if accepted else current
    checkpoint_verdicts = final_verdicts if accepted else current_verdicts
    result = {"status": stop_reason, "record": final_record, "before": before, "after": final_verdicts,
              "final_accept": accepted, "edge_accepted": history[-1].get("edge_accepted", False)
              if history else False,
              "attempts_used": len(history), "max_attempts": max_attempts,
              "history": history,
              "attempt_record_paths": [str(Path(path["workspace"]).parent / "record.json")
                                       for path in attempt_records],
              "pair_win_safe": comparison, "win_safe": comparison["win_safe"],
              "strict_safe": comparison["strict_safe"], "cost": cost,
              "checkpoint_record": checkpoint, "checkpoint_verdicts": checkpoint_verdicts,
              "checkpoint_route": repair_route(checkpoint),
              "checkpoint_record_path": str(Path(checkpoint["workspace"]).parent / "record.json"),
              "memory_frozen": memory.frozen, "dag": dag.to_dict()}
    write_json(outdir / "repair_result.json", result)
    return result

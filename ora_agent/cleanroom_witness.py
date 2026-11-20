"""Witness initialization and target-aware residual repair for clean ORAgentBench runs."""
from __future__ import annotations

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
    shutil.copytree(source, destination)
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


def repair_once(memory: EvidenceMemory, packet: TaskPacket, record: dict, specification: str,
                config: llm_mod.LLMConfig, outdir: Path, run_seed: int = 0) -> dict:
    if record["true_correct"]:
        return {"status": "preserved_win", "record": record}
    if packet.split not in {"dev", "audit", "transfer"}:
        raise ValueError("Witness feedback repair is not allowed on final evaluation tasks")
    execution = record["execution"]
    root_workspace = Path(record["workspace"])
    before = evaluate_witness(memory, packet, root_workspace, execution,
                              record.get("official"), outdir / "before")
    if not before:
        return {"status": "no_authorized_check", "before": before}
    execution_check = before.get("execution_contract")
    if execution_check == FAIL:
        target = "execution_contract"
    else:
        target = f"{packet.domain}_official_task_pass"
    if target not in before:
        return {"status": "no_authorized_target", "target": target, "before": before}

    controller = TrustController(memory)
    dag = RepairDAG(controller)
    dag.add_root(record["artifacts"]["solve_py"], before)
    execution_diagnostics = dict(execution)
    stderr_path = root_workspace.parent / "execution/stderr.txt"
    if stderr_path.exists():
        execution_diagnostics["stderr_tail"] = stderr_path.read_text(errors="replace")[-4000:]
    if "pyscipopt" in execution_diagnostics.get("stderr_tail", "").lower():
        evidence_api = probe_pyscipopt_api(outdir)
        execution_diagnostics["api_contract"] = evidence_api["stdout"]
    evidence = {
        "target_check": target,
        "execution": execution_diagnostics,
        "witness_verdicts": before,
        "official_errors": (record.get("official", {}).get("evaluation", {}).get("errors") or [])[:20],
    }
    base = outdir / "repair_1"
    artifacts = generate_artifacts(packet, specification, config, base / "generation", run_seed,
                                   repair={"artifacts": record["artifacts"], "evidence": evidence})
    workspace = base / "app"
    prepare_workspace(packet, workspace, artifacts)
    child_execution = execute_solver(workspace, base / "execution")
    child_official = official_evaluate(packet, workspace, base / "official")
    after = evaluate_witness(memory, packet, workspace, child_execution, child_official, base / "after")
    try:
        node = dag.add_repair("root", artifacts["solve_py"], target, before, after, packet.scope)
    except ValueError as exc:
        result = {"status": "duplicate_repair", "error": str(exc), "before": before, "after": after}
        write_json(outdir / "repair_result.json", result)
        return result
    final_accept, final_reasons = controller.final_accept(packet.scope, after)
    metrics = official_metrics(child_official)
    child_record = {**record, "attempt": 1, "artifacts": artifacts, "execution": child_execution,
                    "official": child_official, **metrics, "workspace": str(workspace)}
    result = {"status": "accepted" if node.accepted and final_accept else "rejected",
              "target": target, "before": before, "after": after,
              "edge_accepted": node.accepted, "edge_reasons": node.reasons,
              "final_accept": final_accept, "final_reasons": final_reasons,
              "record": child_record, "dag": dag.to_dict()}
    write_json(outdir / "repair_result.json", result)
    return result

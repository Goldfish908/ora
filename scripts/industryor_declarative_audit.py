#!/usr/bin/env python3
"""Run the zero-LLM IndustryOR declarative-neighborhood audit."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.declarative_neighborhood import DecisionArtifact, RepairResult
from ora_agent.industryor_neighborhood import IndustryORNeighborhood, NotReadyError

DEFAULT_OUT = ROOT / "work/industryor_declarative_audit_v0.1"
DEFAULT_FAILED = ROOT / "work/industryor_structured_dev_v0.2/prob_009/execution_A/solution.json"
IMPLEMENTATION = (
    "ora_agent/industryor_neighborhood.py",
    "ora_agent/declarative_neighborhood.py",
    "scripts/industryor_declarative_audit.py",
    "scripts/industryor_next_stage.py",
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def _artifact_record(artifact: DecisionArtifact | None) -> dict | None:
    return artifact.to_dict() if artifact is not None else None


def _spec_record(result: RepairResult) -> dict | None:
    return result.spec.to_dict() if result.spec is not None else None


def _business_metrics(report: Mapping[str, Any]) -> dict:
    score = report["registered_audit"]
    execution = score.get("execution_checks", {})
    feasible = bool(execution and all(execution.values())
                    and all(row.get("passed") for row in score.get("variable_audit", {}).values())
                    and all(row.get("passed") for row in score.get("constraint_checks", [])))
    return {
        "audit_status": score.get("audit_status"),
        "business_correct": score.get("business_correct") is True,
        "business_feasible": feasible,
        "business_objective": score.get("business_objective"),
        "independent_optimality": score.get("optimality"),
        "model_objective_consistent": score.get("model_objective_consistent") is True,
        "violations": list(score.get("violations", [])),
    }


def repair_root(adapter: IndustryORNeighborhood, raw: bytes, role: str) -> dict:
    started = time.monotonic()
    audits_before = adapter.business_audit_calls
    runs_before = adapter.solver.runs if adapter.solver is not None else 0
    scip_before = adapter.solver.wall_seconds if adapter.solver is not None else 0.0
    try:
        parent = adapter.artifact(raw)
        result = adapter.repair(parent)
    except NotReadyError as exc:
        return {"role": role, "status": "not_ready", "reason": str(exc),
                "business_correct": None, "public_answer_scored": False}
    selected_report = result.candidate_report if result.accepted else result.parent_report
    if selected_report is None or result.selected is None:
        return {"role": role, "status": "not_ready", "reason": "selected artifact lacks a registered audit",
                "business_correct": None, "public_answer_scored": False}
    parent_metrics = _business_metrics(result.parent_report)
    selected_metrics = _business_metrics(selected_report)
    runs_after = adapter.solver.runs if adapter.solver is not None else 0
    scip_after = adapter.solver.wall_seconds if adapter.solver is not None else 0.0
    return {
        "role": role,
        "status": "ready",
        "parent_sha256": result.parent.sha256,
        "selected_sha256": result.selected.sha256,
        "parent": _artifact_record(result.parent),
        "selected": _artifact_record(result.selected),
        "candidate": _artifact_record(result.candidate),
        "parent_report": result.parent_report,
        "candidate_report": result.candidate_report,
        "parent_business": parent_metrics,
        "selected_business": selected_metrics,
        "parent_model_objective": result.parent.decisions["objective"],
        "selected_model_objective": result.selected.decisions["objective"],
        "repair_accepted": result.accepted,
        "repair_reason": result.reason,
        "solve_status": result.solve_status,
        "fixed_violations": list(result.fixed_violations),
        "introduced_violations": list(result.introduced_violations),
        "remaining_violations": list(result.remaining_violations),
        "business_recovered": bool(not parent_metrics["business_correct"]
                                   and selected_metrics["business_correct"] and result.accepted),
        "correct_root_preserved": bool(parent_metrics["business_correct"]
                                       and selected_metrics["business_correct"]
                                       and result.selected.raw_bytes == result.parent.raw_bytes),
        "neighborhood": _spec_record(result),
        "dependency_graph": adapter.graph.to_dict(),
        "dependency_graph_sha256": adapter.graph.sha256,
        "public_answer_used_for_repair": False,
        "public_answer_used_for_selection": False,
        "cost": {
            "llm_calls": 0,
            "llm_tokens": 0,
            "business_audit_calls": adapter.business_audit_calls - audits_before,
            "scip_sub_milp_runs": runs_after - runs_before,
            "scip_wall_seconds": round(scip_after - scip_before, 6),
            "wall_seconds": round(time.monotonic() - started, 6),
        },
    }


def score_public_answer(root_record: dict, en_answer: float) -> None:
    if root_record.get("status") != "ready":
        return
    for stage in ("parent", "selected"):
        model_objective = root_record[f"{stage}_model_objective"]
        business_objective = root_record[f"{stage}_business"]["business_objective"]
        root_record[f"{stage}_public_answer"] = {
            "en_answer": en_answer,
            "reported_model_objective_match_abs_0_1": bool(
                model_objective is not None and abs(model_objective - en_answer) <= 0.1),
            "business_objective_match_abs_0_1": bool(
                isinstance(business_objective, (int, float))
                and abs(business_objective - en_answer) <= 0.1),
        }
    root_record["public_answer_scored"] = True


def _correct_root_path(root: Path, problem_id: int) -> Path:
    manifest = json.loads((root / "assets/industryor_next_stage/manifest.json").read_text())
    entry = next((item for item in manifest.get("problems", []) if item.get("id") == problem_id), None)
    relative = (entry or {}).get("artifacts", {}).get("solution.json")
    if not relative:
        raise NotReadyError("registered correct-control solution path is unavailable")
    return root / relative


def _public_answer(root: Path, problem_id: int) -> float:
    rows = json.loads((root / "data/industryor/IndustryOR.json").read_text())
    row = next((item for item in rows if item.get("id") == problem_id), None)
    try:
        return float(row["en_answer"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NotReadyError("public en_answer is unavailable") from exc


def run_problem(root: Path, problem_id: int, failed_path: Path,
                correct_path: Path | None = None, time_limit: float = 30.0) -> dict:
    started = time.monotonic()
    registered_qualified = False
    try:
        manifest = json.loads((root / "assets/industryor_next_stage/manifest.json").read_text())
        registered_qualified = problem_id in set(
            manifest.get("qualification", {}).get("qualified_ids", []))
    except (OSError, json.JSONDecodeError):
        pass
    try:
        adapter = IndustryORNeighborhood(root, problem_id, time_limit)
        if correct_path is None:
            correct_path = _correct_root_path(root, problem_id)
    except (OSError, json.JSONDecodeError, NotReadyError) as exc:
        return {"id": problem_id, "status": "not_ready", "reason": str(exc),
                "registered_qualified": registered_qualified, "roots": []}
    roots = []
    for role, path in (("narrow_failure", failed_path), ("correct_control", correct_path)):
        try:
            raw = path.read_bytes()
        except OSError as exc:
            roots.append({"role": role, "status": "not_ready", "reason": str(exc),
                          "business_correct": None, "public_answer_scored": False})
            continue
        record = repair_root(adapter, raw, role)
        record["artifact_path"] = str(path.relative_to(root) if path.is_relative_to(root) else path)
        record["artifact_sha256"] = hashlib.sha256(raw).hexdigest()
        roots.append(record)
    try:
        answer = _public_answer(root, problem_id)
        for record in roots:
            score_public_answer(record, answer)
    except NotReadyError as exc:
        for record in roots:
            record["status"] = "not_ready"
            record["reason"] = str(exc)
    ready = bool(roots) and all(record["status"] == "ready" for record in roots)
    return {
        "id": problem_id,
        "status": "ready" if ready else "not_ready",
        "registered_qualified": True,
        "question_sha256": adapter.public.question_sha256,
        "public_semantics": adapter.public.to_dict(),
        "roots": roots,
        "wall_seconds": round(time.monotonic() - started, 6),
    }


def build_report(audit: Mapping[str, Any]) -> str:
    summary = audit["summary"]
    lines = [
        "# IndustryOR 最小声明式邻域审计 v0.1",
        "",
        "本实验只处理具有合格独立业务审计、且具有已核验公开 MILP 适配的注册题。输入是既有 `industryor.solution.v1` 决策制品，不执行原生成代码，不调用 LLM、Gurobi、GEPA 或 memory 资产。",
        "",
        "## 结果",
        "",
        f"- 状态：`{audit['status']}`；注册合格题 {summary['registered_qualified_problems']}，可执行题 {summary['ready_problems']}，`not_ready` 题 {summary['not_ready_problems']}。",
        f"- 窄失败根恢复：{summary['recovered_failure_roots']}/{summary['narrow_failure_roots']}；正确控制根原样保留：{summary['preserved_correct_roots']}/{summary['correct_control_roots']}。",
        "- 业务正确只来自注册独立审计；`business_unverified` 不计入业务正确。公开 `en_answer` 只在修复与选择结束后按绝对误差 0.1 评分。",
        "",
        "| ID | 根 | 父业务正确 | 最终业务正确 | 父独立最优性 | 最终独立最优性 | 父公开目标匹配 | 最终公开目标匹配 | 修复结果 |",
        "|---:|---|---|---|---|---|---|---|---|",
    ]
    for problem in audit["problems"]:
        for record in problem.get("roots", []):
            if record.get("status") != "ready":
                lines.append(f"| {problem['id']} | {record['role']} | not_ready | not_ready | - | - | - | - | {record.get('reason', '')} |")
                continue
            parent = record["parent_business"]
            selected = record["selected_business"]
            lines.append(
                f"| {problem['id']} | {record['role']} | {parent['business_correct']} | {selected['business_correct']} "
                f"| {parent['independent_optimality']} | {selected['independent_optimality']} "
                f"| {record['parent_public_answer']['reported_model_objective_match_abs_0_1']} "
                f"| {record['selected_public_answer']['reported_model_objective_match_abs_0_1']} "
                f"| {record['repair_reason']} |"
            )
    lines.extend([
        "",
        "失败根的公开目标匹配与业务正确是不同结论：即使父制品的目标已匹配，指示变量一致性违规仍使注册业务审计失败。独立最优性也单列，不用公开答案代替最优性证明。",
        "",
        "## 成本",
        "",
        f"- LLM 调用 {summary['llm_calls']}，LLM tokens {summary['llm_tokens']}；SCIP sub-MILP {summary['scip_sub_milp_runs']} 次，SCIP 耗时 {summary['scip_wall_seconds']:.6f}s，总墙钟 {summary['wall_seconds']:.6f}s。",
        f"- 注册业务审计调用 {summary['business_audit_calls']} 次。正确根为空邻域，不调用 SCIP；失败或被拒绝的候选不能替换原正确根。",
        "- 以上仅为本次决策修复的增量成本，不包含既有输入制品的历史 LLM 生成成本，也不与从头生成实验共用成本口径。",
        "",
        "## 限制与 ORAgentBench 可比性",
        "",
        "- 仅实现 ID9 的已核验公开语义；其他注册题没有可靠适配时返回 `not_ready`，没有自动猜题面或制品路径。该适配只接受完整执行审计下的公开约束/定义域窄根，不宣称通用模型诊断、代码修复或任意次优根修复。",
        "- 这是对两个既有决策制品的零 LLM 重放：一个窄失败根、一个正确控制根。样本量不足以估计总体恢复率，也未验证其他变量命名、缺失变量、非最优目标或 blocked 审计。",
        "- **不能与 ORAgentBench 的从头生成结果直接比较。** 此处起点、任务（决策修复而非模型/代码生成）、题数、预算和成本均不同；仅沿用公开目标绝对误差 0.1 与注册业务审计口径。不得据此声称 benchmark 提升或 SOTA。",
        "",
        "机器明细：`work/industryor_declarative_audit_v0.1/audit.json`。",
        "",
    ])
    return "\n".join(lines)


def run(root: Path, ids: list[int], failed_path: Path, correct_path: Path | None,
        out: Path, time_limit: float) -> dict:
    started = time.monotonic()
    problems = [run_problem(root, problem_id, failed_path if problem_id == 9 else
                            root / f"work/industryor_structured_dev_v0.2/prob_{problem_id:03d}/execution_A/solution.json",
                            correct_path if problem_id == 9 else None, time_limit)
                for problem_id in ids]
    roots = [record for problem in problems for record in problem.get("roots", [])]
    ready_roots = [record for record in roots if record.get("status") == "ready"]
    failure_roots = [record for record in ready_roots if record["role"] == "narrow_failure"]
    correct_roots = [record for record in ready_roots if record["role"] == "correct_control"]
    summary = {
        "registered_qualified_problems": sum(problem.get("registered_qualified") is True for problem in problems),
        "ready_problems": sum(problem["status"] == "ready" for problem in problems),
        "not_ready_problems": sum(problem["status"] == "not_ready" for problem in problems),
        "narrow_failure_roots": len(failure_roots),
        "recovered_failure_roots": sum(record["business_recovered"] for record in failure_roots),
        "correct_control_roots": len(correct_roots),
        "preserved_correct_roots": sum(record["correct_root_preserved"] for record in correct_roots),
        "business_unverified_roots": 0,
        "llm_calls": 0,
        "llm_tokens": 0,
        "business_audit_calls": sum(record["cost"]["business_audit_calls"] for record in ready_roots),
        "scip_sub_milp_runs": sum(record["cost"]["scip_sub_milp_runs"] for record in ready_roots),
        "scip_wall_seconds": round(sum(record["cost"]["scip_wall_seconds"] for record in ready_roots), 6),
        "wall_seconds": round(time.monotonic() - started, 6),
    }
    audit = {
        "schema_version": "industryor.declarative_neighborhood_audit.v0.1",
        "status": "ready" if problems and all(problem["status"] == "ready" for problem in problems) else "not_ready",
        "scope": "qualified registered audits only; reviewed public semantics only; decision repair only",
        "config": {
            "ids": ids,
            "failed_root": str(failed_path.relative_to(root) if failed_path.is_relative_to(root) else failed_path),
            "correct_root": str(correct_path.relative_to(root) if correct_path and correct_path.is_relative_to(root)
                                else correct_path) if correct_path else "manifest artifact",
            "scip_time_limit_seconds": time_limit,
            "dataset_sha256": hashlib.sha256((root / "data/industryor/IndustryOR.json").read_bytes()).hexdigest(),
            "manifest_sha256": hashlib.sha256((root / "assets/industryor_next_stage/manifest.json").read_bytes()).hexdigest(),
            "implementation_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                                      for name in IMPLEMENTATION},
        },
        "policy": {
            "business_unverified_counts_as_correct": False,
            "public_answer_used_for_repair_or_selection": False,
            "public_answer_match_abs_tolerance": 0.1,
            "business_audit": "registered score_solution only",
            "solver": "PySCIPOpt SCIP sub-MILP; no Gurobi",
            "llm_calls": 0,
            "gepa_or_memory_assets_read": False,
        },
        "summary": summary,
        "problems": problems,
        "oragentbench": {
            "directly_comparable": False,
            "reason": "single-problem decision-artifact repair has different roots, task, budget and cost from from-scratch benchmark generation",
        },
    }
    _write_json(out / "audit.json", audit)
    (out / "report.md").write_text(build_report(audit))
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--ids", type=int, nargs="+", default=[9])
    parser.add_argument("--failed-root", type=Path, default=DEFAULT_FAILED)
    parser.add_argument("--correct-root", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--time-limit", type=float, default=30.0)
    args = parser.parse_args()
    audit = run(args.root, args.ids, args.failed_root, args.correct_root, args.out, args.time_limit)
    print(json.dumps({"status": audit["status"], "summary": audit["summary"],
                      "audit": str(args.out / "audit.json"), "report": str(args.out / "report.md")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

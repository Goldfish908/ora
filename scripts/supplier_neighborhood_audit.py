#!/usr/bin/env python3
"""Same-root direct-full/declarative/Pareto audit for IndustryOR ID19 and ID21."""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ora_agent.declarative_neighborhood import DecisionArtifact
from ora_agent.supplier_neighborhood import (
    ARMS,
    DECLARATIVE,
    DIRECT_FULL,
    OBJECTIVE_FAILURE_VIOLATIONS,
    PARETO,
    SUPPORTED_IDS,
    NotReadyError,
    SupplierNeighborhood,
    business_feasible,
    solution_from_decisions,
)
from scripts.industryor_next_stage import score_solution

DEFAULT_OUT = ROOT / "work/supplier_neighborhood_audit_v0.1"
TIME_LIMIT_SECONDS = 30.0
ROOT_MANIFEST = {
    "schema_version": "supplier_neighborhood_roots.v0.1",
    "validation_scope": "development_only_not_heldout",
    "use_manifest_default_roots": False,
    "repair_class": "joint_objective_error_and_suboptimality_not_narrow_constraint_repair",
    "problems": [
        {
            "id": 19,
            "roots": [
                {
                    "role": "objective_failure",
                    "path": "work/industryor_next_stage_v0.1/prob_019/solution.json",
                    "sha256": "b4d06bad13ea05feeb4059541a1d4302e228309053dde2f10c9fcaa2e41c9a26",
                    "expected": {
                        "parent_business_correct": False,
                        "parent_feasible": True,
                        "optimality": "suboptimal",
                        "model_objective_consistent": False,
                        "violations": OBJECTIVE_FAILURE_VIOLATIONS,
                        "reported_objective": 365.0,
                        "business_objective": 4650.0,
                        "ordinary_constraint_violation_count": 0,
                    },
                },
                {
                    "role": "correct_control",
                    "path": "work/industryor_structured_dev_v0.2/prob_019/structured_dag/regenerate/solution.json",
                    "sha256": "f5707ce9ef546e39cf5fbd785ef877e83feef29a12f66d7cc31f062e695e6fbf",
                    "expected": {
                        "parent_business_correct": True,
                        "parent_feasible": True,
                        "optimality": "proven_optimal",
                        "model_objective_consistent": True,
                        "violations": [],
                        "reported_objective": 4000.0,
                        "business_objective": 4000.0,
                        "ordinary_constraint_violation_count": 0,
                    },
                },
            ],
        },
        {
            "id": 21,
            "roots": [
                {
                    "role": "objective_failure",
                    "path": "work/industryor_next_stage_v0.1/prob_021/solution.json",
                    "sha256": "4fde21855d35aa0dcf82ed0f1260196910e9dbd6afa54106fc8a8e2a38b0a6f0",
                    "expected": {
                        "parent_business_correct": False,
                        "parent_feasible": True,
                        "optimality": "suboptimal",
                        "model_objective_consistent": False,
                        "violations": OBJECTIVE_FAILURE_VIOLATIONS,
                        "reported_objective": 980.0,
                        "business_objective": 16500.0,
                        "ordinary_constraint_violation_count": 0,
                    },
                },
                {
                    "role": "correct_control",
                    "path": "work/industryor_structured_dev_v0.2/prob_021/execution_A/solution.json",
                    "sha256": "ee4664b24db934a2311cc6cfa9e039add7ea5b4247c7ec7f520d63a8cd7aee21",
                    "expected": {
                        "parent_business_correct": True,
                        "parent_feasible": True,
                        "optimality": "proven_optimal",
                        "model_objective_consistent": True,
                        "violations": [],
                        "reported_objective": 15000.0,
                        "business_objective": 15000.0,
                        "ordinary_constraint_violation_count": 0,
                    },
                },
            ],
        },
    ],
}
IMPLEMENTATION_FILES = (
    "ora_agent/supplier_neighborhood.py",
    "scripts/supplier_neighborhood_audit.py",
    "tests/test_supplier_neighborhood.py",
    "ora_agent/declarative_neighborhood.py",
    "scripts/industryor_next_stage.py",
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _public_answer(root: Path, problem_id: int) -> float:
    rows = json.loads((root / "data/industryor/IndustryOR.json").read_text(encoding="utf-8"))
    row = next((item for item in rows if item.get("id") == problem_id), None)
    try:
        return float(row["en_answer"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NotReadyError(f"public en_answer is unavailable after freeze: {problem_id}") from exc


@dataclass(frozen=True)
class RootCase:
    problem_id: int
    role: str
    path: Path
    raw: bytes
    artifact: DecisionArtifact
    parent_score: dict[str, Any]
    root_spec: dict[str, Any]
    assertions: dict[str, Any]
    preflight_seconds: float


def _root_assertions(artifact: DecisionArtifact, score: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "parent_business_correct": score.get("business_correct") is True,
        "parent_feasible": business_feasible(score),
        "optimality": score.get("optimality"),
        "model_objective_consistent": score.get("model_objective_consistent"),
        "violations": list(score.get("violations", [])),
        "reported_objective": artifact.decisions["objective"],
        "business_objective": score.get("business_objective"),
        "ordinary_constraint_violation_count": sum(
            str(item).startswith("business constraint failed:")
            for item in score.get("violations", [])
        ),
    }


def load_root_cases(root: Path, problem_id: int | None = None) -> list[RootCase]:
    if ROOT_MANIFEST["use_manifest_default_roots"] is not False:
        raise NotReadyError("supplier audit requires explicit root paths")
    ids = SUPPORTED_IDS if problem_id is None else (problem_id,)
    cases = []
    for current_id in ids:
        problem_spec = next(
            (row for row in ROOT_MANIFEST["problems"] if row["id"] == current_id),
            None,
        )
        if problem_spec is None:
            raise NotReadyError(f"no explicit supplier roots for ID{current_id}")
        adapter = SupplierNeighborhood(root, current_id)
        problem_cases = []
        for root_spec in problem_spec["roots"]:
            started = time.perf_counter()
            path = (root / root_spec["path"]).resolve()
            try:
                path.relative_to(root.resolve())
                raw = path.read_bytes()
            except (OSError, ValueError) as exc:
                raise NotReadyError(f"explicit root is unreadable: {root_spec['path']}") from exc
            if _sha256(raw) != root_spec["sha256"]:
                raise NotReadyError(f"explicit root SHA256 differs from manifest: {root_spec['path']}")
            artifact = adapter.artifact(raw, root_spec["sha256"])
            score = adapter.score(artifact)
            assertions = _root_assertions(artifact, score)
            expected = root_spec["expected"]
            mismatches = {
                key: {"expected": value, "actual": assertions.get(key)}
                for key, value in expected.items() if assertions.get(key) != value
            }
            if mismatches:
                raise NotReadyError(
                    f"explicit root assertions failed for ID{current_id}/{root_spec['role']}: "
                    + json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
                )
            if current_id == 19 and root_spec["role"] == "correct_control" \
                    and "execution_A" in path.parts:
                raise NotReadyError("ID19 correct control must not default to execution_A")
            problem_cases.append(RootCase(
                current_id,
                root_spec["role"],
                path,
                raw,
                artifact,
                score,
                copy.deepcopy(root_spec),
                {"passed": True, "actual": assertions, "expected": copy.deepcopy(expected)},
                time.perf_counter() - started,
            ))
        if {case.role for case in problem_cases} != {"objective_failure", "correct_control"}:
            raise NotReadyError(f"ID{current_id} requires one objective failure and one correct control")
        cases.extend(problem_cases)
    return cases


def run_arm(
    root: Path,
    case: RootCase,
    arm: str,
    time_limit: float = TIME_LIMIT_SECONDS,
) -> dict[str, Any]:
    adapter = SupplierNeighborhood(root, case.problem_id, time_limit)
    artifact = adapter.artifact(case.raw, case.artifact.sha256)
    if artifact.raw_bytes != case.raw or artifact.sha256 != case.artifact.sha256:
        raise NotReadyError("arm did not receive the exact explicit root bytes")
    record = adapter.repair(artifact, case.parent_score, arm)
    record.update({
        "problem_id": case.problem_id,
        "root_role": case.role,
        "root_path": _relative(root, case.path),
    })
    if _sha256(case.path.read_bytes()) != case.artifact.sha256:
        raise NotReadyError("input root changed during arm execution")
    return record


def _runtime() -> dict[str, Any]:
    try:
        solver_version = importlib.metadata.version("pyscipopt")
    except importlib.metadata.PackageNotFoundError:
        solver_version = None
    return {
        "python_version": platform.python_version(),
        "pyscipopt_version": solver_version,
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip(),
    }


def _freeze_key(scenario: Mapping[str, Any], arm: str) -> str:
    return f"{scenario['problem_id']}/{scenario['role']}/{arm}"


def generate_selection(
    root: Path,
    ids: Sequence[int] = SUPPORTED_IDS,
    time_limit: float = TIME_LIMIT_SECONDS,
) -> dict[str, Any]:
    started = time.perf_counter()
    ids = tuple(ids)
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("ids must be a nonempty unique sequence")
    scenarios = []
    public_models = {}
    preflight_calls = 0
    for problem_id in ids:
        cases = load_root_cases(root, problem_id)
        preflight_calls += len(cases)
        public_models[str(problem_id)] = SupplierNeighborhood(root, problem_id).public.to_dict()
        for case in cases:
            arms = {
                arm: run_arm(root, case, arm, time_limit)
                for arm in ARMS
            }
            scenarios.append({
                "problem_id": problem_id,
                "role": case.role,
                "artifact_path": _relative(root, case.path),
                "root_sha256": case.artifact.sha256,
                "root_bytes_length": len(case.raw),
                "root_original_artifact": case.artifact.to_dict(),
                "root_original_bytes_verified": _sha256(case.path.read_bytes()) == case.artifact.sha256,
                "root_assertions": case.assertions,
                "parent_independent_audit": case.parent_score,
                "parent_business_feasible": business_feasible(case.parent_score),
                "parent_reported_objective": case.artifact.decisions["objective"],
                "preflight_seconds": case.preflight_seconds,
                "arms_share_exact_root_bytes": all(
                    row["parent_sha256"] == case.artifact.sha256
                    and row["parent_artifact_sha256_matches_original_bytes"]
                    for row in arms.values()
                ),
                "arms": arms,
            })

    frozen = {}
    for scenario in scenarios:
        if _sha256((root / scenario["artifact_path"]).read_bytes()) != scenario["root_sha256"]:
            raise ValueError(f"input root changed while freezing: {_freeze_key(scenario, 'root')}")
        for arm, record in scenario["arms"].items():
            key = _freeze_key(scenario, arm)
            selected = DecisionArtifact.from_dict(record["selected"])
            if selected.sha256 != record["selected_sha256"]:
                raise ValueError(f"selected artifact changed while freezing: {key}")
            frozen[key] = selected.sha256
            record["selection_frozen"] = True

    selection_seconds = time.perf_counter() - started
    return {
        "schema_version": "supplier_neighborhood_audit.v0.1",
        "status": "selection_complete",
        "validation_scope": "development_only_not_heldout",
        "root_manifest": copy.deepcopy(ROOT_MANIFEST),
        "settings": {
            "ids": list(ids),
            "arms": list(ARMS),
            "scip_time_limit_seconds": time_limit,
            "direct_full": "one explicit all-five-variable MILP reoptimization",
            "declarative": "one objective-violation/graph-derived all-five-variable MILP reoptimization",
            "pareto": (
                "same-root archive: objective-bookkeeping-only plus full MILP reoptimization; "
                "Pareto metrics do not replace business-correct eligibility"
            ),
            "correct_control_policy": "no solver, no child candidate, retain exact original bytes",
        },
        "public_models": public_models,
        "policy": {
            "manifest_default_roots_used": False,
            "id19_execution_A_used_as_correct_control": False,
            "repair_scope": "feasible parent with exactly objective inconsistency and independent suboptimality",
            "ordinary_constraint_narrow_repair_claimed": False,
            "business_audit": "scripts.industryor_next_stage.score_solution only",
            "public_answer_used_for_repair_or_selection": False,
            "public_answer_read_before_freeze": False,
            "final_score_solution_audit": "fresh post-freeze calls on frozen selected artifacts",
            "business_unverified_counts_as_correct": False,
            "llm_calls": 0,
            "llm_tokens": 0,
            "generated_code_executed": False,
        },
        "runtime": _runtime(),
        "implementation_sha256": {
            name: _sha256((root / name).read_bytes()) for name in IMPLEMENTATION_FILES
        },
        "registered_manifest_sha256": _sha256(
            (root / "assets/industryor_next_stage/manifest.json").read_bytes()
        ),
        "selection_complete": True,
        "final_independent_audit_complete": False,
        "public_answer_scored": False,
        "public_answer_used_for_candidate_selection": False,
        "frozen_final_sha256": frozen,
        "scenarios": scenarios,
        "selection_cost": {
            "preflight_business_audit_calls": preflight_calls,
            "search_business_audit_calls": sum(
                record["cost"]["business_audit_calls"]
                for scenario in scenarios for record in scenario["arms"].values()
            ),
            "scip_runs": sum(
                record["cost"]["scip_runs"]
                for scenario in scenarios for record in scenario["arms"].values()
            ),
            "scip_wall_seconds": sum(
                record["cost"]["scip_wall_seconds"]
                for scenario in scenarios for record in scenario["arms"].values()
            ),
            "wall_seconds": selection_seconds,
            "llm_calls": 0,
            "llm_tokens": 0,
        },
        "summary": {},
    }


def score_frozen(
    audit: dict[str, Any],
    root: Path,
    answer_loader: Callable[[int], float] | None = None,
    scorer: Callable[[int, Mapping[str, Any]], dict[str, Any]] = score_solution,
) -> dict[str, Any]:
    if not audit.get("selection_complete") or audit.get("public_answer_used_for_candidate_selection"):
        raise ValueError("post-freeze scoring requires completed answer-free selection")
    if audit.get("public_answer_scored"):
        raise ValueError("frozen audit has already been scored")
    expected = {
        _freeze_key(scenario, arm)
        for scenario in audit["scenarios"] for arm in scenario["arms"]
    }
    if set(audit["frozen_final_sha256"]) != expected:
        raise ValueError("frozen final manifest does not exactly cover every selected arm")

    selected_solutions = {}
    for scenario in audit["scenarios"]:
        if _sha256((root / scenario["artifact_path"]).read_bytes()) != scenario["root_sha256"]:
            raise ValueError(f"input root changed before final scoring: {scenario['artifact_path']}")
        for arm, record in scenario["arms"].items():
            key = _freeze_key(scenario, arm)
            try:
                raw = base64.b64decode(record["selected"]["raw_bytes_base64"], validate=True)
            except Exception as exc:
                raise ValueError(f"frozen final changed before independent scoring: {key}") from exc
            if _sha256(raw) != audit["frozen_final_sha256"][key] \
                    or _sha256(raw) != record["selected_sha256"]:
                raise ValueError(f"frozen final changed before independent scoring: {key}")
            try:
                artifact = DecisionArtifact.from_dict(record["selected"])
                decoded = json.loads(raw)
                if set(decoded) == {"variables", "objective", "state"}:
                    decisions_match = decoded == artifact.decisions
                else:
                    decisions_match = decoded == solution_from_decisions(artifact.decisions)
            except Exception as exc:
                raise ValueError(f"frozen final changed before independent scoring: {key}") from exc
            if not decisions_match:
                raise ValueError(f"frozen final changed before independent scoring: {key}")
            selected_solutions[key] = solution_from_decisions(artifact.decisions)

    for scenario in audit["scenarios"]:
        for arm, record in scenario["arms"].items():
            key = _freeze_key(scenario, arm)
            started = time.perf_counter()
            score = scorer(scenario["problem_id"], selected_solutions[key])
            elapsed = time.perf_counter() - started
            if score.get("audit_status") != "complete":
                raise ValueError(f"independent final audit is incomplete: {key}")
            record["final_independent_audit"] = score
            record["final_independent_audit_seconds"] = elapsed
            record["total_cost_seconds_including_final_audit"] = (
                record["cost"]["wall_seconds"] + elapsed
            )
            record["business_recovered"] = bool(
                scenario["role"] == "objective_failure"
                and scenario["parent_independent_audit"]["business_correct"] is False
                and score.get("business_correct") is True
                and record["selected_sha256"] != scenario["root_sha256"]
            )
            if scenario["role"] == "correct_control":
                record["correct_root_preserved"] = bool(
                    record["selected_sha256"] == scenario["root_sha256"]
                    and record["selected"]["raw_bytes_base64"]
                    == scenario["root_original_artifact"]["raw_bytes_base64"]
                    and score.get("business_correct") is True
                )
    audit["final_independent_audit_complete"] = True

    answer_started = time.perf_counter()
    loader = (lambda problem_id: _public_answer(root, problem_id)) \
        if answer_loader is None else answer_loader
    answers = {}
    for problem_id in sorted({scenario["problem_id"] for scenario in audit["scenarios"]}):
        answer = float(loader(problem_id))
        answers[str(problem_id)] = {
            "en_answer": answer,
            "abs_tolerance": 0.1,
            "attached_after_freeze": True,
            "attached_after_final_independent_audit": True,
        }
    for scenario in audit["scenarios"]:
        answer = answers[str(scenario["problem_id"])]["en_answer"]
        for record in scenario["arms"].values():
            score = record["final_independent_audit"]
            solution = selected_solutions[_freeze_key(scenario, record["arm"])]
            business_objective = score.get("business_objective")
            record["public_answer"] = {
                "en_answer": answer,
                "reported_model_objective_match_abs_0_1": abs(float(solution["objective"]) - answer) <= 0.1,
                "business_objective_match_abs_0_1": bool(
                    isinstance(business_objective, (int, float))
                    and abs(business_objective - answer) <= 0.1
                ),
                "scored_after_freeze": True,
                "scored_after_final_independent_audit": True,
            }
            record["public_answer_scored"] = True
    audit["post_freeze_public_answer"] = answers
    audit["public_answer_scoring_seconds"] = time.perf_counter() - answer_started
    audit["public_answer_scored"] = True
    _refresh_summary(audit)
    audit["status"] = "ready" if (
        audit["summary"]["not_ready_problems"] == 0
        and audit["summary"]["failure_arm_recoveries"] == audit["summary"]["failure_arm_runs"]
        and audit["summary"]["correct_control_original_bytes_preserved"]
        == audit["summary"]["correct_control_arm_runs"]
    ) else "not_ready"
    return audit


def _refresh_summary(audit: dict[str, Any]) -> None:
    scenarios = audit["scenarios"]
    failure_scenarios = [row for row in scenarios if row["role"] == "objective_failure"]
    control_scenarios = [row for row in scenarios if row["role"] == "correct_control"]
    failure_records = [row["arms"][arm] for row in failure_scenarios for arm in ARMS]
    control_records = [row["arms"][arm] for row in control_scenarios for arm in ARMS]
    all_records = failure_records + control_records
    candidates = [candidate for row in all_records for candidate in row["candidate_lineage"]]
    bookkeeping = [row for row in candidates if row["operation"] == "objective_bookkeeping_only"]
    not_ready_problems = 0
    for problem_id in sorted({row["problem_id"] for row in scenarios}):
        records = [
            row["arms"][arm] for row in scenarios if row["problem_id"] == problem_id for arm in ARMS
        ]
        if any(row["status"] != "ready" for row in records) \
                or any(row["final_independent_audit"].get("business_correct") is not True for row in records):
            not_ready_problems += 1
    audit["summary"] = {
        "problems": len({row["problem_id"] for row in scenarios}),
        "ready_problems": len({row["problem_id"] for row in scenarios}) - not_ready_problems,
        "not_ready_problems": not_ready_problems,
        "objective_failure_roots": len(failure_scenarios),
        "correct_control_roots": len(control_scenarios),
        "failure_arm_runs": len(failure_records),
        "failure_arm_recoveries": sum(row["business_recovered"] for row in failure_records),
        "correct_control_arm_runs": len(control_records),
        "correct_control_original_bytes_preserved": sum(
            row["correct_root_preserved"] is True for row in control_records
        ),
        "failure_business_correct_by_arm": {
            arm: [row["arms"][arm]["business_recovered"] for row in failure_scenarios]
            for arm in ARMS
        },
        "objective_bookkeeping_candidates": len(bookkeeping),
        "objective_bookkeeping_business_correct": sum(
            row["independent_audit"]["business_correct"] is True for row in bookkeeping
        ),
        "objective_bookkeeping_still_suboptimal": sum(
            row["independent_audit"]["optimality"] == "suboptimal" for row in bookkeeping
        ),
        "preflight_business_audit_calls": audit["selection_cost"]["preflight_business_audit_calls"],
        "search_business_audit_calls": audit["selection_cost"]["search_business_audit_calls"],
        "post_freeze_business_audit_calls": len(all_records),
        "business_audit_calls": (
            audit["selection_cost"]["preflight_business_audit_calls"]
            + audit["selection_cost"]["search_business_audit_calls"] + len(all_records)
        ),
        "scip_runs": audit["selection_cost"]["scip_runs"],
        "scip_wall_seconds": audit["selection_cost"]["scip_wall_seconds"],
        "selection_wall_seconds": audit["selection_cost"]["wall_seconds"],
        "post_freeze_independent_audit_seconds": sum(
            row["final_independent_audit_seconds"] for row in all_records
        ),
        "llm_calls": 0,
        "llm_tokens": 0,
        "manifest_default_roots_used": False,
        "validation_scope": "development_only_not_heldout",
    }


def _number(value: Any) -> str:
    return "NA" if value is None else f"{float(value):.6f}"


def build_report(audit: Mapping[str, Any]) -> str:
    summary = audit["summary"]
    lines = [
        "# IndustryOR ID19/21 供应商订单 MILP 目标修复审计 v0.1",
        "",
        "本实验是 **development validation，非 heldout**。四个显式根均来自既有开发制品；只评价公开 MILP 与独立 `score_solution`，不执行原生成代码，不调用 LLM，也不用于宣称 benchmark/SOTA 提升。",
        "",
        "## 公开模型与失败定性",
        "",
        "- `x_A,x_B,x_C` 为非负整数订单数，`y_A,y_B` 为 binary；`Q=q_A*x_A+q_B*x_B+q_C*x_C`，并施加 `L<=Q<=U`、`y_A<=x_A<=M_A*y_A`、`y_B<=x_B<=M_B*y_B`、`x_B>=k*y_A` 和 `x_C>=y_B`。",
        "- 目标严格为 `sum_s c_s*q_s*x_s`：每件成本 × 每单件数 × 订单数。ID19 的每单成本系数为 `(750,450,400)`，ID21 为 `(2400,1650,1500)`；没有使用漏乘 `q` 的 `(50,45,40)` 或 `(120,110,100)`。",
        "- 两个失败根都通过执行、定义域与全部公开约束，却同时具有报告目标不一致和独立次优。因此本次是联合目标公式/次优修复，**不是普通约束窄修复**，也不声称能修复任意约束错误。",
        "",
        "| ID | 根 | 显式路径 | SHA256 | 父报告目标 | 父独立成本 | 父业务正确 | 父最优性 |",
        "|---:|---|---|---|---:|---:|---|---|",
    ]
    for scenario in audit["scenarios"]:
        parent = scenario["parent_independent_audit"]
        lines.append(
            f"| {scenario['problem_id']} | {scenario['role']} | `{scenario['artifact_path']}` "
            f"| `{scenario['root_sha256']}` | {_number(scenario['parent_reported_objective'])} "
            f"| {_number(parent['business_objective'])} | {parent['business_correct']} | {parent['optimality']} |"
        )
    lines.extend([
        "",
        "ID19 正确控制明确使用 `structured_dag/regenerate/solution.json`，没有默认到 `execution_A`。每个根的原始字节以 base64 与 SHA256 一同保存在 `audit.json`，并在运行前后复核。",
        "",
        "## 同根三臂结果",
        "",
        "`direct-full` 显式释放全部五变量；`declarative` 从两个目标违规键及全局 Q/目标依赖图释放全部五变量，二者均无固定变量。`pareto` 另构造仅改目标字段的账面候选，以违规数、独立成本和改变变量数构成 Pareto 指标，但只有独立业务正确候选才可入选。",
        "",
        "| ID | 根 | 臂 | 父独立成本 | 最终独立成本 | 最终业务正确 | 最终最优性 | SCIP | 改变变量数 | en_answer 匹配 |",
        "|---:|---|---|---:|---:|---|---|---:|---:|---|",
    ])
    for scenario in audit["scenarios"]:
        for arm in ARMS:
            record = scenario["arms"][arm]
            final = record["final_independent_audit"]
            selected = DecisionArtifact.from_dict(record["selected"])
            root = DecisionArtifact.from_dict(scenario["root_original_artifact"])
            changed = sum(
                selected.decisions["variables"][name] != root.decisions["variables"][name]
                for name in selected.decisions["variables"]
            )
            lines.append(
                f"| {scenario['problem_id']} | {scenario['role']} | {arm} "
                f"| {_number(scenario['parent_independent_audit']['business_objective'])} "
                f"| {_number(final['business_objective'])} | {final['business_correct']} "
                f"| {final['optimality']} | {record['cost']['scip_runs']} | {changed} "
                f"| {record['public_answer']['business_objective_match_abs_0_1']} |"
            )
    lines.extend([
        "",
        f"失败根恢复为 **{summary['failure_arm_recoveries']}/{summary['failure_arm_runs']} 个 failure-arm**；正确控制原字节保留为 **{summary['correct_control_original_bytes_preserved']}/{summary['correct_control_arm_runs']} 个 control-arm**。正确控制均为零求解、零 child candidate。",
        "",
        "## Pareto 判别与血缘",
        "",
        f"- `pareto` 共产生 {summary['objective_bookkeeping_candidates']} 个仅账面修正候选，其中 {summary['objective_bookkeeping_still_suboptimal']} 个仍为 `suboptimal`，业务正确数为 {summary['objective_bookkeeping_business_correct']}；它们虽减少改变字段且可能位于 Pareto front，但均被拒绝，不计恢复。",
        "- 完整重优化候选在两题均收敛到 `x_A=x_B=y_A=y_B=0,x_C=10`，独立成本分别为 4000 和 15000。账面候选与完整候选可因改变变量数不同而互不支配；Pareto 身份本身不等于业务正确。",
        "- `audit.json` 对每个候选保存 `parent_candidate_id`、`parent_sha256`、candidate SHA256、operation、完整 spec、图 hash、原始/候选字节、独立审计、接受/拒绝原因和逐项成本；最终选择另有冻结 hash 清单。",
        "",
        "## 成本",
        "",
        f"- LLM 调用 {summary['llm_calls']}、tokens {summary['llm_tokens']}；真实 SCIP 共 {summary['scip_runs']} 次，求解耗时 {summary['scip_wall_seconds']:.6f}s。",
        f"- 独立审计调用：根预检 {summary['preflight_business_audit_calls']}，搜索/接受 {summary['search_business_audit_calls']}，冻结后新鲜复评 {summary['post_freeze_business_audit_calls']}，合计 {summary['business_audit_calls']}。选择墙钟 {summary['selection_wall_seconds']:.6f}s，冻结后审计 {summary['post_freeze_independent_audit_seconds']:.6f}s。",
        "- 这是本次决策修复的增量成本，不含输入制品的历史生成成本；墙钟与 SCIP 求解时间是不同口径，不相加冒充求解次数。",
        "",
        "## 冻结、答案与 not_ready 边界",
        "",
        "- 所有选择与 SHA256 冻结完成后，才对冻结制品重新调用独立 `score_solution`；全部最终审计完成后才读取并附加 `en_answer`，绝对误差口径为 0.1。公开答案不参与修复、Pareto 构造或选择。",
        "- 仅支持 ID19/21、注册 question hash、精确五变量及 INTEGER/BINARY 声明、完整独立审计，以及“父完全可行且恰好目标不一致+独立次优”的失败形态；正确根仅做保留。",
        "- 缺失 PySCIPOpt、无候选、非 optimal/完整导出、额外约束/定义域/执行错误、未知审计、根路径或 hash 不符、冻结字节变化均为 `not_ready` 或直接失败关闭；不把 `business_unverified` 计为正确，也不回退到默认根。",
        "- 两题、各一个失败根和一个正确根的开发验证不能估计跨题恢复率或 heldout 泛化；direct-full、declarative 与 Pareto 在这些根上的相同恢复不证明某臂普遍更优。",
        "",
        "机器明细：`work/supplier_neighborhood_audit_v0.1/audit.json`。",
        "",
    ])
    return "\n".join(lines)


def run(
    root: Path,
    out: Path,
    ids: Sequence[int] = SUPPORTED_IDS,
    time_limit: float = TIME_LIMIT_SECONDS,
) -> dict[str, Any]:
    audit = generate_selection(root, ids=ids, time_limit=time_limit)
    score_frozen(audit, root)
    _write_json(out / "audit.json", audit)
    (out / "report.md").write_text(build_report(audit), encoding="utf-8")
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--ids", type=int, nargs="+", default=list(SUPPORTED_IDS))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--time-limit", type=float, default=TIME_LIMIT_SECONDS)
    args = parser.parse_args()
    audit = run(args.root, args.out, ids=args.ids, time_limit=args.time_limit)
    print(json.dumps({
        "status": audit["status"],
        "summary": audit["summary"],
        "audit": str(args.out / "audit.json"),
        "report": str(args.out / "report.md"),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

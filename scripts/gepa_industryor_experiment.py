#!/usr/bin/env python3
"""Same-root GEPA-inspired mechanism validation for IndustryOR ID20."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import platform
import random
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ora_agent.declarative_neighborhood import (
    DECISION_REPAIR,
    OBJECTIVE_OPTIMIZATION,
    DecisionArtifact,
    EmptyNeighborhoodError,
    NeighborhoodSpec,
    build_neighborhood,
    repair_neighborhood,
)
from ora_agent.gepa_repair import (
    DEFAULT_OPERATION,
    DIRECT_FULL_REOPTIMIZATION,
    FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION,
    GEPA_SRC,
)
from ora_agent.industryor_neighborhood import (
    SOLUTION_SCHEMA,
    IndustryORNeighborhood,
    NotReadyError,
    solution_from_decisions,
)
from ora_agent.population_repair import (
    FEASIBLE,
    INFEASIBLE,
    UNKNOWN,
    BusinessResult,
    Candidate,
    Evaluation,
    Mutation,
    PopulationRepairController,
    RepairRun,
)
from scripts.gepa_federated_experiment import (
    CandidateBridge,
    GepaSearchResult,
    run_gepa_search,
    summarize_search,
)
from scripts.industryor_next_stage import score_solution

DIRECT_FULL = "direct-full"
DECLARATIVE = "declarative"
SINGLE = "single"
OLD_POPULATION = "old-population"
PARETO_ONLY = "pareto-only"
PARETO_MERGE = "pareto+compatible+merge"
PRIMARY_ARMS = (DIRECT_FULL, DECLARATIVE, SINGLE, OLD_POPULATION, PARETO_ONLY)
ARMS = (*PRIMARY_ARMS, PARETO_MERGE)
OPERATIONS = (
    DEFAULT_OPERATION,
    DIRECT_FULL_REOPTIMIZATION,
    FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION,
)
EVALUATION_BUDGET = 6
K = 3
DEPTH = 2
SEED = 20261123
TIME_LIMIT_SECONDS = 30.0
DEFAULT_OUT = ROOT / "work/gepa_industryor_id20_v0.1"
ROOT_MANIFEST = {
    "schema_version": "gepa_industryor_id20_roots.v0.1",
    "problem_id": 20,
    "validation_scope": "development_only_not_heldout",
    "use_manifest_default_roots": False,
    "roots": [
        {
            "role": "narrow_failure",
            "path": "work/industryor_structured_dev_v0.2/prob_020/execution_A/solution.json",
            "expected_parent_business_correct": False,
            "expected_violations": [
                "business constraint failed: cars_imply_blocks",
                "business constraint failed: link_x3_y3",
                "business constraint failed: link_x4_y4",
            ],
        },
        {
            "role": "correct_control",
            "path": "work/industryor_structured_dev_v0.2/prob_020/structured_dag/local/solution.json",
            "expected_parent_business_correct": True,
            "expected_violations": [],
            "expected_optimality": "proven_optimal",
        },
    ],
}
IMPLEMENTATION_FILES = (
    "ora_agent/industryor_neighborhood.py",
    "ora_agent/declarative_neighborhood.py",
    "ora_agent/population_repair.py",
    "ora_agent/gepa_repair.py",
    "scripts/industryor_next_stage.py",
    "scripts/federated_population_audit.py",
    "scripts/gepa_federated_experiment.py",
    "scripts/gepa_industryor_experiment.py",
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")


def _digest_json(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(raw)


def _business_from_public(report: Mapping[str, Any], extra_errors: Sequence[str] = ()) -> BusinessResult:
    mapped = {"pass": FEASIBLE, "fail": INFEASIBLE}.get(str(report.get("business_status", "unknown")).lower(), UNKNOWN)
    violations = report.get("violations") or []
    keys = [str(row["key"]) for row in violations]
    objective = report.get("objective") if mapped != UNKNOWN else None
    return BusinessResult(
        status=mapped,
        objective=objective,
        sense="max",
        violation_count=len(violations),
        violation_score=float(len(violations)),
        hard_errors=frozenset(keys).union(str(error) for error in extra_errors),
    )


def _public_answer(root: Path) -> float:
    rows = json.loads((root / "data/industryor/IndustryOR.json").read_text(encoding="utf-8"))
    row = next((item for item in rows if item.get("id") == 20), None)
    try:
        return float(row["en_answer"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NotReadyError("public en_answer is unavailable") from exc


class PublicChecker:
    def __init__(self, adapter: IndustryORNeighborhood) -> None:
        self.adapter = adapter
        self.cache: dict[str, dict[str, Any]] = {}
        self.cache_hits = 0

    def check(self, decisions: Mapping[str, Any]) -> dict[str, Any]:
        key = _digest_json(decisions)
        if key in self.cache:
            self.cache_hits += 1
            return copy.deepcopy(self.cache[key])
        report = self.adapter.business_report(decisions)
        self.cache[key] = copy.deepcopy(report)
        return report


@dataclass(frozen=True)
class RootCase:
    role: str
    path: Path
    raw: bytes
    artifact: DecisionArtifact
    parent_report: dict[str, Any]
    preflight_seconds: float


@dataclass(frozen=True)
class ArmResult:
    value: RepairRun | GepaSearchResult
    bridge: CandidateBridge
    adapter: IndustryORNeighborhood
    checker: PublicChecker
    summary: dict[str, Any]

    @property
    def run(self) -> RepairRun:
        return self.value.run if isinstance(self.value, GepaSearchResult) else self.value


def load_root_cases(root: Path) -> list[RootCase]:
    if ROOT_MANIFEST["use_manifest_default_roots"] is not False:
        raise NotReadyError("ID20 requires explicit root paths")
    adapter = IndustryORNeighborhood(root, 20)
    cases = []
    for spec in ROOT_MANIFEST["roots"]:
        started = time.perf_counter()
        path = (root / spec["path"]).resolve()
        raw = path.read_bytes()
        artifact = adapter.artifact(raw)
        report = adapter.business_report(artifact.decisions)
        score = report.get("registered_audit", {})
        actual = score.get("business_correct")
        if actual is not spec["expected_parent_business_correct"]:
            raise NotReadyError(f"explicit root parent verdict differs from its manifest: {spec['role']}")
        if score.get("violations") != spec["expected_violations"]:
            raise NotReadyError(f"explicit root violations differ from its manifest: {spec['role']}")
        expected_optimality = spec.get("expected_optimality")
        if expected_optimality is not None and score.get("optimality") != expected_optimality:
            raise NotReadyError(f"explicit root optimality differs from its manifest: {spec['role']}")
        cases.append(RootCase(
            role=spec["role"], path=path, raw=raw, artifact=artifact,
            parent_report=report, preflight_seconds=time.perf_counter() - started,
        ))
    if {case.role for case in cases} != {"narrow_failure", "correct_control"}:
        raise NotReadyError("ID20 requires one failure root and one correct control")
    return cases


def make_initial(artifact: DecisionArtifact, checker: PublicChecker, candidate_id: str) -> Candidate:
    started = time.perf_counter()
    report = checker.check(artifact.decisions)
    return Candidate.seed(
        {"artifact_sha256": artifact.sha256, "root": True},
        Evaluation(
            {"source": "explicit_root", "public_status": report["business_status"]},
            _business_from_public(report),
            cost=time.perf_counter() - started,
            checkpoint=artifact,
            structure=artifact.sha256,
        ),
        id=candidate_id,
    )


def _variable_names(artifact: DecisionArtifact) -> tuple[str, ...]:
    return tuple(f"variables.{name}" for name in artifact.decisions["variables"])


def _positive_variables(artifact: DecisionArtifact) -> tuple[str, ...]:
    return tuple(
        f"variables.{name}" for name, value in artifact.decisions["variables"].items()
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
    )


def _spec_signature(spec: NeighborhoodSpec) -> dict[str, Any]:
    return {
        "mode": spec.mode,
        "released_variable_count": len(spec.released_variables),
        "fixed_variable_count": len(spec.fixed_variables),
        "released_variables": list(spec.released_variables),
        "released_variables_sha256": _digest_json(list(spec.released_variables)),
        "violation_keys_sha256": _digest_json(list(spec.violation_keys)),
    }


def _payload(parent: Candidate, operation: str, seed_scope: str,
             spec: NeighborhoodSpec | None = None, unavailable: str | None = None) -> dict[str, Any]:
    payload = {
        "operation": operation,
        "parent_sha256": parent.checkpoint.sha256,
        "seed_scope": seed_scope,
    }
    if spec is not None:
        payload["spec_signature"] = _spec_signature(spec)
    if unavailable is not None:
        payload["unavailable"] = unavailable
    return payload


def _propose(parent: Candidate, adapter: IndustryORNeighborhood,
             checker: PublicChecker, operation: str, seed_scope: str) -> Mutation:
    started = time.perf_counter()
    artifact = parent.checkpoint
    try:
        report = checker.check(artifact.decisions)
        if operation == DEFAULT_OPERATION:
            seeds: Sequence[str] = ()
            mode = DECISION_REPAIR
        elif operation == DIRECT_FULL_REOPTIMIZATION:
            seeds = _variable_names(artifact)
            mode = DECISION_REPAIR if report["business_status"] != "pass" else OBJECTIVE_OPTIMIZATION
        elif operation == FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION:
            seeds = _positive_variables(artifact)
            mode = OBJECTIVE_OPTIMIZATION
        else:
            raise ValueError(f"unsupported operation: {operation}")
        spec = build_neighborhood(
            artifact,
            report["violations"],
            adapter.graph,
            variable_names=_variable_names(artifact),
            seed_variables=seeds,
            mode=mode,
            objective_sense="maximize",
        )
        payload = _payload(parent, operation, seed_scope, spec=spec)
    except EmptyNeighborhoodError:
        payload = _payload(parent, operation, seed_scope, unavailable="empty_neighborhood")
    return Mutation(operation, payload, cost=time.perf_counter() - started)


def make_operators(adapter: IndustryORNeighborhood, checker: PublicChecker):
    scopes = {
        DEFAULT_OPERATION: "violations_and_one_hop",
        DIRECT_FULL_REOPTIMIZATION: "all_variables",
        FEASIBLE_PARENT_OBJECTIVE_OPTIMIZATION: "positive_variables_and_one_hop",
    }
    return [
        lambda parent, operation=operation, scope=scopes[operation]: _propose(
            parent, adapter, checker, operation, scope,
        )
        for operation in OPERATIONS
    ]


def _seeds(mutation: Mutation, artifact: DecisionArtifact) -> Sequence[str]:
    scope = mutation.payload["seed_scope"]
    if scope == "violations_and_one_hop":
        return ()
    if scope == "all_variables":
        return _variable_names(artifact)
    if scope == "positive_variables_and_one_hop":
        return _positive_variables(artifact)
    raise ValueError(f"unsupported seed scope: {scope}")


def evaluate_mutation(mutation: Mutation, parent: Candidate,
                      adapter: IndustryORNeighborhood, checker: PublicChecker) -> Evaluation:
    started = time.perf_counter()
    artifact = parent.checkpoint
    if mutation.payload.get("parent_sha256") != artifact.sha256:
        raise ValueError("mutation parent hash does not match the supplied parent")
    if "unavailable" in mutation.payload:
        reason = mutation.payload["unavailable"]
        return Evaluation(
            {"repair_accepted": False, "repair_reason": reason, "solver": {}, "candidate_violations": []},
            BusinessResult(UNKNOWN, sense="max", hard_errors={reason}),
            cost=time.perf_counter() - started,
            checkpoint=artifact,
            structure=artifact.sha256,
        )

    raw_outcome: dict[str, Any] = {}
    mode = mutation.payload["spec_signature"]["mode"]
    seeds = _seeds(mutation, artifact)

    def solve(spec: NeighborhoodSpec):
        if spec.parent_sha256 != mutation.payload["parent_sha256"]:
            raise ValueError("rebuilt neighborhood parent hash mismatch")
        if _spec_signature(spec) != mutation.payload["spec_signature"]:
            raise ValueError("rebuilt neighborhood signature mismatch")
        solve_started = time.perf_counter()
        outcome = adapter._get_solver()(spec)
        raw_outcome.update(outcome)
        raw_outcome["solve_seconds"] = time.perf_counter() - solve_started
        raw_outcome["solver_status"] = outcome.get("status")
        raw_outcome["released_variable_count"] = len(spec.released_variables)
        raw_outcome["fixed_variable_count"] = len(spec.fixed_variables)
        return outcome

    try:
        result = repair_neighborhood(
            artifact,
            adapter.graph,
            checker.check,
            solve,
            variable_names=_variable_names(artifact),
            seed_variables=seeds,
            mode=mode,
            objective_sense="maximize",
        )
    except Exception as exc:
        reason = f"evaluator_error:{type(exc).__name__}"
        return Evaluation(
            {"repair_accepted": False, "repair_reason": reason,
             "solver": dict(raw_outcome), "candidate_violations": []},
            BusinessResult(UNKNOWN, sense="max", hard_errors={reason}),
            cost=time.perf_counter() - started,
            checkpoint=artifact,
            structure=artifact.sha256,
        )

    solver_keys = (
        "status", "solver_status", "solve_seconds", "released_variable_count", "fixed_variable_count",
    )
    execution = {
        "repair_accepted": result.accepted,
        "repair_reason": result.reason,
        "solve_status": result.solve_status,
        "introduced_violations": list(result.introduced_violations),
        "fixed_violations": list(result.fixed_violations),
        "remaining_violations": list(result.remaining_violations),
        "solver": {key: raw_outcome[key] for key in solver_keys if key in raw_outcome},
        "candidate_violations": [],
    }
    if result.candidate is None or result.candidate_report is None:
        business = BusinessResult(UNKNOWN, sense="max", hard_errors={f"no_candidate:{result.reason}"})
        selected = artifact
        structure = artifact.sha256
    else:
        selected = result.candidate
        business = _business_from_public(result.candidate_report)
        structure = selected.sha256
        execution["candidate_sha256"] = selected.sha256
        execution["candidate_public_status"] = result.candidate_report["business_status"]
        execution["candidate_public_objective"] = result.candidate_report["objective"]
        execution["candidate_violations"] = copy.deepcopy(result.candidate_report["violations"])
    return Evaluation(
        execution,
        business,
        cost=time.perf_counter() - started,
        checkpoint=selected,
        structure=structure,
    )


def run_arm(root: Path, case: RootCase, arm: str, time_limit: float = TIME_LIMIT_SECONDS) -> ArmResult:
    if arm not in ARMS:
        raise ValueError(f"unsupported arm: {arm}")
    started = time.perf_counter()
    adapter = IndustryORNeighborhood(root, 20, time_limit)
    artifact = adapter.artifact(case.raw, case.artifact.sha256)
    checker = PublicChecker(adapter)
    initial = make_initial(artifact, checker, f"{case.role}/{arm}/root")
    operators = make_operators(adapter, checker)

    def evaluator(mutation: Mutation, parent: Candidate) -> Evaluation:
        return evaluate_mutation(mutation, parent, adapter, checker)

    objective_scale = max(1.0, abs(float(initial.business_result.objective or 0.0)))
    bridge = CandidateBridge(objective_scale=objective_scale, checker=checker)
    if arm in {DIRECT_FULL, DECLARATIVE}:
        operation = DIRECT_FULL_REOPTIMIZATION if arm == DIRECT_FULL else DEFAULT_OPERATION
        value: RepairRun | GepaSearchResult = PopulationRepairController(
            k=1, depth=1, evaluation_budget=EVALUATION_BUDGET,
        ).run(
            initial, evaluator, [operators[OPERATIONS.index(operation)]], allow_exploration=True,
        )
    elif arm == SINGLE:
        value = PopulationRepairController(k=K, depth=DEPTH, evaluation_budget=EVALUATION_BUDGET).run(
            initial, evaluator, operators, single_chain=True, allow_exploration=True,
        )
    elif arm == OLD_POPULATION:
        value = PopulationRepairController(k=K, depth=DEPTH, evaluation_budget=EVALUATION_BUDGET).run(
            initial, evaluator, operators, allow_exploration=True,
        )
    else:
        value = run_gepa_search(
            initial,
            evaluator,
            operators,
            bridge,
            merge_enabled=arm == PARETO_MERGE,
            seed=SEED,
            k=K,
            depth=DEPTH,
            evaluation_budget=EVALUATION_BUDGET,
        )
    run = value.run if isinstance(value, GepaSearchResult) else value
    if run.initial.checkpoint.sha256 != case.artifact.sha256 or run.initial.checkpoint.raw_bytes != case.raw:
        raise AssertionError(f"{case.role}/{arm} changed the explicit root")
    if run.evaluations > EVALUATION_BUDGET:
        raise AssertionError(f"{case.role}/{arm} exceeded the common evaluation budget")
    if arm in {DIRECT_FULL, DECLARATIVE} and run.evaluations != 1:
        raise AssertionError(f"{case.role}/{arm} must execute exactly one operation")
    if arm == DIRECT_FULL:
        direct = run.candidates[1]
        if direct.payload.get("spec_signature", {}).get("released_variable_count") != len(adapter.public.domains):
            raise AssertionError("direct-full did not release every reviewed variable")
    if case.role == "correct_control" and run.best.checkpoint.raw_bytes != case.raw:
        raise AssertionError("correct control did not preserve its original bytes")

    summary = summarize_search(value, bridge, arm)
    by_id = {candidate.id: candidate for candidate in run.candidates}
    for row in summary["candidates"]:
        candidate = by_id[row["id"]]
        row["violations"] = copy.deepcopy(candidate.execution_result.get("candidate_violations", []))
    summary.update({
        "arm": arm,
        "mode": arm,
        "root_role": case.role,
        "root_sha256": case.artifact.sha256,
        "evaluation_budget": EVALUATION_BUDGET,
        "public_answer_scored": False,
        "public_answer": None,
        "final_independent_audit": None,
        "correct_root_original_bytes_preserved": (
            run.best.checkpoint.raw_bytes == case.raw if case.role == "correct_control" else None
        ),
        "adapter_counters": {
            "business_audit_calls": adapter.business_audit_calls,
            "public_check_cache_hits": checker.cache_hits,
            "scip_sub_milp_runs": adapter.solver.runs if adapter.solver is not None else 0,
            "scip_wall_seconds": adapter.solver.wall_seconds if adapter.solver is not None else 0.0,
        },
        "arm_wall_seconds": time.perf_counter() - started,
    })
    if summary["adapter_counters"]["scip_sub_milp_runs"] != summary["solver_call_count"]:
        raise AssertionError(f"{case.role}/{arm} solver cost counters disagree")
    return ArmResult(value, bridge, adapter, checker, summary)


def _runtime() -> dict[str, Any]:
    try:
        solver_version = importlib.metadata.version("pyscipopt")
    except importlib.metadata.PackageNotFoundError:
        solver_version = None
    return {
        "python_version": platform.python_version(),
        "pyscipopt_version": solver_version,
        "gepa_src": str(GEPA_SRC),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    }


def generate_selection(root: Path, out: Path, time_limit: float = TIME_LIMIT_SECONDS) -> dict[str, Any]:
    started = time.perf_counter()
    cases = load_root_cases(root)
    adapter = IndustryORNeighborhood(root, 20, time_limit)
    scenarios = []
    results_by_role: dict[str, dict[str, ArmResult]] = {}
    for case in cases:
        results = {arm: run_arm(root, case, arm, time_limit) for arm in ARMS}
        results_by_role[case.role] = results
        scenarios.append({
            "role": case.role,
            "artifact_path": str(case.path.relative_to(root)),
            "root_sha256": case.artifact.sha256,
            "root_original_bytes_verified": _sha256(case.path.read_bytes()) == case.artifact.sha256,
            "parent_expected_business_correct": case.parent_report["registered_audit"]["business_correct"],
            "parent_public_report": case.parent_report,
            "preflight_seconds": case.preflight_seconds,
            "arms_share_exact_root_bytes": all(
                result.run.initial.checkpoint.raw_bytes == case.raw for result in results.values()
            ),
            "arms": {arm: result.summary for arm, result in results.items()},
        })

    frozen = {}
    for scenario in scenarios:
        role = scenario["role"]
        case = next(case for case in cases if case.role == role)
        for arm in ARMS:
            run = results_by_role[role][arm].run
            raw = run.best.checkpoint.raw_bytes
            digest = _sha256(raw)
            if digest != scenario["arms"][arm]["best_sha256"]:
                raise AssertionError(f"selected artifact changed while freezing: {role}/{arm}")
            path = out / "final" / role / arm / "solution.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            if _sha256(path.read_bytes()) != digest:
                raise AssertionError(f"frozen write differs from selection: {role}/{arm}")
            frozen[f"{role}/{arm}"] = digest
        if _sha256(case.path.read_bytes()) != case.artifact.sha256:
            raise AssertionError(f"input root bytes changed during search: {role}")

    return {
        "schema_version": "gepa_industryor_id20_experiment.v0.1",
        "status": "selection_complete",
        "validation_scope": "development_only_not_heldout",
        "root_manifest": copy.deepcopy(ROOT_MANIFEST),
        "settings": {
            "primary_arms": list(PRIMARY_ARMS),
            "merge_arm": PARETO_MERGE,
            "evaluation_budget_per_arm_including_direct_and_declarative": EVALUATION_BUDGET,
            "k": K,
            "depth": DEPTH,
            "random_seed": SEED,
            "scip_time_limit_seconds": time_limit,
            "direct_and_declarative_stop": "one operation by definition; unused common budget is not filled with duplicate solves",
            "merge_policy": "test only a compatible, novel, full-public-PASS merge; every other attempt is not_tested",
        },
        "public_semantics": adapter.public.to_dict(),
        "policy": {
            "manifest_default_roots_used": False,
            "root_variable_semantics_fail_closed": True,
            "public_answer_used_for_repair_or_selection": False,
            "public_answer_read_before_freeze": False,
            "final_score_solution_audit": "fresh post-freeze score_solution calls, not cached search reports",
            "business_unverified_counts_as_correct": False,
            "llm_calls": 0,
            "llm_tokens": 0,
        },
        "runtime": _runtime(),
        "implementation_sha256": {
            name: _sha256((root / name).read_bytes()) for name in IMPLEMENTATION_FILES
        },
        "dataset_sha256": _sha256((root / "data/industryor/IndustryOR.json").read_bytes()),
        "registered_manifest_sha256": _sha256((root / "assets/industryor_next_stage/manifest.json").read_bytes()),
        "selection_complete": True,
        "final_independent_audit_complete": False,
        "public_answer_scored": False,
        "public_answer_used_for_candidate_selection": False,
        "frozen_final_sha256": frozen,
        "scenarios": scenarios,
        "selection_wall_seconds": time.perf_counter() - started,
        "summary": {},
    }


def _refresh_summary(audit: dict[str, Any]) -> None:
    arms = [arm for scenario in audit["scenarios"] for arm in scenario["arms"]]
    primary_failures = [
        scenario for scenario in audit["scenarios"] if scenario["role"] == "narrow_failure"
    ]
    controls = [scenario for scenario in audit["scenarios"] if scenario["role"] == "correct_control"]
    merge_records = [
        scenario["arms"][PARETO_MERGE]["merge"]
        for scenario in audit["scenarios"] if PARETO_MERGE in scenario["arms"]
    ]
    audit["summary"] = {
        "primary_arms": list(PRIMARY_ARMS),
        "failure_business_correct_by_arm": {
            arm: [scenario["arms"][arm]["final_independent_audit"]["business_correct"] is True
                  for scenario in primary_failures]
            for arm in PRIMARY_ARMS if primary_failures
        },
        "correct_control_original_bytes_preserved": all(
            scenario["arms"][arm]["correct_root_original_bytes_preserved"] is True
            and scenario["arms"][arm]["best_sha256"] == scenario["root_sha256"]
            for scenario in controls for arm in scenario["arms"]
        ),
        "merge_attempted": sum(row["attempted"] for row in merge_records),
        "merge_tested": sum(row["tested"] for row in merge_records),
        "merge_not_tested": sum(row["not_tested"] for row in merge_records),
        "llm_calls": 0,
        "llm_tokens": 0,
        "business_audit_calls": sum(
            scenario["arms"][arm]["adapter_counters"]["business_audit_calls"]
            for scenario in audit["scenarios"] for arm in scenario["arms"]
        ),
        "scip_sub_milp_runs": sum(
            scenario["arms"][arm]["adapter_counters"]["scip_sub_milp_runs"]
            for scenario in audit["scenarios"] for arm in scenario["arms"]
        ),
        "total_search_seconds": sum(
            scenario["arms"][arm]["total_search_seconds"]
            for scenario in audit["scenarios"] for arm in scenario["arms"]
        ),
        "post_freeze_independent_audit_seconds": sum(
            scenario["arms"][arm]["final_independent_audit_seconds"]
            for scenario in audit["scenarios"] for arm in scenario["arms"]
        ),
        "arm_wall_seconds": sum(
            scenario["arms"][arm]["arm_wall_seconds"]
            for scenario in audit["scenarios"] for arm in scenario["arms"]
        ),
        "arm_count": len(arms),
    }


def _frozen_solution(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("frozen final is not a JSON object")
    if value.get("schema_version") == SOLUTION_SCHEMA:
        return value
    if set(value) == {"variables", "objective", "state"}:
        return solution_from_decisions(value)
    raise ValueError("frozen final uses an unsupported decision representation")


def score_frozen(audit: dict[str, Any], root: Path, out: Path,
                 answer_loader: Callable[[], float] | None = None,
                 scorer: Callable[[int, Mapping[str, Any]], dict[str, Any]] = score_solution) -> dict[str, Any]:
    if not audit.get("selection_complete") or audit.get("public_answer_used_for_candidate_selection"):
        raise ValueError("post-freeze scoring requires completed answer-free selection")
    expected = {
        f"{scenario['role']}/{arm}"
        for scenario in audit["scenarios"] for arm in scenario["arms"]
    }
    if set(audit["frozen_final_sha256"]) != expected:
        raise ValueError("frozen final manifest does not exactly cover every selected arm")
    solutions: dict[str, dict[str, Any]] = {}
    for scenario in audit["scenarios"]:
        if _sha256((root / scenario["artifact_path"]).read_bytes()) != scenario["root_sha256"]:
            raise ValueError(f"input root changed before final scoring: {scenario['role']}")
        for arm in scenario["arms"]:
            key = f"{scenario['role']}/{arm}"
            path = out / "final" / scenario["role"] / arm / "solution.json"
            raw = path.read_bytes()
            if _sha256(raw) != audit["frozen_final_sha256"][key] \
                    or _sha256(raw) != scenario["arms"][arm]["best_sha256"]:
                raise ValueError(f"frozen final changed before independent scoring: {key}")
            solutions[key] = _frozen_solution(raw)

    for scenario in audit["scenarios"]:
        for arm, record in scenario["arms"].items():
            key = f"{scenario['role']}/{arm}"
            started = time.perf_counter()
            score = scorer(20, solutions[key])
            elapsed = time.perf_counter() - started
            if score.get("audit_status") != "complete":
                raise ValueError(f"independent final audit is incomplete: {key}")
            record["final_independent_audit"] = score
            record["final_independent_audit_seconds"] = elapsed
            record["total_cost_seconds_including_final_audit"] = record["total_search_seconds"] + elapsed
            record["final_business_conclusion"] = {
                "business_correct": score["business_correct"] is True,
                "business_objective": score["business_objective"],
                "optimality": score["optimality"],
                "violations": list(score["violations"]),
            }
    audit["final_independent_audit_complete"] = True

    answer = (_public_answer(root) if answer_loader is None else answer_loader())
    answer_started = time.perf_counter()
    for scenario in audit["scenarios"]:
        for arm, record in scenario["arms"].items():
            key = f"{scenario['role']}/{arm}"
            solution = solutions[key]
            objective = record["final_independent_audit"]["business_objective"]
            record["public_answer"] = {
                "en_answer": answer,
                "reported_model_objective_match_abs_0_1": abs(float(solution["objective"]) - answer) <= 0.1,
                "business_objective_match_abs_0_1": (
                    isinstance(objective, (int, float)) and abs(objective - answer) <= 0.1
                ),
                "scored_after_freeze": True,
            }
            record["public_answer_scored"] = True
    audit["post_freeze_public_answer"] = {"en_answer": answer, "abs_tolerance": 0.1}
    audit["public_answer_scoring_seconds"] = time.perf_counter() - answer_started
    audit["public_answer_scored"] = True
    audit["status"] = "complete"
    if "summary" in audit:
        _refresh_summary(audit)
    return audit


def _number(value: Any) -> str:
    return "NA" if value is None else f"{float(value):.6f}"


def build_report(audit: Mapping[str, Any]) -> str:
    summary = audit["summary"]
    settings = audit["settings"]
    lines = [
        "# IndustryOR ID20 公开 MILP 与 GEPA-inspired 机制验证",
        "",
        "本实验是 **development validation，非 heldout**。只重放两个显式指定的 ID20 决策根，不用于估计总体恢复率或宣称 benchmark/SOTA 提升。搜索与选择不读取 `en_answer`；最终独立 `score_solution` 和公开答案评分均发生在 SHA256 冻结之后。",
        "",
        "## 公开 MILP 与根契约",
        "",
        "- `x1..x4` 为非负整数，`y1..y4` 为 binary；最大化 `15*x1 + 8*x2 + 12*x3 + 5*x4`。",
        "- 资源约束为 `30*x1+10*x2+20*x3+15*x4 <= 1200` 与 `8*x1+5*x2+3*x3+2*x4 <= 800`。",
        "- 逻辑约束为 `y1+y4 <= 1`、`y3 >= y2`、`x4 <= x2`；每个 `i` 均有 `yi <= xi <= Mi*yi`，`M=(40,120,60,80)`。题面、注册 question hash 与 ORThought 源文件 hash 均已核验。",
        "- 失败根父独立业务结论为 `False`，违规为 `cars_imply_blocks`、`link_x3_y3`、`link_x4_y4`；正确控制父结论为 `True/proven_optimal`。manifest 默认根未使用，ID20 只接受八个精确变量及匹配的 INTEGER/BINARY 声明与注册语义。",
        "",
        "## 同根同预算对照",
        "",
        f"五个主臂为 `{', '.join(PRIMARY_ARMS)}`，另有 `{PARETO_MERGE}` 辅助臂。每臂上限均为 {settings['evaluation_budget_per_arm_including_direct_and_declarative']} 次 child evaluation；direct-full 和 declarative 按定义一次操作后停止，不用重复求解填满预算。所有候选使用公开检查，最终 elite-best 先冻结再独立复评。",
        "",
        "| 根 | 臂 | Child eval | SCIP runs | 父目标 | 最终目标 | 最终违规数 | 独立业务正确 | 独立最优性 | en_answer 匹配 | 搜索秒 | 冻结后审计秒 |",
        "|---|---|---:|---:|---:|---:|---:|---|---|---|---:|---:|",
    ]
    for scenario in audit["scenarios"]:
        parent_objective = scenario["parent_public_report"]["objective"]
        for arm in ARMS:
            row = scenario["arms"][arm]
            final = row["final_independent_audit"]
            lines.append(
                f"| {scenario['role']} | {arm} | {row['child_evaluations']} | "
                f"{row['adapter_counters']['scip_sub_milp_runs']} | {_number(parent_objective)} | "
                f"{_number(final['business_objective'])} | {len(final['violations'])} | "
                f"{final['business_correct']} | {final['optimality']} | "
                f"{row['public_answer']['business_objective_match_abs_0_1']} | "
                f"{_number(row['total_search_seconds'])} | {_number(row['final_independent_audit_seconds'])} |"
            )
    lines.extend([
        "",
        "## 血缘、违规与 merge 判别",
        "",
        "`audit.json` 保留每个候选的 `parent_id`、`parent_sha256`、operation、公开违规、目标、接受/拒绝原因和逐条成本 ledger。merge 只有真实兼容、非重复且完整公开检查 PASS 才计 tested；其余一律 `not_tested`，不计 invalid，也不为制造 merge 而追加预算。",
        "",
        "| 根 | Merge attempted | Tested | Not tested | Not-tested reasons |",
        "|---|---:|---:|---:|---|",
    ])
    for scenario in audit["scenarios"]:
        merge = scenario["arms"][PARETO_MERGE]["merge"]
        lines.append(
            f"| {scenario['role']} | {merge['attempted']} | {merge['tested']} | {merge['not_tested']} | "
            f"{json.dumps(merge['not_tested_reasons'], ensure_ascii=False, sort_keys=True)} |"
        )
    recovered = {
        arm: values for arm, values in summary["failure_business_correct_by_arm"].items()
    }
    lines.extend([
        "",
        "## 独立业务结论与成本",
        "",
        f"- 失败根五主臂独立业务正确序列：`{json.dumps(recovered, ensure_ascii=False)}`。正确控制所有臂保留原始字节：`{summary['correct_control_original_bytes_preserved']}`。",
        f"- Merge attempted/tested/not_tested = {summary['merge_attempted']}/{summary['merge_tested']}/{summary['merge_not_tested']}；没有真实兼容 merge 时不声称 merge 增益。",
        f"- LLM 调用 0、tokens 0；真实 SCIP sub-MILP 共 {summary['scip_sub_milp_runs']} 次，搜索公开审计 {summary['business_audit_calls']} 次。搜索 ledger 总秒数 {summary['total_search_seconds']:.6f}，臂墙钟合计 {summary['arm_wall_seconds']:.6f}，冻结后独立审计 {summary['post_freeze_independent_audit_seconds']:.6f}s。",
        "- `total_search_seconds` 是逐候选可调和成本；`arm_wall_seconds` 另含选父等控制开销，二者不相加。求解时间已经包含在 evaluation 中，不重复计费。既有输入根的历史生成成本不在本次增量成本内。",
        "- 单题、单失败根、单正确根且全部属于开发验证；结果只说明本根上的机制行为，不构成 heldout 泛化证据。",
        "",
        "机器明细：`work/gepa_industryor_id20_v0.1/audit.json`；冻结制品位于同目录 `final/`。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--time-limit", type=float, default=TIME_LIMIT_SECONDS)
    args = parser.parse_args()
    root = args.root.resolve()
    out = args.out if args.out.is_absolute() else root / args.out
    out = out.resolve()
    started = time.perf_counter()
    audit = generate_selection(root, out, args.time_limit)
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "audit.json", audit)
    audit = score_frozen(audit, root, out)
    audit["whole_experiment_wall_seconds"] = time.perf_counter() - started
    _write_json(out / "audit.json", audit)
    (out / "report.md").write_text(build_report(audit), encoding="utf-8")
    print(json.dumps({
        "status": audit["status"], "summary": audit["summary"],
        "audit": str(out / "audit.json"), "report": str(out / "report.md"),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

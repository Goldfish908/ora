"""Real-evidence audit for the federated sub-MILP method-level skill candidate."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .oragentbench import official_metrics
from .skill_assets import REJECTED, SkillAsset, SkillRegistry, replay_paired_evidence

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "work/gepa_federated_experiment_v0.1"
SOURCE_SCHEMA = "gepa_federated_experiment_v0.1"
AUDIT_SCHEMA = "federated_skill_audit_v0.1"
PROBLEM_ID = "federated_learning_cohort_selection"
METHOD_ID = "federated_sub_milp_v0.1"
VERSION = "0.1"
CONTROL_ARM = "direct-full"
TREATMENT_ARM = "single"
CONTROL_SOURCE = "scripts/federated_population_audit.py"
TREATMENT_SOURCE = "ora_agent/federated_neighborhood.py"
EVALUATOR_SOURCE = "ora_agent/oragentbench.py"
DEV_TASKS = ("duplicate_client", "stream_minimums")
GAPCHECK_TASKS = ("all_budgets",)
METRIC_FIELDS = ("feasible", "quality", "true_correct", "objective", "evaluation_unknown")


@dataclass
class CandidateBundle:
    source: dict[str, Any]
    asset: SkillAsset
    evidence: dict[str, Any]
    pairs: list[dict[str, Any]]
    clean_control: dict[str, Any]
    provenance: dict[str, Any]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _digest_json(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    return float(value)


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-8)


def _inside(base: Path, relative: str) -> Path:
    path = (base / relative).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"source artifact escapes its audit directory: {relative}") from exc
    return path


def load_source_audit(source_root: Path = SOURCE_ROOT, *, root: Path = ROOT) -> dict[str, Any]:
    source_root = source_root.resolve()
    audit_path = source_root / "audit.json"
    snapshot_path = source_root / "implementation_snapshot.json"
    source = json.loads(audit_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if source.get("schema_version") != SOURCE_SCHEMA:
        raise ValueError("unexpected federated source audit schema")
    if snapshot.get("audit_sha256") != _digest_file(audit_path):
        raise ValueError("source audit does not match its frozen implementation snapshot")
    if snapshot.get("development_only") is not True:
        raise ValueError("the real source snapshot must retain its development-only scope")
    recorded = source.get("implementation_sha256")
    if not isinstance(recorded, dict) or not recorded:
        raise ValueError("source implementation hashes are missing")
    for name, expected in recorded.items():
        if _digest_file(root / name) != expected:
            raise ValueError(f"recorded implementation changed: {name}")
    return source


def _evaluator_binding(root: Path) -> dict[str, Any]:
    test_root = root / "ORAgentBench/harbor_tasks" / PROBLEM_ID / "tests"
    paths = [root / EVALUATOR_SOURCE]
    paths.extend(sorted(path for path in test_root.rglob("*") if path.is_file()))
    sources = {}
    for path in paths:
        relative = str(path.relative_to(root))
        sources[relative] = _digest_file(path)
    return {
        "kind": "ORAgentBench official wrapper and federated task tests",
        "sha256": _digest_json(sources),
        "sources": sources,
        "historical_binding_note": (
            "The source experiment did not freeze a separate evaluator hash; this audit binds "
            "the current wrapper and task tests and recomputes every saved official result."
        ),
    }


def _verify_public_files(source: Mapping[str, Any], root: Path) -> dict[str, str]:
    app = root / "ORAgentBench/harbor_tasks" / PROBLEM_ID / "environment/app"
    recorded = source.get("public_file_sha256")
    if not isinstance(recorded, dict) or not recorded:
        raise ValueError("source public-file hashes are missing")
    actual = {name: _digest_file(app / name) for name in sorted(recorded)}
    if actual != recorded:
        raise ValueError("current public files differ from the source experiment")
    return actual


def _best_candidate(arm: Mapping[str, Any]) -> dict[str, Any] | None:
    best_id = arm.get("best_candidate_id")
    matches = [row for row in arm.get("candidates", []) if row.get("id") == best_id]
    if len(matches) > 1:
        raise ValueError(f"duplicate best candidate id: {best_id}")
    if best_id == "root":
        if matches or arm.get("best_sha256") != arm.get("initial_sha256"):
            raise ValueError("root-best arm does not preserve the root artifact")
        return None
    if len(matches) != 1:
        raise ValueError(f"best candidate is missing: {best_id}")
    candidate = matches[0]
    if candidate.get("artifact_sha256") != arm.get("best_sha256"):
        raise ValueError("best candidate artifact hash does not match the frozen best hash")
    return candidate


def _operation_candidate(arm: Mapping[str, Any], operation: str) -> dict[str, Any]:
    matches = [row for row in arm.get("candidates", []) if row.get("operation") == operation]
    if not matches:
        raise ValueError(f"arm did not really execute {operation}")
    return matches[0]


def _official_outcome(
    row: Mapping[str, Any],
    arm_name: str,
    arm: Mapping[str, Any],
    *,
    source_root: Path,
    source: Mapping[str, Any],
    implementation_sha256: str,
    evaluator_sha256: str,
) -> dict[str, Any]:
    scenario = str(row["scenario"])
    official = arm.get("official")
    if not isinstance(official, dict):
        raise ValueError(f"missing official result: {scenario}/{arm_name}")
    result_dir = _inside(source_root, str(official.get("output_dir", "")))
    raw_path = result_dir / "official_evaluation.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    metrics = official_metrics(raw)
    for field in METRIC_FIELDS:
        if official.get(field) != metrics[field]:
            raise ValueError(f"source official metric mismatch: {scenario}/{arm_name}/{field}")
    runner = raw.get("runner") or {}
    if official.get("runner_return_code") != runner.get("return_code") \
            or official.get("runner_timed_out") != runner.get("timed_out") \
            or official.get("runner_wall_seconds") != runner.get("wall_seconds"):
        raise ValueError(f"source official runner mismatch: {scenario}/{arm_name}")
    final_path = source_root / "final" / scenario / arm_name / "solution.csv"
    final_sha256 = _digest_file(final_path)
    frozen_key = f"{scenario}/{arm_name}"
    if final_sha256 != arm.get("best_sha256") \
            or final_sha256 != official.get("candidate_sha256") \
            or source.get("frozen_final_sha256", {}).get(frozen_key) != final_sha256:
        raise ValueError(f"frozen final artifact mismatch: {frozen_key}")
    decision_hashes = (raw.get("evaluation_inputs") or {}).get("decision_sha256") or {}
    if decision_hashes.get("solution.csv") != final_sha256:
        raise ValueError(f"official input artifact mismatch: {frozen_key}")

    public = arm.get("best_public") or {}
    if public.get("status") not in {"FEASIBLE", "INFEASIBLE"}:
        raise ValueError(f"invalid final public status: {frozen_key}")
    if not isinstance(public.get("violation_count"), int) or public["violation_count"] < 0:
        raise ValueError(f"invalid public violation count: {frozen_key}")
    if public.get("objective") is not None:
        _number(public["objective"], f"public objective {frozen_key}")

    search = _number(arm.get("total_search_seconds"), f"search cost {frozen_key}")
    official_seconds = _number(runner.get("wall_seconds"), f"official cost {frozen_key}")
    if arm.get("official_wall_seconds") != runner.get("wall_seconds"):
        raise ValueError(f"official wall-time summary mismatch: {frozen_key}")
    total = _number(
        arm.get("total_cost_seconds_including_official"), f"total cost {frozen_key}")
    if not _close(search + official_seconds, total):
        raise ValueError(f"search plus official cost does not reconcile: {frozen_key}")
    if arm.get("cost_reconciled") is not True or arm.get("cost_ledger_reconciled") is not True:
        raise ValueError(f"cost ledger is not marked reconciled: {frozen_key}")
    ledger = arm.get("cost_ledger")
    if not isinstance(ledger, list) or not ledger:
        raise ValueError(f"cost ledger is missing: {frozen_key}")
    ledger_total = sum(_number(entry.get("total_seconds"), f"ledger cost {frozen_key}")
                       for entry in ledger)
    if not _close(ledger_total, search):
        raise ValueError(f"itemized cost ledger does not reconcile: {frozen_key}")
    child_evaluations = arm.get("child_evaluations")
    solver_calls = arm.get("solver_call_count")
    evaluation_budget = arm.get("evaluation_budget")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
           for value in (child_evaluations, solver_calls, evaluation_budget)):
        raise ValueError(f"invalid evaluation counts: {frozen_key}")
    if solver_calls > child_evaluations or child_evaluations > evaluation_budget:
        raise ValueError(f"evaluation or solver budget exceeded: {frozen_key}")
    candidate = _best_candidate(arm)
    operation = "initial" if candidate is None else candidate.get("operation")
    spec = None if candidate is None else candidate.get("spec_signature")
    status = "UNKNOWN" if metrics["evaluation_unknown"] else "OK"
    if not metrics["evaluation_unknown"] and metrics["feasible"] and metrics["objective"] is None:
        raise ValueError(f"feasible official result lacks an objective: {frozen_key}")
    cost = {
        "initial_evaluation_seconds": _number(
            arm.get("initial_evaluation_seconds"), f"initial cost {frozen_key}"),
        "proposal_seconds": _number(arm.get("proposal_seconds"), f"proposal cost {frozen_key}"),
        "evaluation_seconds": _number(
            arm.get("evaluation_seconds"), f"evaluation cost {frozen_key}"),
        "solver_seconds": _number(arm.get("solver_seconds"), f"solver cost {frozen_key}"),
        "search_seconds": search,
        "official_wall_seconds": official_seconds,
        "total_seconds": total,
        "ledger_total_seconds": ledger_total,
        "cost_ledger_sha256": _digest_json(ledger),
        "child_evaluations": child_evaluations,
        "solver_calls": solver_calls,
        "evaluation_budget": evaluation_budget,
        "llm_calls": source.get("llm_calls"),
    }
    if cost["llm_calls"] != 0:
        raise ValueError("the candidate cost contract requires the recorded zero-LLM experiment")
    return {
        "initial_artifact_sha256": arm.get("initial_sha256"),
        "implementation_sha256": implementation_sha256,
        "evaluator_sha256": evaluator_sha256,
        "status": status,
        "true_correct": metrics["true_correct"],
        "proxy_correct": public["status"] == "FEASIBLE" and public["violation_count"] == 0,
        "candidate_id": arm.get("best_candidate_id"),
        "candidate_sha256": final_sha256,
        "operation": operation,
        "spec_signature": copy.deepcopy(spec),
        "public": copy.deepcopy(public),
        "official": {
            **metrics,
            "candidate_sha256": final_sha256,
            "runner_return_code": runner.get("return_code"),
            "runner_timed_out": runner.get("timed_out"),
            "runner_wall_seconds": official_seconds,
            "output_dir": official["output_dir"],
            "raw_official_evaluation_sha256": _digest_file(raw_path),
        },
        "cost": cost,
        "unchanged": arm.get("unchanged"),
        "best_not_worse_than_initial": arm.get("best_not_worse_than_initial"),
    }


def _not_worse(treatment: float, control: float) -> bool:
    tolerance = 1e-9 * max(1.0, abs(treatment), abs(control))
    return treatment + tolerance >= control


def _make_pair(
    row: Mapping[str, Any],
    split: str,
    *,
    source_root: Path,
    source: Mapping[str, Any],
    baseline_sha256: str,
    treatment_sha256: str,
    evaluator_sha256: str,
) -> dict[str, Any]:
    scenario = row.get("scenario")
    if row.get("arms_share_exact_initial_candidate") is not True:
        raise ValueError(f"arms do not declare an exact shared root: {scenario}")
    seed = row.get("random_seed")
    if seed != source.get("settings", {}).get("random_seed"):
        raise ValueError(f"scenario seed differs from the frozen setting: {scenario}")
    arms = row.get("arms") or {}
    if CONTROL_ARM not in arms or TREATMENT_ARM not in arms:
        raise ValueError(f"missing direct-full/sub-MILP pair: {scenario}")
    control = _official_outcome(
        row, CONTROL_ARM, arms[CONTROL_ARM], source_root=source_root, source=source,
        implementation_sha256=baseline_sha256, evaluator_sha256=evaluator_sha256)
    treatment = _official_outcome(
        row, TREATMENT_ARM, arms[TREATMENT_ARM], source_root=source_root, source=source,
        implementation_sha256=treatment_sha256, evaluator_sha256=evaluator_sha256)
    if control["initial_artifact_sha256"] != row.get("initial_sha256") \
            or treatment["initial_artifact_sha256"] != row.get("initial_sha256"):
        raise ValueError(f"control and treatment do not use the same initial root: {scenario}")

    direct = _operation_candidate(arms[CONTROL_ARM], "direct_full_reoptimization")
    direct_spec = direct.get("spec_signature") or {}
    if direct_spec.get("fixed_variable_count") != 0 \
            or not isinstance(direct_spec.get("released_variable_count"), int) \
            or direct_spec["released_variable_count"] <= 0:
        raise ValueError(f"direct-full control did not release the full decision vector: {scenario}")
    variable_count = direct_spec["released_variable_count"]
    if arms[CONTROL_ARM].get("evaluation_budget") != 1 \
            or arms[CONTROL_ARM].get("child_evaluations") != 1 \
            or arms[CONTROL_ARM].get("solver_call_count") != 1:
        raise ValueError(f"direct-full control is not exactly one full solve: {scenario}")
    if control["operation"] not in {"initial", "direct_full_reoptimization"}:
        raise ValueError(f"control final artifact did not come from the direct-full arm: {scenario}")
    treatment_spec = treatment.get("spec_signature") or {}
    released = treatment_spec.get("released_variable_count")
    fixed = treatment_spec.get("fixed_variable_count")
    if not isinstance(released, int) or not isinstance(fixed, int) \
            or released <= 0 or fixed <= 0 or released + fixed != variable_count:
        raise ValueError(f"treatment best is not a proper sub-MILP: {scenario}")
    if treatment["operation"] == "direct_full_reoptimization":
        raise ValueError(f"treatment best is direct-full rather than sub-MILP: {scenario}")
    if arms[TREATMENT_ARM].get("evaluation_budget") != 6:
        raise ValueError(f"unexpected sub-MILP treatment budget: {scenario}")

    control_official = control["official"]
    treatment_official = treatment["official"]
    objective_delta = None
    if control_official["objective"] is not None and treatment_official["objective"] is not None:
        objective_delta = treatment_official["objective"] - control_official["objective"]
    quality_delta = treatment_official["quality"] - control_official["quality"]
    deltas = {
        "quality_treatment_minus_control": quality_delta,
        "objective_treatment_minus_control": objective_delta,
        "search_seconds_treatment_minus_control": (
            treatment["cost"]["search_seconds"] - control["cost"]["search_seconds"]),
        "total_seconds_treatment_minus_control": (
            treatment["cost"]["total_seconds"] - control["cost"]["total_seconds"]),
    }
    checks = {
        "same_initial_root": True,
        "official_records_recomputed": True,
        "frozen_artifacts_verified": True,
        "costs_reconciled": True,
        "both_official_feasible": control_official["feasible"] and treatment_official["feasible"],
        "both_official_true": control_official["true_correct"] and treatment_official["true_correct"],
        "quality_not_worse": _not_worse(
            treatment_official["quality"], control_official["quality"]),
        "objective_not_worse": objective_delta is not None and _not_worse(
            treatment_official["objective"], control_official["objective"]),
        "search_cost_not_worse": _not_worse(
            control["cost"]["search_seconds"], treatment["cost"]["search_seconds"]),
        "total_cost_not_worse": _not_worse(
            control["cost"]["total_seconds"], treatment["cost"]["total_seconds"]),
        "equal_evaluation_budget": (
            control["cost"]["evaluation_budget"] == treatment["cost"]["evaluation_budget"]),
        "gained_true": not control_official["true_correct"] and treatment_official["true_correct"],
        "lost_true": control_official["true_correct"] and not treatment_official["true_correct"],
        "new_phantom": (not (control["proxy_correct"] and not control_official["true_correct"])
                        and treatment["proxy_correct"] and not treatment_official["true_correct"]),
    }
    return {
        "scenario": scenario,
        "split": split,
        "seed": seed,
        "initial_sha256": row["initial_sha256"],
        "initial_public": copy.deepcopy(row.get("initial_public")),
        "control": control,
        "treatment": treatment,
        "deltas": deltas,
        "checks": checks,
    }


def prepare_candidate(
    source: dict[str, Any],
    *,
    source_root: Path = SOURCE_ROOT,
    root: Path = ROOT,
) -> CandidateBundle:
    if source.get("schema_version") != SOURCE_SCHEMA:
        raise ValueError("unexpected federated source audit schema")
    if source.get("selection_complete") is not True or source.get("official_complete") is not True \
            or source.get("official_feedback_used_for_candidate_selection") is not False:
        raise ValueError("source experiment is incomplete or used official feedback for selection")
    recorded = source.get("implementation_sha256") or {}
    for name in (CONTROL_SOURCE, TREATMENT_SOURCE):
        if _digest_file(root / name) != recorded.get(name):
            raise ValueError(f"recorded arm implementation changed: {name}")
    public_file_sha256 = _verify_public_files(source, root)
    evaluator = _evaluator_binding(root)
    baseline_code = (root / CONTROL_SOURCE).read_text(encoding="utf-8")
    treatment_code = (root / TREATMENT_SOURCE).read_text(encoding="utf-8")
    baseline_sha256 = hashlib.sha256(baseline_code.encode("utf-8")).hexdigest()
    treatment_sha256 = hashlib.sha256(treatment_code.encode("utf-8")).hexdigest()
    if baseline_sha256 == treatment_sha256:
        raise ValueError("direct-full baseline and sub-MILP treatment must have different hashes")

    rows = {row.get("scenario"): row for row in source.get("scenarios", [])}
    expected = set(DEV_TASKS) | set(GAPCHECK_TASKS)
    if set(rows) != expected or len(source.get("scenarios", [])) != len(expected):
        raise ValueError("source scenarios do not exactly cover the declared dev/gapcheck tasks")
    pairs = []
    for split, tasks in (("dev", DEV_TASKS), ("gapcheck", GAPCHECK_TASKS)):
        for task in tasks:
            pairs.append(_make_pair(
                rows[task], split, source_root=source_root, source=source,
                baseline_sha256=baseline_sha256, treatment_sha256=treatment_sha256,
                evaluator_sha256=evaluator["sha256"]))
    clean_row = source.get("clean_control")
    if not isinstance(clean_row, dict) or clean_row.get("scenario") != "clean_control":
        raise ValueError("separate clean control is missing")
    clean = _make_pair(
        clean_row, "clean_control", source_root=source_root, source=source,
        baseline_sha256=baseline_sha256, treatment_sha256=treatment_sha256,
        evaluator_sha256=evaluator["sha256"])
    if source.get("common_clean_sha256") != clean["initial_sha256"]:
        raise ValueError("clean control root differs from the common clean artifact")

    records = [{
        "split": pair["split"],
        "task_id": pair["scenario"],
        "seed": pair["seed"],
        "control": copy.deepcopy(pair["control"]),
        "treatment": copy.deepcopy(pair["treatment"]),
    } for pair in pairs]
    evidence = {"schema_version": 1, "records": records}
    treatment_costs = [pair["treatment"]["cost"] for pair in pairs]
    count = len(treatment_costs)

    def mean(key: str) -> float:
        return sum(float(cost[key]) for cost in treatment_costs) / count

    cost = {
        "llm_calls": 0,
        "mean_search_seconds_across_3_predeclared_scenarios": mean("search_seconds"),
        "mean_official_wall_seconds_across_3_predeclared_scenarios": mean("official_wall_seconds"),
        "mean_total_seconds_across_3_predeclared_scenarios": mean("total_seconds"),
        "mean_solver_seconds_across_3_predeclared_scenarios": mean("solver_seconds"),
        "mean_child_evaluations_across_3_predeclared_scenarios": mean("child_evaluations"),
        "mean_solver_calls_across_3_predeclared_scenarios": mean("solver_calls"),
    }
    seed = source["settings"]["random_seed"]
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("source random seed is invalid")
    asset = SkillAsset(
        method_id=METHOD_ID,
        version=VERSION,
        trigger_signature={
            "asset_level": "method",
            "problem_id": PROBLEM_ID,
            "event": "declarative_solution_repair",
            "representation": "binary_client_stream_selection",
        },
        required_inputs=(
            "incumbent_solution_csv",
            "parent_artifact_sha256",
            "PROBLEM_STATEMENT.md",
            "data/config.json",
            "data/clients.csv",
            "data/training_streams.csv",
            "data/client_stream_scores.csv",
            "public_check_violations",
            "repair_mode",
            "solver_time_limit_and_relative_gap",
        ),
        dataset_scope=(f"ORAgentBench/{PROBLEM_ID}",),
        domain_scope=("logistics/federated-learning-cohort-selection",),
        api_scope=("PySCIPOpt==6.2.1", "federated_sub_milp_v0.1"),
        schema_scope=(f"{PROBLEM_ID}/solution.csv:client_id,stream_id,selected",),
        operations=(
            "build_violation_dependency_graph",
            "release_violations_and_direct_neighbors",
            "fix_all_non_neighborhood_binary_variables",
            "solve_public_maximize_sub_milp",
            "recheck_complete_public_constraints_and_objective",
            "accept_only_known_non_regressing_candidate",
        ),
        allowed_edits=("released_selected_binary_variables_only",),
        invariants=(
            "parent_sha256_must_match",
            "fixed_variables_must_remain_byte_identical",
            "released_and_fixed_variables_partition_the_complete_decision_vector",
            "eligible_client_stream_pairs_only",
            "no_new_public_violations",
            "maximize_objective_must_not_regress",
            "unknown_candidates_are_rejected",
            "official_feedback_is_post_freeze_only",
        ),
        forbidden_actions=(
            "change_fixed_variables",
            "alter_public_data_constraints_or_objective",
            "delete_or_hide_violations",
            "use_official_results_for_parent_selection_or_expansion",
            "claim_global_optimality_from_gaplimit",
            "activate_on_another_problem_dataset_domain_api_or_schema",
        ),
        positive_examples=tuple({
            "scenario": pair["scenario"],
            "root_sha256": pair["initial_sha256"],
            "candidate_sha256": pair["treatment"]["candidate_sha256"],
            "operation": pair["treatment"]["operation"],
            "observed": "official feasible and true; no public violations",
        } for pair in pairs),
        negative_examples=(
            {"case": "fixed_variable_changed", "required_action": "reject_and_restore_parent"},
            {"case": "new_violation_or_UNKNOWN", "required_action": "reject"},
            {"case": "clean_control", "required_action": "report_separately_not_as_damage_repair"},
        ),
        near_miss_examples=(
            {"scenario": "all_budgets", "scope": "privacy_upload_and_gpu_positive_contributors"},
            {"scenario": "stream_minimums", "scope": "same_stream_minimum_constraints_and_neighbors"},
        ),
        ambiguous_examples=(
            {"case": "duplicate_csv_row_aggregation", "required_action": "UNKNOWN_not_pass"},
            {"case": "gaplimit_solver_status", "required_action": "feasible_incumbent_not_optimality"},
        ),
        out_of_scope_examples=(
            {"case": "another_ORAgentBench_problem", "required_action": "do_not_activate"},
            {"case": "free_text_or_solver_code_generation", "required_action": "do_not_activate"},
            {"case": "different_solution_schema", "required_action": "do_not_activate"},
        ),
        code=treatment_code,
        text=(
            "Method-level declarative sub-MILP repair for the registered federated cohort-selection "
            "problem only. Release violation variables and direct neighbors, keep every other binary "
            "decision fixed, solve the complete public formulation, and accept only a fully rechecked "
            "non-regressing candidate. Costs are observed means over the three real predeclared "
            "single-chain treatment runs; they are not a promised runtime or cross-task estimate."
        ),
        baseline_implementation_sha256=baseline_sha256,
        evaluator_sha256=evaluator["sha256"],
        task_coverage={"dev": DEV_TASKS, "gapcheck": GAPCHECK_TASKS},
        required_seeds=(seed,),
        cost=cost,
        min_gained_true={"dev": 1, "gapcheck": 1},
    )
    provenance = {
        "source_schema": SOURCE_SCHEMA,
        "source_path": str(source_root / "audit.json"),
        "source_audit_sha256": _digest_file(source_root / "audit.json"),
        "source_snapshot_sha256": _digest_file(source_root / "implementation_snapshot.json"),
        "source_generation_git_head": source.get("generation_runtime", {}).get("git_head"),
        "source_runtime": copy.deepcopy(source.get("generation_runtime")),
        "implementation_sha256": copy.deepcopy(recorded),
        "control_implementation": {
            "arm": CONTROL_ARM,
            "source": CONTROL_SOURCE,
            "sha256": baseline_sha256,
            "execution": "independent direct-full arm and ledger; one all-variable solve",
        },
        "treatment_implementation": {
            "arm": TREATMENT_ARM,
            "source": TREATMENT_SOURCE,
            "sha256": treatment_sha256,
            "execution": "single-chain declarative sub-MILP arm and independent ledger",
        },
        "implementation_hashes_differ": True,
        "evaluator": evaluator,
        "public_file_sha256": public_file_sha256,
        "official_records_recomputed": 2 * (len(pairs) + 1),
        "frozen_final_artifacts_verified": 2 * (len(pairs) + 1),
        "metrics_source": "official_metrics(saved official_evaluation.json), never audit summaries alone",
    }
    return CandidateBundle(source, asset, evidence, pairs, clean, provenance)


def promotion_gate_allows(dev_report: Mapping[str, Any], scope: Mapping[str, Any]) -> bool:
    return bool(dev_report.get("passed") and scope.get("cross_task_evidence")
                and scope.get("independent_gapcheck"))


def audit_candidate(bundle: CandidateBundle) -> dict[str, Any]:
    asset = bundle.asset
    evidence = bundle.evidence
    registry = SkillRegistry()
    registry.propose(asset)
    dev_records = [row for row in evidence["records"] if row["split"] == "dev"]
    dev_report = registry.validate(asset.asset_id, {"schema_version": 1, "records": dev_records})
    full_replay = replay_paired_evidence(asset, evidence)
    scope = {
        "problem_ids": [PROBLEM_ID],
        "distinct_problem_count": 1,
        "scenario_origin": "predeclared corruptions of one clean artifact in one development experiment",
        "dev_tasks": list(DEV_TASKS),
        "gapcheck_tasks": list(GAPCHECK_TASKS),
        "gapcheck_classification": "same_problem_predeclared_replay_not_an_independent_holdout",
        "cross_task_evidence": False,
        "independent_gapcheck": False,
        "required_seeds": list(asset.required_seeds),
        "observed_seeds": sorted({row["seed"] for row in evidence["records"]}),
        "clean_control_separate": True,
    }
    promotion_report = None
    promotion_attempted = promotion_gate_allows(dev_report, scope)
    if promotion_attempted:
        promotion_report = registry.promote(asset.asset_id, evidence)
    promoted = asset.status == "promoted"

    scenario_checks = [pair["checks"] for pair in bundle.pairs]
    clean_checks = bundle.clean_control["checks"]
    clean_preserved = bool(
        clean_checks["same_initial_root"] and clean_checks["official_records_recomputed"]
        and clean_checks["both_official_feasible"] and clean_checks["both_official_true"]
        and clean_checks["quality_not_worse"] and clean_checks["objective_not_worse"]
        and not clean_checks["lost_true"] and not clean_checks["new_phantom"]
        and bundle.clean_control["control"]["best_not_worse_than_initial"] is True
        and bundle.clean_control["treatment"]["best_not_worse_than_initial"] is True
    )
    scoped_success = bool(
        all(checks["official_records_recomputed"] and checks["both_official_feasible"]
            and checks["both_official_true"] and checks["quality_not_worse"]
            and checks["objective_not_worse"] and not checks["lost_true"]
            and not checks["new_phantom"] for checks in scenario_checks)
        and clean_preserved
    )
    scoped = {
        "claim_scope": (
            "Only the three named predeclared repairs on ORAgentBench/"
            "federated_learning_cohort_selection with seed 20261123 and the separate clean control"
        ),
        "scope_limited_quality_and_objective_evidence": scoped_success,
        "all_scenario_arms_official_true": all(checks["both_official_true"] for checks in scenario_checks),
        "quality_not_worse_in_all_scenarios": all(checks["quality_not_worse"] for checks in scenario_checks),
        "objective_not_worse_in_all_scenarios": all(checks["objective_not_worse"] for checks in scenario_checks),
        "search_cost_not_worse_in_all_scenarios": all(
            checks["search_cost_not_worse"] for checks in scenario_checks),
        "total_cost_not_worse_in_all_scenarios": all(
            checks["total_cost_not_worse"] for checks in scenario_checks),
        "equal_evaluation_budget": all(checks["equal_evaluation_budget"] for checks in scenario_checks),
        "clean_control_preserved": clean_preserved,
        "clean_control_direct_full_unchanged": bundle.clean_control["control"]["unchanged"],
        "clean_control_treatment_unchanged": bundle.clean_control["treatment"]["unchanged"],
        "cross_task_superiority_supported": False,
        "global_optimality_supported": False,
        "treatment_attribution_note": (
            "The single arm mixes default, direct-full, and feasible-parent operations; its frozen "
            "best is verified sub-MILP, but the arm-level treatment effect is not a pure one-solve ablation."
        ),
    }
    reasons = list(full_replay["reasons"])
    if not scope["cross_task_evidence"]:
        reasons.append("cross_task_evidence_missing:only one problem with predeclared scenarios")
    if not scope["independent_gapcheck"]:
        reasons.append("independent_gapcheck_missing:all_budgets belongs to the same development experiment")
    if not clean_preserved:
        reasons.append("clean_control_regression")
    reasons = list(dict.fromkeys(reasons))
    missing = [
        (
            f"真实 dev gained_true 证据：当前为 {dev_report['layers']['dev']['gained_true']}，"
            f"要求 {asset.min_gained_true['dev']}；必须有配对从 control true=false 变为 "
            "treatment true=true，不能仅改写记录标签。"
        ),
        (
            "未见任务或 problem 上的独立 gapcheck gained_true 证据：当前为 "
            f"{full_replay['layers']['gapcheck']['gained_true']}，要求 "
            f"{asset.min_gained_true['gapcheck']}；all_budgets 不能证明跨任务晋升。"
        ),
        "额外预注册 seed 及冻结配对运行；当前证据只有 seed 20261123。",
        "预算匹配或预先声明成本目标的 direct-full 对照；当前 child evaluation 上限分别为 1 和 6。",
        "纯 sub-MILP 消融或候选级重放，把方法收益与 single 臂的混合操作序列分离。",
        "使用同一冻结评价器的独立留出 problem，并具备显式 scope、clean control 和完整成本账本。",
    ]
    return {
        "schema_version": AUDIT_SCHEMA,
        "asset": asset.to_dict(),
        "method": {
            "level": "method",
            "method_id": METHOD_ID,
            "version": VERSION,
            "control": "direct-full independent baseline implementation and cost ledger",
            "treatment": "single-chain declarative sub-MILP implementation and cost ledger",
            "baseline_implementation_sha256": asset.baseline_implementation_sha256,
            "treatment_implementation_sha256": asset.code_sha256,
            "evaluator_sha256": asset.evaluator_sha256,
            "implementation_hashes_differ": (
                asset.baseline_implementation_sha256 != asset.code_sha256),
        },
        "provenance": bundle.provenance,
        "coverage": scope,
        "pairs": bundle.pairs,
        "clean_control": bundle.clean_control,
        "paired_evidence": evidence,
        "registry": {
            "dev": dev_report,
            "full_replay": full_replay,
            "promotion_gate_allows_attempt": promotion_attempted,
            "promotion_attempted": promotion_report is not None,
            "promotion": promotion_report,
            "asset_status": asset.status,
            "promoted": promoted,
            "selectable_asset_ids": [item.asset_id for item in registry.select()],
        },
        "scoped_findings": scoped,
        "decision": {
            "promoted": promoted,
            "status": asset.status,
            "registry_rejected": asset.status == REJECTED,
            "reasons": reasons,
            "missing_evidence": missing,
        },
    }

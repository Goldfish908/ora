"""Fail-closed objective repair for the public IndustryOR supplier-order MILPs."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from ora_agent.declarative_neighborhood import (
    OBJECTIVE_OPTIMIZATION,
    DecisionArtifact,
    DependencyGraph,
    NeighborhoodSpec,
    ViolationKey,
    build_neighborhood,
)
from scripts.industryor_next_stage import score_solution

SOLUTION_SCHEMA = "industryor.solution.v1"
DIRECT_FULL = "direct-full"
DECLARATIVE = "declarative"
PARETO = "pareto"
ARMS = (DIRECT_FULL, DECLARATIVE, PARETO)
SUPPORTED_IDS = (19, 21)
VARIABLE_DOMAINS = {
    "x_A": "integer",
    "x_B": "integer",
    "x_C": "integer",
    "y_A": "binary",
    "y_B": "binary",
}
OBJECTIVE_FAILURE_VIOLATIONS = [
    "business objective is not independently optimal",
    "reported model objective differs from the audited business objective",
]
QUESTION_SHA256 = {
    19: "fe37a30dfca55f4ce240a35fc90d5b407e0b71550d9a2dcf2122b333904ba25b",
    21: "710403b956d8a0e8ff886f7345081f874d348504ad9f638d7d5e3ac94898ac82",
}


class NotReadyError(ValueError):
    pass


def _path(name: str) -> str:
    return f"variables.{name}"


def _objective_key(problem_id: int, part: str) -> ViolationKey:
    return ViolationKey(f"industryor.{problem_id}.objective", ("global",), part)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class SupplierMILP:
    problem_id: int
    q: Mapping[str, int]
    c: Mapping[str, int]
    M: Mapping[str, int]
    lower: int
    upper: int
    k: int

    @property
    def objective_coefficients(self) -> dict[str, int]:
        return {name: self.c[name] * self.q[name] for name in self.q}

    @property
    def question_sha256(self) -> str:
        return QUESTION_SHA256[self.problem_id]

    def objective(self, values: Mapping[str, float]) -> float:
        return float(sum(
            self.c[name] * self.q[name] * values[name] for name in self.q
        ))

    def quantity(self, values: Mapping[str, float]) -> float:
        return float(sum(self.q[name] * values[name] for name in self.q))

    def to_dict(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "question_sha256": self.question_sha256,
            "domains": dict(VARIABLE_DOMAINS),
            "bounds": {
                **{name: [0, self.M[name]] for name in self.q},
                "y_A": [0, 1],
                "y_B": [0, 1],
            },
            "units_per_order_q": dict(self.q),
            "unit_cost_c": dict(self.c),
            "big_M": dict(self.M),
            "quantity_bounds_L_U": [self.lower, self.upper],
            "A_activation_minimum_B_orders_k": self.k,
            "objective_sense": "minimize",
            "objective_coefficients_c_times_q": self.objective_coefficients,
            "objective_formula": "sum_s c_s * q_s * x_s",
            "constraints": [
                "Q = q_A*x_A + q_B*x_B + q_C*x_C",
                "L <= Q <= U",
                "x_A >= y_A",
                "x_A <= M_A*y_A",
                "x_B >= y_B",
                "x_B <= M_B*y_B",
                "x_B >= k*y_A",
                "x_C >= y_B",
            ],
        }

    def dependency_graph(self) -> DependencyGraph:
        paths = tuple(_path(name) for name in VARIABLE_DOMAINS)
        keys = (
            _objective_key(self.problem_id, "independent_optimality"),
            _objective_key(self.problem_id, "model_objective_consistency"),
        )
        return DependencyGraph(
            {key.stable_key: paths for key in keys},
            {name: tuple(other for other in paths if other != name) for name in paths},
        )


def supplier_milp(problem_id: int) -> SupplierMILP:
    if problem_id == 19:
        return SupplierMILP(
            19,
            {"x_A": 15, "x_B": 10, "x_C": 10},
            {"x_A": 50, "x_B": 45, "x_C": 40},
            {"x_A": 33, "x_B": 50, "x_C": 50},
            100,
            500,
            1,
        )
    if problem_id == 21:
        return SupplierMILP(
            21,
            {"x_A": 20, "x_B": 15, "x_C": 15},
            {"x_A": 120, "x_B": 110, "x_C": 100},
            {"x_A": 30, "x_B": 40, "x_C": 40},
            150,
            600,
            2,
        )
    raise NotReadyError("no reviewed public supplier MILP for this problem")


def solution_from_decisions(decisions: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(decisions, Mapping) or not isinstance(decisions.get("variables"), Mapping):
        raise NotReadyError("decision artifact lacks a variables object")
    state = decisions.get("state")
    if not isinstance(state, Mapping):
        raise NotReadyError("decision artifact lacks solver/export state")
    solution = copy.deepcopy(dict(state))
    solution["variables"] = copy.deepcopy(dict(decisions["variables"]))
    solution["objective"] = decisions.get("objective")
    if solution.get("schema_version") != SOLUTION_SCHEMA:
        raise NotReadyError("unsupported IndustryOR solution schema")
    return solution


def artifact_from_bytes(
    raw: bytes,
    sha256: str = "",
) -> DecisionArtifact:
    try:
        solution = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NotReadyError("parent solution is not valid UTF-8 JSON") from exc
    if not isinstance(solution, dict) or solution.get("schema_version") != SOLUTION_SCHEMA:
        raise NotReadyError("parent does not use industryor.solution.v1")
    variables = solution.get("variables")
    types = solution.get("variable_types")
    if not isinstance(variables, dict) or not isinstance(types, dict):
        raise NotReadyError("parent variables or variable_types are unavailable")
    if set(variables) != set(VARIABLE_DOMAINS) or set(types) != set(VARIABLE_DOMAINS):
        raise NotReadyError("parent does not use the exact reviewed variable set")
    expected_types = {"integer": "INTEGER", "binary": "BINARY"}
    for name, domain in VARIABLE_DOMAINS.items():
        value = variables[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value):
            raise NotReadyError(f"parent decision is not finite numeric data: {name}")
        if types[name] != expected_types[domain]:
            raise NotReadyError(f"required declared domain is unavailable: {name}")
    objective = solution.get("objective")
    if isinstance(objective, bool) or not isinstance(objective, (int, float)) \
            or not math.isfinite(objective):
        raise NotReadyError("parent model objective is unavailable")
    state = {
        key: copy.deepcopy(value)
        for key, value in solution.items() if key not in {"variables", "objective"}
    }
    decisions = {
        "variables": copy.deepcopy(variables),
        "objective": objective,
        "state": state,
    }
    return DecisionArtifact.create(decisions, raw_bytes=raw, sha256=sha256)


def business_feasible(score: Mapping[str, Any]) -> bool:
    execution = score.get("execution_checks", {})
    variables = score.get("variable_audit", {})
    constraints = score.get("constraint_checks", [])
    return bool(
        score.get("audit_status") == "complete"
        and execution and all(execution.values())
        and set(variables) == set(VARIABLE_DOMAINS)
        and all(row.get("passed") for row in variables.values())
        and constraints and all(row.get("passed") for row in constraints)
    )


class SupplierSCIPSolver:
    def __init__(self, public: SupplierMILP, time_limit: float = 30.0) -> None:
        try:
            import pyscipopt
        except ImportError as exc:
            raise NotReadyError("PySCIPOpt is required for the real supplier MILP experiment") from exc
        self.public = public
        self.time_limit = float(time_limit)
        self.pyscipopt = pyscipopt
        self.runs = 0
        self.wall_seconds = 0.0

    def __call__(self, spec: NeighborhoodSpec) -> tuple[str, Optional[DecisionArtifact]]:
        parent = artifact_from_bytes(spec.parent_bytes, spec.parent_sha256)
        released = set(spec.released_variables)
        semantic_paths = {_path(name) for name in VARIABLE_DOMAINS}
        if not released.issubset(semantic_paths):
            raise NotReadyError("an opaque variable cannot be released by the supplier adapter")
        model = self.pyscipopt.Model(f"industryor_{self.public.problem_id}_supplier_objective_repair")
        model.hideOutput()
        model.setRealParam("limits/time", self.time_limit)
        variables = {}
        for name, domain in VARIABLE_DOMAINS.items():
            upper = self.public.M[name] if name in self.public.M else 1
            variables[name] = model.addVar(
                name=name,
                vtype="I" if domain == "integer" else "B",
                lb=0,
                ub=upper,
            )
            path = _path(name)
            if path in spec.fixed_values:
                model.addCons(variables[name] == spec.fixed_values[path], f"fixed_{name}")
            elif path not in released:
                raise NotReadyError(f"semantic variable is neither fixed nor released: {name}")

        quantity = sum(self.public.q[name] * variables[name] for name in self.public.q)
        model.addCons(quantity >= self.public.lower, "minimum_total_quantity")
        model.addCons(quantity <= self.public.upper, "maximum_total_quantity")
        model.addCons(variables["x_A"] >= variables["y_A"], "positive_A_implies_y_A")
        model.addCons(
            variables["x_A"] <= self.public.M["x_A"] * variables["y_A"],
            "y_A_implies_positive_A",
        )
        model.addCons(variables["x_B"] >= variables["y_B"], "positive_B_implies_y_B")
        model.addCons(
            variables["x_B"] <= self.public.M["x_B"] * variables["y_B"],
            "y_B_implies_positive_B",
        )
        model.addCons(variables["x_B"] >= self.public.k * variables["y_A"], "A_requires_B_orders")
        model.addCons(variables["x_C"] >= variables["y_B"], "B_requires_C_order")
        model.setObjective(
            sum(
                self.public.c[name] * self.public.q[name] * variables[name]
                for name in self.public.q
            ),
            "minimize",
        )
        started = time.perf_counter()
        self.runs += 1
        model.optimize()
        self.wall_seconds += time.perf_counter() - started
        status = str(model.getStatus())
        if model.getNSols() < 1:
            return status, None
        complete = copy.deepcopy(parent.decisions)
        values = {}
        for path in spec.released_variables:
            name = path.split(".", 1)[1]
            value = float(model.getVal(variables[name]))
            if not math.isfinite(value):
                return "error", None
            if VARIABLE_DOMAINS[name] in {"integer", "binary"}:
                value = float(round(value))
            complete["variables"][name] = value
            values[name] = value
        for name in VARIABLE_DOMAINS:
            values.setdefault(name, complete["variables"][name])
        complete["objective"] = self.public.objective(values)
        complete["state"]["solver_status"] = status
        complete["state"]["solution_count"] = int(model.getNSols())
        complete["state"]["export"] = {"complete": True, "error": None}
        return status, DecisionArtifact.create(complete)


class SupplierNeighborhood:
    def __init__(self, root: Path | str, problem_id: int, time_limit: float = 30.0) -> None:
        self.root = Path(root)
        self.problem_id = int(problem_id)
        self.time_limit = float(time_limit)
        if self.problem_id not in SUPPORTED_IDS:
            raise NotReadyError("problem is outside the reviewed supplier objective adapter")
        self.manifest_path = self.root / "assets/industryor_next_stage/manifest.json"
        try:
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NotReadyError("registered IndustryOR manifest is unavailable") from exc
        qualified = set(self.manifest.get("qualification", {}).get("qualified_ids", []))
        entry = next(
            (row for row in self.manifest.get("problems", []) if row.get("id") == self.problem_id),
            None,
        )
        if self.problem_id not in qualified or entry is None \
                or entry.get("audit", {}).get("qualified") is not True:
            raise NotReadyError("problem lacks a qualified independent business audit")
        question = entry.get("question")
        if not isinstance(question, str) \
                or _sha256(question.encode("utf-8")) != entry.get("question_sha256"):
            raise NotReadyError("registered question hash does not match the public question")
        self.public = supplier_milp(self.problem_id)
        if entry.get("question_sha256") != self.public.question_sha256:
            raise NotReadyError("registered question differs from the reviewed supplier semantics")
        mapping = entry.get("variable_mapping", {})
        if set(mapping) != set(VARIABLE_DOMAINS):
            raise NotReadyError("registered variable mapping does not match the reviewed variables")
        for name, domain in VARIABLE_DOMAINS.items():
            row = mapping[name]
            if row.get("domain") != domain or row.get("required_for_audit") is not True \
                    or row.get("observed_in_initial_export") is not True:
                raise NotReadyError(f"registered variable mapping is not ready: {name}")
        self.graph = self.public.dependency_graph()
        self.solver: Optional[SupplierSCIPSolver] = None
        self.business_audit_calls = 0
        self.business_audit_seconds = 0.0

    def artifact(self, raw: bytes, sha256: str = "") -> DecisionArtifact:
        return artifact_from_bytes(raw, sha256)

    def score(self, artifact: DecisionArtifact) -> dict[str, Any]:
        self.business_audit_calls += 1
        started = time.perf_counter()
        try:
            return score_solution(self.problem_id, solution_from_decisions(artifact.decisions))
        finally:
            self.business_audit_seconds += time.perf_counter() - started

    def _validate_parent(self, score: Mapping[str, Any]) -> str:
        if not business_feasible(score):
            raise NotReadyError("root is outside joint objective-error repair: parent is not fully feasible")
        if score.get("business_correct") is True:
            if score.get("violations") != [] or score.get("optimality") != "proven_optimal" \
                    or score.get("model_objective_consistent") is not True:
                raise NotReadyError("correct parent has an unaccounted independent audit")
            return "correct"
        if list(score.get("violations", [])) != OBJECTIVE_FAILURE_VIOLATIONS \
                or score.get("optimality") != "suboptimal" \
                or score.get("model_objective_consistent") is not False:
            raise NotReadyError(
                "root is outside joint objective-error and suboptimality repair; "
                "ordinary constraint, domain, execution, and unknown failures are not_ready"
            )
        return "objective_failure"

    def _violation_keys(self) -> list[ViolationKey]:
        return [
            _objective_key(self.problem_id, "independent_optimality"),
            _objective_key(self.problem_id, "model_objective_consistency"),
        ]

    def build_spec(
        self,
        parent: DecisionArtifact,
        parent_score: Mapping[str, Any],
        arm: str,
    ) -> NeighborhoodSpec:
        if arm not in {DIRECT_FULL, DECLARATIVE}:
            raise ValueError("a declarative spec requires direct-full or declarative arm")
        if self._validate_parent(parent_score) != "objective_failure":
            raise NotReadyError("a correct root has an empty repair neighborhood")
        variable_names = tuple(_path(name) for name in VARIABLE_DOMAINS)
        direct = arm == DIRECT_FULL
        return build_neighborhood(
            parent,
            [] if direct else self._violation_keys(),
            self.graph,
            variable_names=variable_names,
            seed_variables=variable_names if direct else (),
            mode=OBJECTIVE_OPTIMIZATION,
            objective_sense="minimize",
        )

    def _get_solver(self) -> SupplierSCIPSolver:
        if self.solver is None:
            self.solver = SupplierSCIPSolver(self.public, self.time_limit)
        return self.solver

    def _bookkeeping_candidate(self, parent: DecisionArtifact) -> DecisionArtifact:
        decisions = copy.deepcopy(parent.decisions)
        decisions["objective"] = self.public.objective(decisions["variables"])
        return DecisionArtifact.create(decisions)

    def _candidate_record(
        self,
        candidate_id: str,
        operation: str,
        parent: DecisionArtifact,
        candidate: DecisionArtifact,
        score: Mapping[str, Any],
        spec: Optional[NeighborhoodSpec],
        solver_status: Optional[str],
        started: float,
    ) -> dict[str, Any]:
        changed_variables = sorted(
            name for name in VARIABLE_DOMAINS
            if parent.decisions["variables"][name] != candidate.decisions["variables"][name]
        )
        changed_fields = []
        if parent.decisions["objective"] != candidate.decisions["objective"]:
            changed_fields.append("objective")
        changed_fields.extend(f"variables.{name}" for name in changed_variables)
        if parent.decisions["state"] != candidate.decisions["state"]:
            changed_fields.append("state")
        accepted = score.get("business_correct") is True
        reason = None if accepted else (
            "still_suboptimal" if score.get("optimality") == "suboptimal"
            else "independent_business_audit_failed"
        )
        return {
            "candidate_id": candidate_id,
            "parent_candidate_id": "explicit-root",
            "parent_sha256": parent.sha256,
            "candidate_sha256": candidate.sha256,
            "operation": operation,
            "artifact": candidate.to_dict(),
            "independent_audit": copy.deepcopy(dict(score)),
            "spec": spec.to_dict() if spec is not None else None,
            "dependency_graph_sha256": self.graph.sha256,
            "solver_status": solver_status,
            "changed_variables": changed_variables,
            "changed_fields": changed_fields,
            "changed_variable_count": len(changed_variables),
            "accepted": accepted,
            "rejection_reason": reason,
            "selected": False,
            "cost": {
                "wall_seconds": time.perf_counter() - started,
                "scip_runs": 1 if solver_status is not None else 0,
                "business_audit_calls": 1,
                "llm_calls": 0,
                "llm_tokens": 0,
            },
        }

    def repair(
        self,
        parent: DecisionArtifact,
        parent_score: Mapping[str, Any],
        arm: str,
    ) -> dict[str, Any]:
        if arm not in ARMS:
            raise ValueError(f"unsupported supplier repair arm: {arm}")
        started = time.perf_counter()
        parent_kind = self._validate_parent(parent_score)
        base = {
            "arm": arm,
            "repair_class": "joint_objective_consistency_and_suboptimality_repair",
            "ordinary_constraint_narrow_repair": False,
            "parent_sha256": parent.sha256,
            "parent_artifact_sha256_matches_original_bytes": parent.sha256 == _sha256(parent.raw_bytes),
            "dependency_graph": self.graph.to_dict(),
            "dependency_graph_sha256": self.graph.sha256,
            "public_answer_used_for_repair_or_selection": False,
            "public_answer_scored": False,
            "final_independent_audit": None,
        }
        if parent_kind == "correct":
            return {
                **base,
                "status": "ready",
                "reason": "correct_root_preserved_without_solver",
                "selected_candidate_id": "explicit-root",
                "selected_sha256": parent.sha256,
                "selected": parent.to_dict(),
                "selected_independent_audit": copy.deepcopy(dict(parent_score)),
                "candidate_lineage": [],
                "pareto": {"frontier_candidate_ids": ["explicit-root"]} if arm == PARETO else None,
                "business_recovered": False,
                "correct_root_preserved": True,
                "cost": {
                    "candidate_evaluations": 0,
                    "business_audit_calls": 0,
                    "business_audit_seconds": 0.0,
                    "scip_runs": 0,
                    "scip_wall_seconds": 0.0,
                    "wall_seconds": time.perf_counter() - started,
                    "llm_calls": 0,
                    "llm_tokens": 0,
                },
            }

        candidates = []
        if arm == PARETO:
            candidate_started = time.perf_counter()
            bookkeeping = self._bookkeeping_candidate(parent)
            bookkeeping_score = self.score(bookkeeping)
            candidates.append(self._candidate_record(
                "objective-bookkeeping",
                "objective_bookkeeping_only",
                parent,
                bookkeeping,
                bookkeeping_score,
                None,
                None,
                candidate_started,
            ))

        spec_arm = DIRECT_FULL if arm == DIRECT_FULL else DECLARATIVE
        spec = self.build_spec(parent, parent_score, spec_arm)
        candidate_started = time.perf_counter()
        solver_status, candidate = self._get_solver()(spec)
        if candidate is None:
            raise NotReadyError(f"supplier MILP returned no candidate: {solver_status}")
        candidate_score = self.score(candidate)
        operation = "full_milp_reoptimization"
        candidate_id = {
            DIRECT_FULL: "direct-full-reoptimization",
            DECLARATIVE: "declarative-reoptimization",
            PARETO: "pareto-full-reoptimization",
        }[arm]
        candidates.append(self._candidate_record(
            candidate_id,
            operation,
            parent,
            candidate,
            candidate_score,
            spec,
            solver_status,
            candidate_started,
        ))

        pareto = None
        if arm == PARETO:
            archive = [{
                "candidate_id": "explicit-root",
                "business_objective": parent_score["business_objective"],
                "violation_count": len(parent_score["violations"]),
                "changed_variable_count": 0,
            }]
            archive.extend({
                "candidate_id": row["candidate_id"],
                "business_objective": row["independent_audit"]["business_objective"],
                "violation_count": len(row["independent_audit"]["violations"]),
                "changed_variable_count": row["changed_variable_count"],
            } for row in candidates)

            def dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
                metrics = ("violation_count", "business_objective", "changed_variable_count")
                return all(left[key] <= right[key] for key in metrics) \
                    and any(left[key] < right[key] for key in metrics)

            dominated_by = {}
            for row in archive:
                dominator = next(
                    (other["candidate_id"] for other in archive
                     if other["candidate_id"] != row["candidate_id"] and dominates(other, row)),
                    None,
                )
                if dominator is not None:
                    dominated_by[row["candidate_id"]] = dominator
            pareto = {
                "minimized_metrics": [
                    "independent_violation_count",
                    "independently_recomputed_business_objective",
                    "changed_variable_count",
                ],
                "metrics_by_candidate_id": {row["candidate_id"]: row for row in archive},
                "frontier_candidate_ids": [
                    row["candidate_id"] for row in archive
                    if row["candidate_id"] not in dominated_by
                ],
                "dominated_by": dominated_by,
                "root_dominated_by": dominated_by.get("explicit-root"),
                "selection_rule": (
                    "among business_correct candidates only: minimum independent business objective, "
                    "then changed-variable count, then SHA256; otherwise retain explicit root"
                ),
                "pareto_front_alone_does_not_establish_business_correctness": True,
            }

        eligible = [row for row in candidates if row["accepted"]]
        if eligible:
            selected_record = min(
                eligible,
                key=lambda row: (
                    row["independent_audit"]["business_objective"],
                    row["changed_variable_count"],
                    row["candidate_sha256"],
                ),
            )
            selected_record["selected"] = True
            selected = DecisionArtifact.from_dict(selected_record["artifact"])
            selected_score = selected_record["independent_audit"]
            selected_candidate_id = selected_record["candidate_id"]
            status = "ready"
            reason = "independently_verified_objective_recovery"
        else:
            selected = parent
            selected_score = copy.deepcopy(dict(parent_score))
            selected_candidate_id = "explicit-root"
            status = "not_ready"
            reason = "no_business_correct_candidate; explicit failure root retained"
        runs = self.solver.runs if self.solver is not None else 0
        solver_seconds = self.solver.wall_seconds if self.solver is not None else 0.0
        return {
            **base,
            "status": status,
            "reason": reason,
            "selected_candidate_id": selected_candidate_id,
            "selected_sha256": selected.sha256,
            "selected": selected.to_dict(),
            "selected_independent_audit": selected_score,
            "candidate_lineage": candidates,
            "pareto": pareto,
            "business_recovered": bool(
                parent_score.get("business_correct") is False
                and selected_score.get("business_correct") is True
                and selected.sha256 != parent.sha256
            ),
            "correct_root_preserved": None,
            "cost": {
                "candidate_evaluations": len(candidates),
                "business_audit_calls": self.business_audit_calls,
                "business_audit_seconds": self.business_audit_seconds,
                "scip_runs": runs,
                "scip_wall_seconds": solver_seconds,
                "wall_seconds": time.perf_counter() - started,
                "llm_calls": 0,
                "llm_tokens": 0,
            },
        }

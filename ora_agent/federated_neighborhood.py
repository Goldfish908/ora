"""Declarative sub-MILP neighborhoods for federated cohort decisions."""
from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Callable, Mapping

from .declarative_neighborhood import (
    DECISION_REPAIR,
    DecisionArtifact,
    DependencyGraph,
    NeighborhoodError,
    NeighborhoodSpec,
    RepairResult,
    ViolationKey,
    build_neighborhood,
    repair_neighborhood,
)
from .federated_public_ir import (
    CLIENT_UNIQUE,
    GPU_BUDGET,
    PRIVACY_BUDGET,
    STREAM_CLIENTS,
    STREAM_ENCLAVES,
    STREAM_EXAMPLES,
    UPLOAD_BUDGET,
    FederatedPublicChecker,
    PublicProblem,
    all_variable_names,
    decisions_to_artifact,
    decisions_to_solution_bytes,
    load_public_files,
    load_public_problem,
    pair_key,
    solution_file_to_artifact,
    solution_to_artifact,
    split_variable_name,
    variable_name,
)

SOLVER_VERSION = "federated_sub_milp_v0.1"


def _bind(bindings: dict[str, tuple[str, ...]], requirement_id: str, index,
          rule_parts: tuple[str, ...], names: list[str] | tuple[str, ...]) -> None:
    for rule_part in rule_parts:
        key = ViolationKey(requirement_id, tuple(str(item) for item in index), rule_part).stable_key
        bindings[key] = tuple(sorted(names))


def build_dependency_graph(decisions: Mapping | None = None,
                           public_files: dict[str, str] | None = None) -> DependencyGraph:
    """Bind every encoded constraint violation and connect alternatives for the same client.

    Budget bindings use the parent's positive contributors when decisions are supplied. This
    avoids releasing unrelated, already-zero clients merely because a global budget is tight.
    """
    problem = load_public_problem(public_files)
    names_by_pair = {
        pair: variable_name(*pair) for pair in problem.pair_order
    }
    selected = decisions.get("selected", {}) if isinstance(decisions, Mapping) else {}
    bindings = {}
    adjacency = {}
    for client_id, pairs in problem.by_client.items():
        names = [names_by_pair[pair] for pair in pairs]
        _bind(bindings, CLIENT_UNIQUE, (client_id,),
              ("capacity", "numeric_inputs"), names)
        for name in names:
            adjacency[name] = tuple(sorted(other for other in names if other != name))
    for stream_id, pairs in problem.by_stream.items():
        names = [names_by_pair[pair] for pair in pairs]
        for requirement_id in (STREAM_CLIENTS, STREAM_EXAMPLES, STREAM_ENCLAVES):
            _bind(bindings, requirement_id, (stream_id,),
                  ("minimum_flow", "capacity", "numeric_inputs"), names)
    if isinstance(decisions, Mapping) and isinstance(selected, Mapping):
        contributing = [
            names_by_pair[pair] for pair in problem.pair_order
            if selected.get(pair_key(*pair)) == 1 and not isinstance(selected.get(pair_key(*pair)), bool)
        ]
    else:
        contributing = [names_by_pair[pair] for pair in problem.pair_order]
    for requirement_id in (PRIVACY_BUDGET, UPLOAD_BUDGET, GPU_BUDGET):
        _bind(bindings, requirement_id, ("sprint",),
              ("capacity", "numeric_inputs"), contributing)
    return DependencyGraph(bindings, adjacency)


def _as_artifact(parent, public_files: dict[str, str]) -> DecisionArtifact:
    if isinstance(parent, DecisionArtifact):
        return parent
    if isinstance(parent, (str, bytes)):
        return solution_to_artifact(parent, public_files)
    if isinstance(parent, Mapping):
        return decisions_to_artifact(parent, public_files)
    raise NeighborhoodError("federated parent must be CSV bytes/text, decisions, or DecisionArtifact")


def _fixed_binary_values(spec: NeighborhoodSpec) -> dict[str, int]:
    values = {}
    for name in spec.fixed_variables:
        value = spec.fixed_values[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value) or value not in {0, 1}:
            raise NeighborhoodError(f"fixed federated variable is not binary: {name}")
        values[name] = int(value)
    return values


def solve_sub_milp(spec: NeighborhoodSpec, public_files: dict[str, str] | None = None,
                   *, time_limit_seconds: float = 60.0, relative_gap: float = 0.0005) -> dict:
    """Solve the full public formulation with every non-neighborhood variable fixed."""
    if not isinstance(time_limit_seconds, (int, float)) or isinstance(time_limit_seconds, bool) \
            or not math.isfinite(time_limit_seconds) or time_limit_seconds <= 0:
        raise NeighborhoodError("time_limit_seconds must be a finite positive number")
    if not isinstance(relative_gap, (int, float)) or isinstance(relative_gap, bool) \
            or not math.isfinite(relative_gap) or relative_gap < 0:
        raise NeighborhoodError("relative_gap must be a finite nonnegative number")
    try:
        from pyscipopt import Model, quicksum
    except ImportError as exc:
        raise RuntimeError("PySCIPOpt is required for federated sub-MILP repair") from exc

    files = load_public_files() if public_files is None else public_files
    problem = load_public_problem(files)
    variable_names = all_variable_names(files)
    if set(spec.released_variables).union(spec.fixed_variables) != set(variable_names):
        raise NeighborhoodError("neighborhood does not partition the complete federated decision vector")
    fixed = _fixed_binary_values(spec)
    released = set(spec.released_variables)
    model = Model(f"federated_neighborhood_{spec.parent_sha256[:12]}")
    model.hideOutput()
    model.setRealParam("limits/gap", float(relative_gap))
    model.setRealParam("limits/time", float(time_limit_seconds))
    variables = {}
    for name in variable_names:
        if name in released:
            variables[name] = model.addVar(name=name, vtype="B")
        else:
            value = fixed[name]
            variables[name] = model.addVar(name=name, vtype="B", lb=value, ub=value)

    def pair_expression(pairs, coefficient: Callable[[tuple[str, str]], float]):
        return quicksum(
            coefficient(pair) * variables[variable_name(*pair)] for pair in pairs
        )

    for client_id, pairs in problem.by_client.items():
        model.addCons(pair_expression(pairs, lambda pair: 1.0) <= 1.0,
                      name=f"unique_{client_id}")
    for stream_id, pairs in problem.by_stream.items():
        stream = problem.streams[stream_id]
        count = pair_expression(pairs, lambda pair: 1.0)
        model.addCons(count >= float(stream["min_clients"]), name=f"min_clients_{stream_id}")
        model.addCons(count <= float(stream["max_clients"]), name=f"max_clients_{stream_id}")
        model.addCons(
            pair_expression(pairs, lambda pair: float(problem.scores[pair]["examples"]))
            >= float(stream["min_examples"]),
            name=f"examples_{stream_id}",
        )
        model.addCons(
            pair_expression(
                pairs, lambda pair: float(problem.clients[pair[0]]["secure_enclave"]))
            >= float(stream["min_secure_enclave_clients"]),
            name=f"enclaves_{stream_id}",
        )
    all_pairs = problem.pair_order
    model.addCons(
        pair_expression(all_pairs, lambda pair: float(problem.clients[pair[0]]["privacy_cost"]))
        <= float(problem.config["privacy_budget"]),
        name="privacy_budget",
    )
    model.addCons(
        pair_expression(all_pairs, lambda pair: float(problem.scores[pair]["upload_mb"]))
        <= float(problem.config["upload_budget_mb"]),
        name="upload_budget",
    )
    model.addCons(
        pair_expression(all_pairs, lambda pair: float(problem.scores[pair]["gpu_minutes"]))
        <= float(problem.config["gpu_minutes_budget"]),
        name="gpu_budget",
    )

    def objective_coefficient(pair: tuple[str, str]) -> float:
        score = problem.scores[pair]
        return (float(score["expected_model_gain"])
                - float(problem.clients[pair[0]]["privacy_cost"])
                - float(score["gpu_minutes"]) * float(problem.config["gpu_minute_cost"])
                - float(score["upload_mb"]) * float(problem.config["upload_mb_cost"]))

    model.setObjective(pair_expression(all_pairs, objective_coefficient), "maximize")
    started = time.perf_counter()
    model.optimize()
    elapsed = time.perf_counter() - started
    solver_status = str(model.getStatus()).lower()
    base = {
        "parent_sha256": spec.parent_sha256,
        "solver_status": solver_status,
        "solver_version": SOLVER_VERSION,
        "solve_seconds": elapsed,
        "node_count": model.getNNodes(),
        "released_variable_count": len(spec.released_variables),
        "fixed_variable_count": len(spec.fixed_variables),
        "veto_enabled": False,
    }
    if model.getNSols() == 0:
        return {"status": solver_status, **base}
    solution = model.getBestSol()
    values = {}
    for name in spec.released_variables:
        value = float(model.getSolVal(solution, variables[name]))
        rounded = round(value)
        if abs(value - rounded) > 1e-6:
            return {"status": "failed", "reason": "non_integral_solver_value", **base}
        values[name] = int(rounded)
    complete_selected = {}
    for pair in problem.pair_order:
        name = variable_name(*pair)
        complete_selected[pair_key(*pair)] = values[name] if name in released else fixed[name]
    raw_bytes = decisions_to_solution_bytes({"selected": complete_selected}, files)
    status = "optimal" if solver_status == "optimal" else "feasible"
    return {
        "status": status,
        "values": values,
        "raw_bytes": raw_bytes,
        "scip_objective": float(model.getSolObjVal(solution)),
        "primal_bound": float(model.getPrimalbound()),
        "dual_bound": float(model.getDualbound()),
        **base,
    }


class FederatedNeighborhoodRepair:
    def __init__(self, public_files: dict[str, str] | None = None, *,
                 time_limit_seconds: float = 60.0, relative_gap: float = 0.0005) -> None:
        self.public_files = load_public_files() if public_files is None else public_files
        self.problem: PublicProblem = load_public_problem(self.public_files)
        self.checker = FederatedPublicChecker(self.public_files)
        self.variable_names = all_variable_names(self.public_files)
        self.time_limit_seconds = time_limit_seconds
        self.relative_gap = relative_gap

    def artifact(self, parent) -> DecisionArtifact:
        return _as_artifact(parent, self.public_files)

    def graph(self, parent=None) -> DependencyGraph:
        decisions = None if parent is None else self.artifact(parent).decisions
        return build_dependency_graph(decisions, self.public_files)

    def build(self, parent, violations=None, **kwargs) -> NeighborhoodSpec:
        artifact = self.artifact(parent)
        if violations is None:
            violations = self.checker.check(artifact.decisions)["violations"]
        kwargs.setdefault("variable_names", self.variable_names)
        kwargs.setdefault("objective_sense", self.checker.ir.objective_sense)
        return build_neighborhood(
            artifact, violations, self.graph(artifact), **kwargs,
        )

    def solve(self, spec: NeighborhoodSpec) -> dict:
        return solve_sub_milp(
            spec, self.public_files,
            time_limit_seconds=self.time_limit_seconds,
            relative_gap=self.relative_gap,
        )

    def repair(self, parent, *, mode: str = DECISION_REPAIR, seed_variables=(),
               checkpoint=None, solver: Callable[[NeighborhoodSpec], object] | None = None,
               objective_tolerance: float = 1e-9) -> RepairResult:
        artifact = self.artifact(parent)
        retained = None if checkpoint is None else self.artifact(checkpoint)
        return repair_neighborhood(
            artifact,
            self.graph(artifact),
            self.checker.check,
            self.solve if solver is None else solver,
            variable_names=self.variable_names,
            seed_variables=seed_variables,
            mode=mode,
            objective_sense=self.checker.ir.objective_sense,
            objective_tolerance=objective_tolerance,
            checkpoint=retained,
        )


def repair_federated_solution(parent, public_files: dict[str, str] | None = None, *,
                              time_limit_seconds: float = 60.0, relative_gap: float = 0.0005,
                              mode: str = DECISION_REPAIR, seed_variables=(), checkpoint=None,
                              solver: Callable[[NeighborhoodSpec], object] | None = None) -> RepairResult:
    return FederatedNeighborhoodRepair(
        public_files, time_limit_seconds=time_limit_seconds, relative_gap=relative_gap,
    ).repair(
        parent, mode=mode, seed_variables=seed_variables, checkpoint=checkpoint, solver=solver,
    )


def repair_federated_solution_file(path: str | Path, public_files: dict[str, str] | None = None,
                                   **kwargs) -> RepairResult:
    files = load_public_files() if public_files is None else public_files
    return repair_federated_solution(solution_file_to_artifact(path, files), files, **kwargs)

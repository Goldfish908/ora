"""Fail-closed IndustryOR decision neighborhoods from reviewed public semantics."""
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
    DECISION_REPAIR,
    DecisionArtifact,
    DependencyGraph,
    NeighborhoodSpec,
    RepairResult,
    ViolationKey,
    repair_neighborhood,
)
from scripts.industryor_next_stage import score_solution

SOLUTION_SCHEMA = "industryor.solution.v1"
ID9_QUESTION_SHA256 = "bc5f7c924a5574dda81b157fef88f1644f22862a2428ec0e76ebc85f95fa87d0"


class NotReadyError(ValueError):
    pass


def _path(name: str) -> str:
    return f"variables.{name}"


def constraint_key(problem_id: int, rule: str) -> ViolationKey:
    return ViolationKey(f"industryor.{problem_id}.{rule}", ("public",), "constraint")


def domain_key(problem_id: int, name: str) -> ViolationKey:
    return ViolationKey(f"industryor.{problem_id}.domain", (name,), "domain")


def execution_key(problem_id: int, name: str) -> ViolationKey:
    return ViolationKey(f"industryor.{problem_id}.execution", (name,), "execution")


def objective_key(problem_id: int, part: str) -> ViolationKey:
    return ViolationKey(f"industryor.{problem_id}.objective", ("global",), part)


@dataclass(frozen=True)
class LinearConstraint:
    rule: str
    coefficients: Mapping[str, float]
    sense: str
    rhs: float
    source: str

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "coefficients": dict(self.coefficients),
            "sense": self.sense,
            "rhs": self.rhs,
            "source": self.source,
        }


@dataclass(frozen=True)
class PublicMILP:
    problem_id: int
    question_sha256: str
    domains: Mapping[str, str]
    bounds: Mapping[str, tuple[float, float]]
    objective: Mapping[str, float]
    objective_sense: str
    constraints: tuple[LinearConstraint, ...]

    def to_dict(self) -> dict:
        return {
            "problem_id": self.problem_id,
            "question_sha256": self.question_sha256,
            "domains": dict(self.domains),
            "bounds": {name: list(value) for name, value in self.bounds.items()},
            "objective": dict(self.objective),
            "objective_sense": self.objective_sense,
            "constraints": [row.to_dict() for row in self.constraints],
        }

    def dependency_graph(self) -> DependencyGraph:
        bindings: dict[str, set[str]] = {}
        adjacency: dict[str, set[str]] = {_path(name): set() for name in self.domains}
        for name in self.domains:
            bindings[domain_key(self.problem_id, name).stable_key] = {_path(name)}
        for row in self.constraints:
            names = {_path(name) for name in row.coefficients}
            key = constraint_key(self.problem_id, row.rule).stable_key
            bindings.setdefault(key, set()).update(names)
            for name in names:
                adjacency[name].update(names - {name})
        return DependencyGraph(
            {key: sorted(names) for key, names in bindings.items()},
            {key: sorted(names) for key, names in adjacency.items()},
        )


def _row(rule: str, coefficients: Mapping[str, float], sense: str, rhs: float,
         source: str) -> LinearConstraint:
    return LinearConstraint(rule, coefficients, sense, float(rhs), source)


def _id9_milp(question: str, question_sha256: str) -> PublicMILP:
    wood_source = (
        "There are 890 units of wood available. Each truck requires 12 units, "
        "each airplane 20 units, each boat 15 units, and each train 10 units."
    )
    steel_source = (
        "There are 500 units of steel available. Each airplane requires 3 units, "
        "each boat 5 units, each train 4 units, and each truck 6 units."
    )
    exclusion_source = "If Haus Toys manufactures trucks, they will not manufacture trains."
    implication_source = "However, if they manufacture boats, they will also manufacture airplanes."
    quantity_source = "The number of toy boats manufactured cannot exceed the number of toy trains manufactured."
    for source in (wood_source, steel_source, exclusion_source, implication_source, quantity_source):
        if source not in question:
            raise NotReadyError("ID9 public source excerpt is missing")
    link_1 = "registered audit link_x1_y1 and manifest meanings for x1/y1"
    link_3 = "registered audit link_x3_y2 and manifest meanings for x3/y2"
    constraints = (
        _row("wood", {"x1": 12, "x2": 20, "x3": 15, "x4": 10}, "<=", 890, wood_source),
        _row("steel", {"x1": 6, "x2": 3, "x3": 5, "x4": 4}, "<=", 500, steel_source),
        _row("first_excludes_fourth", {"x4": 1, "y1": 89}, "<=", 89, exclusion_source),
        _row("boats_imply_airplanes", {"x2": 1, "y2": -1}, ">=", 0, implication_source),
        _row("boats_no_greater_than_trains", {"x3": 1, "x4": -1}, "<=", 0, quantity_source),
        _row("link_x1_y1", {"x1": 1, "y1": -74}, "<=", 0, link_1),
        _row("link_x1_y1", {"x1": 1, "y1": -1}, ">=", 0, link_1),
        _row("link_x3_y2", {"x3": 1, "y2": -59}, "<=", 0, link_3),
        _row("link_x3_y2", {"x3": 1, "y2": -1}, ">=", 0, link_3),
    )
    return PublicMILP(
        problem_id=9,
        question_sha256=question_sha256,
        domains={"x1": "integer", "x2": "integer", "x3": "integer", "x4": "integer",
                 "y1": "binary", "y2": "binary"},
        bounds={"x1": (0, 74), "x2": (0, 44), "x3": (0, 59), "x4": (0, 89),
                "y1": (0, 1), "y2": (0, 1)},
        objective={"x1": 5, "x2": 10, "x3": 8, "x4": 7},
        objective_sense="maximize",
        constraints=constraints,
    )


def solution_from_decisions(decisions: Mapping[str, Any]) -> dict:
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


def artifact_from_bytes(raw: bytes, required_domains: Mapping[str, str],
                        sha256: str = "") -> DecisionArtifact:
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
    for name, value in variables.items():
        if not isinstance(name, str) or not name or "." in name:
            raise NotReadyError("parent contains an unsupported variable path")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise NotReadyError("parent contains a non-finite decision value")
    expected_types = {"integer": "INTEGER", "binary": "BINARY", "continuous": "CONTINUOUS"}
    for name, domain in required_domains.items():
        if name not in variables or types.get(name) != expected_types[domain]:
            raise NotReadyError(f"required variable or declared domain is unavailable: {name}")
    objective = solution.get("objective")
    if isinstance(objective, bool) or not isinstance(objective, (int, float)) \
            or not math.isfinite(objective):
        raise NotReadyError("parent model objective is unavailable")
    state = {key: copy.deepcopy(value) for key, value in solution.items()
             if key not in {"variables", "objective"}}
    decisions = {"variables": copy.deepcopy(variables), "objective": objective, "state": state}
    return DecisionArtifact.create(decisions, raw_bytes=raw, sha256=sha256)


class SCIPSubMILPSolver:
    def __init__(self, public: PublicMILP, time_limit: float = 30.0) -> None:
        try:
            import pyscipopt
        except ImportError as exc:
            raise NotReadyError("PySCIPOpt is required for the real sub-MILP experiment") from exc
        self.public = public
        self.time_limit = float(time_limit)
        self.pyscipopt = pyscipopt
        self.runs = 0
        self.wall_seconds = 0.0

    def __call__(self, spec: NeighborhoodSpec) -> dict:
        parent = artifact_from_bytes(spec.parent_bytes, self.public.domains, spec.parent_sha256)
        released = set(spec.released_variables)
        semantic_paths = {_path(name) for name in self.public.domains}
        if not released.issubset(semantic_paths):
            raise NotReadyError("an opaque exported variable cannot be released by the ID9 adapter")
        model = self.pyscipopt.Model(f"industryor_{self.public.problem_id}_sub_milp")
        model.hideOutput()
        model.setRealParam("limits/time", self.time_limit)
        variables = {}
        for name, domain in self.public.domains.items():
            lower, upper = self.public.bounds[name]
            vtype = {"integer": "I", "binary": "B", "continuous": "C"}[domain]
            variables[name] = model.addVar(name=name, vtype=vtype, lb=lower, ub=upper)
            path = _path(name)
            if path in spec.fixed_values:
                model.addCons(variables[name] == spec.fixed_values[path], f"fixed_{name}")
            elif path not in released:
                raise NotReadyError(f"semantic variable is neither fixed nor released: {name}")
        for index, row in enumerate(self.public.constraints):
            expression = sum(coefficient * variables[name]
                             for name, coefficient in row.coefficients.items())
            if row.sense == "<=":
                constraint = expression <= row.rhs
            elif row.sense == ">=":
                constraint = expression >= row.rhs
            else:
                raise NotReadyError(f"unsupported public constraint sense: {row.sense}")
            model.addCons(constraint, f"public_{index}_{row.rule}")
        model.setObjective(
            sum(coefficient * variables[name] for name, coefficient in self.public.objective.items()),
            self.public.objective_sense,
        )
        started = time.monotonic()
        self.runs += 1
        model.optimize()
        self.wall_seconds += time.monotonic() - started
        status = str(model.getStatus())
        if model.getNSols() < 1:
            return {"status": status, "parent_sha256": spec.parent_sha256}
        complete = copy.deepcopy(parent.decisions)
        for path in spec.released_variables:
            name = path.split(".", 1)[1]
            value = float(model.getVal(variables[name]))
            if not math.isfinite(value):
                return {"status": "error", "parent_sha256": spec.parent_sha256}
            if self.public.domains[name] in {"integer", "binary"}:
                value = float(round(value))
            complete["variables"][name] = value
        complete["objective"] = float(model.getObjVal())
        complete["state"]["solver_status"] = status
        complete["state"]["solution_count"] = int(model.getNSols())
        complete["state"]["export"] = {"complete": True, "error": None}
        return {"status": status, "decisions": complete, "parent_sha256": spec.parent_sha256}


class IndustryORNeighborhood:
    def __init__(self, root: Path | str, problem_id: int, time_limit: float = 30.0) -> None:
        self.root = Path(root)
        self.problem_id = int(problem_id)
        self.time_limit = float(time_limit)
        self.manifest_path = self.root / "assets/industryor_next_stage/manifest.json"
        self.dataset_path = self.root / "data/industryor/IndustryOR.json"
        try:
            self.manifest = json.loads(self.manifest_path.read_text())
            rows = json.loads(self.dataset_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise NotReadyError("public IndustryOR registry or dataset is unavailable") from exc
        qualified = set(self.manifest.get("qualification", {}).get("qualified_ids", []))
        if self.problem_id not in qualified:
            raise NotReadyError("problem lacks a qualified independent business audit")
        entry = next((item for item in self.manifest.get("problems", [])
                      if item.get("id") == self.problem_id), None)
        if entry is None or entry.get("audit", {}).get("qualified") is not True:
            raise NotReadyError("registered problem has no qualified manifest entry")
        row = next((item for item in rows if item.get("id") == self.problem_id), None)
        if row is None or not isinstance(row.get("en_question"), str):
            raise NotReadyError("public question is unavailable")
        self.question = row["en_question"]
        if self.question != entry.get("question"):
            raise NotReadyError("dataset and registered manifest questions differ")
        digest = hashlib.sha256(self.question.encode("utf-8")).hexdigest()
        if digest != entry.get("question_sha256"):
            raise NotReadyError("registered question hash does not match the public question")
        if self.problem_id != 9 or digest != ID9_QUESTION_SHA256:
            raise NotReadyError("no reviewed public MILP adapter for this registered problem")
        self.public = _id9_milp(self.question, digest)
        mapping = entry.get("variable_mapping", {})
        for name, domain in self.public.domains.items():
            if mapping.get(name, {}).get("domain") != domain \
                    or mapping.get(name, {}).get("required_for_audit") is not True:
                raise NotReadyError(f"registered variable mapping is not ready: {name}")
        self.graph = self.public.dependency_graph()
        self.solver: Optional[SCIPSubMILPSolver] = None
        self.business_audit_calls = 0

    def artifact(self, raw: bytes, sha256: str = "") -> DecisionArtifact:
        return artifact_from_bytes(raw, self.public.domains, sha256)

    def business_report(self, decisions: Mapping[str, Any]) -> dict:
        self.business_audit_calls += 1
        try:
            score = score_solution(self.problem_id, solution_from_decisions(decisions))
        except Exception as exc:
            return {"business_status": "unknown", "violations": [], "objective": None,
                    "error": f"{type(exc).__name__}: {exc}"}
        violations = []
        accounted = set()
        if score.get("audit_status") == "complete":
            for name, passed in score.get("execution_checks", {}).items():
                if not passed:
                    violations.append(execution_key(self.problem_id, name).to_dict())
                    accounted.add(f"execution check failed: {name}")
            for name, row in score.get("variable_audit", {}).items():
                if not row.get("passed"):
                    violations.append(domain_key(self.problem_id, name).to_dict())
                    accounted.add(f"variable domain failed: {name}")
            for row in score.get("constraint_checks", []):
                if not row.get("passed"):
                    violations.append(constraint_key(self.problem_id, row["rule"]).to_dict())
                    accounted.add(f"business constraint failed: {row['rule']}")
            if score.get("optimality") == "suboptimal":
                violations.append(objective_key(self.problem_id, "independent_optimality").to_dict())
                accounted.add("business objective is not independently optimal")
            if score.get("model_objective_consistent") is False:
                violations.append(objective_key(self.problem_id, "model_objective_consistency").to_dict())
                accounted.add("reported model objective differs from the audited business objective")
        unknown = score.get("audit_status") != "complete" or set(score.get("violations", [])) != accounted
        if unknown or (score.get("business_correct") is False and not violations):
            status = "unknown"
        else:
            status = "pass" if score.get("business_correct") is True else "fail"
        feasible = bool(score.get("execution_checks") and all(score["execution_checks"].values())
                        and all(row.get("passed") for row in score.get("variable_audit", {}).values())
                        and all(row.get("passed") for row in score.get("constraint_checks", [])))
        objective = score.get("business_objective")
        return {
            "business_status": status,
            "violations": violations,
            "objective": objective if isinstance(objective, (int, float)) else None,
            "verdicts": {
                "execution_and_public_constraints": "pass" if feasible else "fail",
                "independent_optimality": score.get("optimality", "not_assessed"),
                "model_objective_consistency": "pass" if score.get("model_objective_consistent") else "fail",
                "registered_business_correct": "pass" if score.get("business_correct") is True else "fail",
            },
            "registered_audit": score,
        }

    def _get_solver(self) -> SCIPSubMILPSolver:
        if self.solver is None:
            self.solver = SCIPSubMILPSolver(self.public, self.time_limit)
        return self.solver

    def repair(self, parent: DecisionArtifact) -> RepairResult:
        parent_report = self.business_report(parent.decisions)
        if parent_report["business_status"] == "unknown":
            raise NotReadyError("parent has no complete, fully accounted registered business audit")
        unsupported = sorted({row["key"] for row in parent_report["violations"]}
                             - set(self.graph.violation_variables))
        if unsupported:
            raise NotReadyError("root is outside the narrow public-constraint adapter: " + ", ".join(unsupported))
        if parent_report["violations"]:
            solver = self._get_solver()
        else:
            solver = self._get_solver

        def cached_checker(decisions: Mapping[str, Any]) -> Mapping[str, Any]:
            if decisions == parent.decisions:
                return parent_report
            return self.business_report(decisions)

        variable_names = [_path(name) for name in parent.decisions["variables"]]
        return repair_neighborhood(
            parent,
            self.graph,
            cached_checker,
            solver,
            variable_names=variable_names,
            mode=DECISION_REPAIR,
        )

"""Declarative, solver-agnostic neighborhood repair with independent acceptance checks."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional, Tuple

SCHEMA_VERSION = "declarative_neighborhood_v0.1"
MODEL_DIAGNOSIS = "model_diagnosis"
DECISION_REPAIR = "decision_repair"
OBJECTIVE_OPTIMIZATION = "objective_optimization"

INPUT_REQUIREMENTS = {
    MODEL_DIAGNOSIS: (
        "model_artifacts",
        "model_diagnostics",
        "model_to_decision_bindings",
    ),
    DECISION_REPAIR: (
        "parent_decisions_and_original_bytes",
        "independent_full_checker_with_stable_violation_keys",
        "violation_variable_bindings_and_dependency_graph",
        "local_solver_callback",
    ),
    OBJECTIVE_OPTIMIZATION: (
        "feasible_parent_decisions_and_original_bytes",
        "independent_full_checker_with_stable_violation_keys",
        "dependency_graph_and_optimization_seed_variables",
        "local_solver_callback",
        "objective_sense_and_independently_recomputed_objectives",
    ),
}


def required_inputs(mode: str) -> Tuple[str, ...]:
    """Return inputs for a task; decision violations alone cannot diagnose a model."""
    try:
        return INPUT_REQUIREMENTS[mode]
    except KeyError as exc:
        raise ValueError("unsupported neighborhood mode: %s" % mode) from exc


class NeighborhoodError(ValueError):
    pass


class EmptyNeighborhoodError(NeighborhoodError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _unique_strings(values: Iterable[str], label: str) -> Tuple[str, ...]:
    result = set()
    for value in values:
        if not isinstance(value, str) or not value:
            raise NeighborhoodError("%s must contain nonempty strings" % label)
        result.add(value)
    return tuple(sorted(result))


@dataclass(frozen=True)
class DecisionArtifact:
    decisions: dict
    raw_bytes: bytes
    sha256: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.decisions, dict):
            raise NeighborhoodError("decisions must be a JSON object")
        decisions = copy.deepcopy(self.decisions)
        try:
            _canonical_bytes(decisions)
        except (TypeError, ValueError) as exc:
            raise NeighborhoodError("decisions must be finite JSON data") from exc
        if not isinstance(self.raw_bytes, bytes):
            raise NeighborhoodError("original decision bytes must be bytes")
        digest = _sha256(self.raw_bytes)
        if self.sha256 and self.sha256 != digest:
            raise NeighborhoodError("parent solution hash does not match original bytes")
        object.__setattr__(self, "decisions", decisions)
        object.__setattr__(self, "sha256", digest)

    @classmethod
    def create(
        cls,
        decisions: Mapping[str, Any],
        raw_bytes: Optional[bytes] = None,
        sha256: str = "",
    ) -> "DecisionArtifact":
        copied = copy.deepcopy(dict(decisions))
        return cls(copied, _canonical_bytes(copied) if raw_bytes is None else raw_bytes, sha256)

    def to_dict(self) -> dict:
        return {
            "decisions": copy.deepcopy(self.decisions),
            "raw_bytes_base64": base64.b64encode(self.raw_bytes).decode("ascii"),
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DecisionArtifact":
        try:
            raw = base64.b64decode(value["raw_bytes_base64"], validate=True)
            return cls(dict(value["decisions"]), raw, value["sha256"])
        except (KeyError, TypeError, ValueError) as exc:
            raise NeighborhoodError("invalid serialized decision artifact") from exc


ParentSolution = DecisionArtifact
FeasibleCheckpoint = DecisionArtifact


@dataclass(frozen=True)
class ViolationKey:
    requirement_id: str
    index: Tuple[str, ...]
    rule_part: str

    def __post_init__(self) -> None:
        if not isinstance(self.requirement_id, str) or not self.requirement_id:
            raise NeighborhoodError("violation requirement_id must be a nonempty string")
        if not isinstance(self.rule_part, str) or not self.rule_part:
            raise NeighborhoodError("violation rule_part must be a nonempty string")
        if isinstance(self.index, (list, tuple)):
            index = tuple(str(item) for item in self.index)
        else:
            index = (str(self.index),)
        object.__setattr__(self, "index", index)

    @property
    def stable_key(self) -> str:
        return json.dumps(
            [self.requirement_id, list(self.index), self.rule_part],
            ensure_ascii=False,
        )

    def to_dict(self) -> dict:
        return {
            "key": self.stable_key,
            "requirement_id": self.requirement_id,
            "index": list(self.index),
            "rule_part": self.rule_part,
        }

    @classmethod
    def from_value(cls, value: Any) -> "ViolationKey":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError as exc:
                raise NeighborhoodError("invalid stable violation key") from exc
            if not isinstance(decoded, list) or len(decoded) != 3:
                raise NeighborhoodError("stable violation key must encode a three-item list")
            value = decoded
        if isinstance(value, Mapping):
            try:
                result = cls(value["requirement_id"], value["index"], value["rule_part"])
            except KeyError as exc:
                raise NeighborhoodError("violation lacks a stable requirement_id/index/rule_part") from exc
            if "key" in value and value["key"] != result.stable_key:
                raise NeighborhoodError("violation key does not match its stable components")
            return result
        if isinstance(value, (list, tuple)) and len(value) == 3:
            return cls(value[0], value[1], value[2])
        raise NeighborhoodError("unsupported violation key")

    @classmethod
    def from_stable_key(cls, value: str) -> "ViolationKey":
        return cls.from_value(value)


def _graph_violation_key(value: Any) -> str:
    return ViolationKey.from_value(value).stable_key


@dataclass(frozen=True)
class DependencyGraph:
    """Violation bindings plus variable adjacency; both edge directions are direct neighbors."""

    violation_variables: Mapping[Any, Iterable[str]] = field(default_factory=dict)
    adjacency: Mapping[str, Iterable[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        bindings = {}
        for key, names in self.violation_variables.items():
            stable = _graph_violation_key(key)
            normalized = _unique_strings(names, "violation variable bindings")
            if stable in bindings and bindings[stable] != normalized:
                raise NeighborhoodError("conflicting bindings for violation: %s" % stable)
            bindings[stable] = normalized
        adjacency = {}
        for name, neighbors in self.adjacency.items():
            if not isinstance(name, str) or not name:
                raise NeighborhoodError("dependency variable names must be nonempty strings")
            adjacency[name] = _unique_strings(neighbors, "dependency neighbors")
        object.__setattr__(self, "violation_variables", bindings)
        object.__setattr__(self, "adjacency", adjacency)

    @classmethod
    def from_dict(cls, value: Any) -> "DependencyGraph":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise NeighborhoodError("dependency graph must be a DependencyGraph or object")
        bindings = value.get(
            "violation_variables", value.get("bindings", value.get("violations", {})),
        )
        adjacency = value.get("adjacency", value.get("neighbors", value.get("variables", {})))
        if "edges" in value:
            merged = {name: set(neighbors) for name, neighbors in adjacency.items()}
            for edge in value["edges"]:
                if not isinstance(edge, (list, tuple)) or len(edge) != 2:
                    raise NeighborhoodError("dependency edges must be variable pairs")
                left, right = edge
                merged.setdefault(left, set()).add(right)
            adjacency = merged
        return cls(bindings, adjacency)

    def to_dict(self) -> dict:
        return {
            "violation_variables": {
                key: list(self.violation_variables[key])
                for key in sorted(self.violation_variables)
            },
            "adjacency": {key: list(self.adjacency[key]) for key in sorted(self.adjacency)},
        }

    @property
    def sha256(self) -> str:
        return _sha256(_canonical_bytes(self.to_dict()))

    def direct_neighbors(self, seeds: Iterable[str]) -> Tuple[str, ...]:
        seeds = set(seeds)
        neighbors = set(seeds)
        for seed in seeds:
            neighbors.update(self.adjacency.get(seed, ()))
        for source, targets in self.adjacency.items():
            if seeds.intersection(targets):
                neighbors.add(source)
        return tuple(sorted(neighbors))


@dataclass(frozen=True)
class NeighborhoodSpec:
    parent_sha256: str
    parent_bytes: bytes
    violation_keys: Tuple[str, ...]
    released_variables: Tuple[str, ...]
    fixed_variables: Tuple[str, ...]
    fixed_values: Mapping[str, Any]
    dependency_graph_sha256: str
    mode: str = DECISION_REPAIR
    objective_sense: Optional[str] = None
    seed_variables: Tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise NeighborhoodError("unsupported neighborhood schema version")
        if not isinstance(self.parent_bytes, bytes) or _sha256(self.parent_bytes) != self.parent_sha256:
            raise NeighborhoodError("neighborhood parent hash does not match original bytes")
        released = _unique_strings(self.released_variables, "released_variables")
        fixed = _unique_strings(self.fixed_variables, "fixed_variables")
        violations = _unique_strings(self.violation_keys, "violation_keys")
        seeds = _unique_strings(self.seed_variables, "seed_variables")
        if not released:
            raise EmptyNeighborhoodError("empty neighborhoods are not executable")
        if set(released).intersection(fixed):
            raise NeighborhoodError("fixed and released variables overlap")
        if set(fixed) != set(self.fixed_values):
            raise NeighborhoodError("fixed_values must exactly match fixed_variables")
        try:
            _canonical_bytes(self.fixed_values)
        except (TypeError, ValueError) as exc:
            raise NeighborhoodError("fixed values must be finite JSON data") from exc
        if self.mode not in {DECISION_REPAIR, OBJECTIVE_OPTIMIZATION}:
            raise NeighborhoodError("model diagnosis is not decision repair; required inputs: %s" % (
                ", ".join(required_inputs(MODEL_DIAGNOSIS)),
            ))
        if self.mode == OBJECTIVE_OPTIMIZATION and self.objective_sense not in {"minimize", "maximize"}:
            raise NeighborhoodError("objective optimization requires minimize/maximize sense")
        if self.mode == DECISION_REPAIR and not violations:
            raise EmptyNeighborhoodError("decision repair requires at least one violation")
        object.__setattr__(self, "released_variables", released)
        object.__setattr__(self, "fixed_variables", fixed)
        object.__setattr__(self, "violation_keys", violations)
        object.__setattr__(self, "seed_variables", seeds)
        object.__setattr__(self, "fixed_values", copy.deepcopy(dict(self.fixed_values)))

    @property
    def free_variables(self) -> Tuple[str, ...]:
        return self.released_variables

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "objective_sense": self.objective_sense,
            "parent_sha256": self.parent_sha256,
            "parent_bytes_base64": base64.b64encode(self.parent_bytes).decode("ascii"),
            "dependency_graph_sha256": self.dependency_graph_sha256,
            "violation_keys": list(self.violation_keys),
            "seed_variables": list(self.seed_variables),
            "released_variables": list(self.released_variables),
            "fixed_variables": list(self.fixed_variables),
            "fixed_values": copy.deepcopy(dict(self.fixed_values)),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, allow_nan=False)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NeighborhoodSpec":
        try:
            raw = base64.b64decode(value["parent_bytes_base64"], validate=True)
            return cls(
                parent_sha256=value["parent_sha256"],
                parent_bytes=raw,
                violation_keys=tuple(value["violation_keys"]),
                released_variables=tuple(value["released_variables"]),
                fixed_variables=tuple(value["fixed_variables"]),
                fixed_values=value["fixed_values"],
                dependency_graph_sha256=value["dependency_graph_sha256"],
                mode=value.get("mode", DECISION_REPAIR),
                objective_sense=value.get("objective_sense"),
                seed_variables=tuple(value.get("seed_variables", ())),
                schema_version=value.get("schema_version", SCHEMA_VERSION),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, NeighborhoodError):
                raise
            raise NeighborhoodError("invalid serialized neighborhood specification") from exc


_MISSING = object()


def _get_path(decisions: Mapping[str, Any], path: str) -> Any:
    if path in decisions:
        return decisions[path]
    current = decisions
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise NeighborhoodError("decision path does not exist: %s" % path) from exc
        else:
            raise NeighborhoodError("decision path does not exist: %s" % path)
    return current


def _set_path(decisions: dict, path: str, value: Any) -> None:
    if path in decisions:
        decisions[path] = copy.deepcopy(value)
        return
    parts = path.split(".")
    current = decisions
    for part in parts[:-1]:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise NeighborhoodError("decision path does not exist: %s" % path) from exc
        else:
            raise NeighborhoodError("decision path does not exist: %s" % path)
    final = parts[-1]
    if isinstance(current, dict) and final in current:
        current[final] = copy.deepcopy(value)
    elif isinstance(current, list):
        try:
            current[int(final)] = copy.deepcopy(value)
        except (ValueError, IndexError) as exc:
            raise NeighborhoodError("decision path does not exist: %s" % path) from exc
    else:
        raise NeighborhoodError("decision path does not exist: %s" % path)


def _same_value(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isfinite(float(left)) and math.isfinite(float(right)) and left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(_same_value(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_value(a, b) for a, b in zip(left, right))
    return left == right


def _as_artifact(
    parent: Any,
    parent_bytes: Optional[bytes] = None,
    parent_sha256: str = "",
) -> DecisionArtifact:
    if isinstance(parent, DecisionArtifact):
        if parent_bytes is not None or parent_sha256:
            raise NeighborhoodError("parent bytes/hash must be supplied either in the artifact or separately")
        return parent
    if not isinstance(parent, Mapping):
        raise NeighborhoodError("parent decisions must be a mapping or DecisionArtifact")
    return DecisionArtifact.create(parent, parent_bytes, parent_sha256)


def build_neighborhood(
    parent: Any,
    violations: Iterable[Any],
    dependency_graph: Any,
    *,
    parent_bytes: Optional[bytes] = None,
    parent_sha256: str = "",
    variable_names: Optional[Iterable[str]] = None,
    seed_variables: Iterable[str] = (),
    mode: str = DECISION_REPAIR,
    objective_sense: Optional[str] = None,
) -> NeighborhoodSpec:
    """Release variables bound to violations/seeds and their one-hop dependencies only."""
    if mode == MODEL_DIAGNOSIS:
        raise NeighborhoodError(
            "model diagnosis requires model artifacts and diagnostics, not a decision neighborhood",
        )
    artifact = _as_artifact(parent, parent_bytes, parent_sha256)
    graph = DependencyGraph.from_dict(dependency_graph)
    violation_keys = tuple(sorted({ViolationKey.from_value(item).stable_key for item in violations}))
    if variable_names is None:
        variables = _unique_strings(artifact.decisions.keys(), "parent decision keys")
    else:
        variables = _unique_strings(variable_names, "variable_names")
    if not variables:
        raise EmptyNeighborhoodError("no decision variables were declared")
    for name in variables:
        _get_path(artifact.decisions, name)
    seeds = set(_unique_strings(seed_variables, "seed_variables"))
    for key in violation_keys:
        bound = graph.violation_variables.get(key)
        if not bound:
            raise NeighborhoodError("violation has no decision-variable binding: %s" % key)
        seeds.update(bound)
    unknown_seeds = seeds.difference(variables)
    if unknown_seeds:
        raise NeighborhoodError("neighborhood seeds are not declared decisions: %s" % ", ".join(sorted(unknown_seeds)))
    released = set(graph.direct_neighbors(seeds))
    unknown_neighbors = released.difference(variables)
    if unknown_neighbors:
        raise NeighborhoodError("dependency neighbors are not declared decisions: %s" % ", ".join(sorted(unknown_neighbors)))
    fixed = set(variables).difference(released)
    if not released:
        raise EmptyNeighborhoodError("empty neighborhoods are not executable")
    return NeighborhoodSpec(
        parent_sha256=artifact.sha256,
        parent_bytes=artifact.raw_bytes,
        violation_keys=violation_keys,
        released_variables=tuple(sorted(released)),
        fixed_variables=tuple(sorted(fixed)),
        fixed_values={name: copy.deepcopy(_get_path(artifact.decisions, name)) for name in sorted(fixed)},
        dependency_graph_sha256=graph.sha256,
        mode=mode,
        objective_sense=objective_sense,
        seed_variables=tuple(sorted(seeds)),
    )


@dataclass(frozen=True)
class SolveOutcome:
    status: Optional[str]
    values: Optional[Mapping[str, Any]] = None
    decisions: Optional[Mapping[str, Any]] = None
    raw_bytes: Optional[bytes] = None
    parent_sha256: Optional[str] = None

    @classmethod
    def from_value(cls, value: Any) -> "SolveOutcome":
        if isinstance(value, cls):
            return value
        if isinstance(value, (tuple, list)) and len(value) == 2:
            return cls(value[0], values=value[1])
        if not isinstance(value, Mapping):
            return cls(None)
        decisions = value.get("decisions", value.get("solution"))
        values = value.get("values", value.get("released_values"))
        return cls(
            status=value.get("status"),
            values=values,
            decisions=decisions,
            raw_bytes=value.get("raw_bytes", value.get("decision_bytes")),
            parent_sha256=value.get("parent_sha256"),
        )


@dataclass(frozen=True)
class RepairResult:
    accepted: bool
    reason: str
    selected: DecisionArtifact
    parent: DecisionArtifact
    checkpoint: Optional[DecisionArtifact]
    spec: Optional[NeighborhoodSpec] = None
    candidate: Optional[DecisionArtifact] = None
    parent_report: Optional[dict] = None
    candidate_report: Optional[dict] = None
    solve_status: Optional[str] = None
    introduced_violations: Tuple[str, ...] = ()
    fixed_violations: Tuple[str, ...] = ()
    remaining_violations: Tuple[str, ...] = ()

    @property
    def decisions(self) -> dict:
        return self.selected.decisions

    @property
    def parent_bytes(self) -> bytes:
        return self.parent.raw_bytes

    @property
    def parent_sha256(self) -> str:
        return self.parent.sha256


@dataclass(frozen=True)
class _CheckView:
    status: str
    violation_keys: Tuple[str, ...]
    objective: Optional[float]
    raw: dict


def _check_view(report: Any) -> _CheckView:
    if not isinstance(report, Mapping):
        return _CheckView("unknown", (), None, {"invalid_report": report})
    raw = copy.deepcopy(dict(report))
    status_value = report.get("business_status", report.get("status", report.get("verdict")))
    status_text = str(status_value).strip().lower() if status_value is not None else "unknown"
    status = {
        "pass": "pass", "valid": "pass", "ok": "pass", "satisfied": "pass",
        "fail": "fail", "invalid": "fail", "violated": "fail",
    }.get(status_text, "unknown")
    keys = []
    malformed = False
    unknown = status == "unknown" or bool(report.get("unknown"))
    rows = report.get("violations", [])
    if not isinstance(rows, list):
        rows = []
        malformed = True
    for row in rows:
        try:
            keys.append(ViolationKey.from_value(row).stable_key)
        except (NeighborhoodError, TypeError, ValueError):
            malformed = True
        if isinstance(row, Mapping) and str(row.get("status", "")).lower() == "unknown":
            unknown = True
    verdicts = report.get("verdicts", {})
    if isinstance(verdicts, Mapping) and any(
        str(value).lower() == "unknown" for value in verdicts.values()
    ):
        unknown = True
    if malformed or (status == "pass" and keys) or (status == "fail" and not keys):
        unknown = True
    objective_value = report.get("objective", report.get("objective_value"))
    objective = None
    if isinstance(objective_value, (int, float)) and not isinstance(objective_value, bool):
        objective = float(objective_value)
        if not math.isfinite(objective):
            objective = None
    return _CheckView("unknown" if unknown else status, tuple(sorted(set(keys))), objective, raw)


def _rejected(
    reason: str,
    parent: DecisionArtifact,
    checkpoint: Optional[DecisionArtifact],
    *,
    spec: Optional[NeighborhoodSpec] = None,
    candidate: Optional[DecisionArtifact] = None,
    parent_report: Optional[dict] = None,
    candidate_report: Optional[dict] = None,
    solve_status: Optional[str] = None,
    introduced: Iterable[str] = (),
    fixed: Iterable[str] = (),
    remaining: Iterable[str] = (),
) -> RepairResult:
    return RepairResult(
        accepted=False,
        reason=reason,
        selected=parent,
        parent=parent,
        checkpoint=checkpoint,
        spec=spec,
        candidate=candidate,
        parent_report=parent_report,
        candidate_report=candidate_report,
        solve_status=solve_status,
        introduced_violations=tuple(sorted(set(introduced))),
        fixed_violations=tuple(sorted(set(fixed))),
        remaining_violations=tuple(sorted(set(remaining))),
    )


_SOLUTION_STATUSES = {"optimal", "feasible", "success", "ok", "sat", "solution", "solution_found"}
_KNOWN_NO_SOLUTION_STATUSES = {
    "infeasible", "unbounded", "infeasible_or_unbounded", "timelimit", "time_limit",
    "nodelimit", "node_limit", "gaplimit", "gap_limit", "userinterrupt", "user_interrupt",
    "terminate", "terminated", "error", "failed", "no_solution",
}


def repair_neighborhood(
    parent: Any,
    dependency_graph: Any,
    full_checker: Callable[[dict], Mapping[str, Any]],
    solver: Callable[[NeighborhoodSpec], Any],
    *,
    parent_bytes: Optional[bytes] = None,
    parent_sha256: str = "",
    variable_names: Optional[Iterable[str]] = None,
    seed_variables: Iterable[str] = (),
    mode: str = DECISION_REPAIR,
    objective_sense: Optional[str] = None,
    objective_tolerance: float = 1e-9,
    checkpoint: Optional[Any] = None,
) -> RepairResult:
    """Execute one local solve and accept only an independently checked, non-regressing result.

    A local outcome uses ``values`` keyed by released variable IDs. A full outcome uses
    ``decisions`` and must preserve every fixed value and the parent's top-level schema.
    Partial decision repairs may retain old violation keys, but must fix at least one and
    introduce none. Objective optimization requires a feasible parent and a non-worsening
    independently recomputed objective.
    """
    artifact = _as_artifact(parent, parent_bytes, parent_sha256)
    retained_checkpoint = _as_artifact(checkpoint) if checkpoint is not None else None
    if mode == MODEL_DIAGNOSIS:
        return _rejected(
            "model_diagnosis_requires_model_inputs", artifact, retained_checkpoint,
        )
    if mode not in {DECISION_REPAIR, OBJECTIVE_OPTIMIZATION}:
        return _rejected("unsupported_mode", artifact, retained_checkpoint)
    if not isinstance(objective_tolerance, (int, float)) or isinstance(objective_tolerance, bool) \
            or not math.isfinite(objective_tolerance) or objective_tolerance < 0:
        raise NeighborhoodError("objective_tolerance must be a finite nonnegative number")
    try:
        parent_report = full_checker(copy.deepcopy(artifact.decisions))
        parent_view = _check_view(parent_report)
    except Exception as exc:
        return _rejected("parent_checker_error:%s" % type(exc).__name__, artifact, retained_checkpoint)
    if parent_view.status == "unknown":
        return _rejected(
            "parent_unknown", artifact, retained_checkpoint, parent_report=parent_view.raw,
        )
    if retained_checkpoint is not None:
        try:
            checkpoint_view = _check_view(full_checker(copy.deepcopy(retained_checkpoint.decisions)))
        except Exception:
            return _rejected(
                "checkpoint_not_feasible", artifact, retained_checkpoint, parent_report=parent_view.raw,
            )
        if checkpoint_view.status != "pass":
            return _rejected(
                "checkpoint_not_feasible", artifact, retained_checkpoint, parent_report=parent_view.raw,
            )
    elif parent_view.status == "pass":
        retained_checkpoint = artifact
    if mode == OBJECTIVE_OPTIMIZATION:
        if parent_view.status != "pass":
            return _rejected(
                "optimization_requires_feasible_parent", artifact, retained_checkpoint,
                parent_report=parent_view.raw,
            )
        if objective_sense not in {"minimize", "maximize"}:
            return _rejected(
                "objective_sense_required", artifact, retained_checkpoint,
                parent_report=parent_view.raw,
            )
        if parent_view.objective is None:
            return _rejected(
                "parent_objective_unknown", artifact, retained_checkpoint,
                parent_report=parent_view.raw,
            )
    try:
        spec = build_neighborhood(
            artifact,
            parent_view.violation_keys,
            dependency_graph,
            variable_names=variable_names,
            seed_variables=seed_variables,
            mode=mode,
            objective_sense=objective_sense,
        )
    except EmptyNeighborhoodError:
        return _rejected(
            "empty_neighborhood", artifact, retained_checkpoint, parent_report=parent_view.raw,
        )
    except NeighborhoodError as exc:
        return _rejected(
            "invalid_neighborhood:%s" % str(exc), artifact, retained_checkpoint,
            parent_report=parent_view.raw,
        )
    try:
        outcome = SolveOutcome.from_value(solver(spec))
    except Exception as exc:
        return _rejected(
            "solver_error:%s" % type(exc).__name__, artifact, retained_checkpoint,
            spec=spec, parent_report=parent_view.raw,
        )
    status = str(outcome.status).strip().lower().replace("-", "_").replace(" ", "_") \
        if outcome.status is not None else "unknown"
    if status not in _SOLUTION_STATUSES:
        reason = "solver_no_solution" if status in _KNOWN_NO_SOLUTION_STATUSES else "solver_status_unknown"
        return _rejected(
            reason, artifact, retained_checkpoint, spec=spec, parent_report=parent_view.raw,
            solve_status=status,
        )
    if outcome.parent_sha256 is not None and outcome.parent_sha256 != artifact.sha256:
        return _rejected(
            "parent_hash_mismatch", artifact, retained_checkpoint, spec=spec,
            parent_report=parent_view.raw, solve_status=status,
        )
    if (outcome.values is None) == (outcome.decisions is None):
        return _rejected(
            "solver_decisions_missing_or_ambiguous", artifact, retained_checkpoint, spec=spec,
            parent_report=parent_view.raw, solve_status=status,
        )
    try:
        if outcome.values is not None:
            if not isinstance(outcome.values, Mapping):
                raise NeighborhoodError("local values must be an object")
            supplied = set(outcome.values)
            released = set(spec.released_variables)
            if not supplied.issubset(released):
                return _rejected(
                    "unexpected_solver_variable", artifact, retained_checkpoint, spec=spec,
                    parent_report=parent_view.raw, solve_status=status,
                )
            if supplied != released:
                return _rejected(
                    "incomplete_local_decisions", artifact, retained_checkpoint, spec=spec,
                    parent_report=parent_view.raw, solve_status=status,
                )
            complete = copy.deepcopy(artifact.decisions)
            for name in spec.released_variables:
                _set_path(complete, name, outcome.values[name])
        else:
            if not isinstance(outcome.decisions, Mapping):
                raise NeighborhoodError("full decisions must be an object")
            complete = copy.deepcopy(dict(outcome.decisions))
            if set(complete) != set(artifact.decisions):
                return _rejected(
                    "parent_decision_lost", artifact, retained_checkpoint, spec=spec,
                    parent_report=parent_view.raw, solve_status=status,
                )
            for name in spec.fixed_variables:
                if not _same_value(_get_path(complete, name), _get_path(artifact.decisions, name)):
                    return _rejected(
                        "fixed_variable_changed", artifact, retained_checkpoint, spec=spec,
                        parent_report=parent_view.raw, solve_status=status,
                    )
            for name in spec.released_variables:
                _get_path(complete, name)
        candidate = DecisionArtifact.create(complete, outcome.raw_bytes)
    except NeighborhoodError as exc:
        return _rejected(
            "parent_decision_lost:%s" % str(exc), artifact, retained_checkpoint, spec=spec,
            parent_report=parent_view.raw, solve_status=status,
        )
    try:
        candidate_report = full_checker(copy.deepcopy(candidate.decisions))
        candidate_view = _check_view(candidate_report)
    except Exception as exc:
        return _rejected(
            "candidate_checker_error:%s" % type(exc).__name__, artifact, retained_checkpoint,
            spec=spec, candidate=candidate, parent_report=parent_view.raw, solve_status=status,
        )
    parent_keys = set(parent_view.violation_keys)
    candidate_keys = set(candidate_view.violation_keys)
    introduced = tuple(sorted(candidate_keys - parent_keys))
    fixed = tuple(sorted(parent_keys - candidate_keys))
    remaining = tuple(sorted(parent_keys & candidate_keys))
    common = {
        "spec": spec,
        "candidate": candidate,
        "parent_report": parent_view.raw,
        "candidate_report": candidate_view.raw,
        "solve_status": status,
        "introduced": introduced,
        "fixed": fixed,
        "remaining": remaining,
    }
    if candidate_view.status == "unknown":
        return _rejected("candidate_unknown", artifact, retained_checkpoint, **common)
    if introduced:
        return _rejected("new_violations", artifact, retained_checkpoint, **common)
    if mode == DECISION_REPAIR and not fixed:
        return _rejected("no_repair_progress", artifact, retained_checkpoint, **common)
    if mode == OBJECTIVE_OPTIMIZATION:
        if candidate_view.status != "pass":
            return _rejected("candidate_not_feasible", artifact, retained_checkpoint, **common)
        if candidate_view.objective is None:
            return _rejected("candidate_objective_unknown", artifact, retained_checkpoint, **common)
        scale = max(1.0, abs(parent_view.objective), abs(candidate_view.objective))
        tolerance = objective_tolerance * scale
        regressed = (
            candidate_view.objective > parent_view.objective + tolerance
            if objective_sense == "minimize"
            else candidate_view.objective < parent_view.objective - tolerance
        )
        if regressed:
            return _rejected("objective_regression", artifact, retained_checkpoint, **common)
    new_checkpoint = candidate if candidate_view.status == "pass" else retained_checkpoint
    return RepairResult(
        accepted=True,
        reason="accepted",
        selected=candidate,
        parent=artifact,
        checkpoint=new_checkpoint,
        spec=spec,
        candidate=candidate,
        parent_report=parent_view.raw,
        candidate_report=candidate_view.raw,
        solve_status=status,
        introduced_violations=introduced,
        fixed_violations=fixed,
        remaining_violations=remaining,
    )


class DeclarativeNeighborhoodEngine:
    """Convenience wrapper binding a graph, independent checker and local solver."""

    def __init__(
        self,
        dependency_graph: Any,
        full_checker: Callable[[dict], Mapping[str, Any]],
        solver: Callable[[NeighborhoodSpec], Any],
        *,
        variable_names: Optional[Iterable[str]] = None,
    ) -> None:
        self.dependency_graph = DependencyGraph.from_dict(dependency_graph)
        self.full_checker = full_checker
        self.solver = solver
        self.variable_names = tuple(variable_names) if variable_names is not None else None

    def build(self, parent: Any, violations: Iterable[Any], **kwargs: Any) -> NeighborhoodSpec:
        kwargs.setdefault("variable_names", self.variable_names)
        return build_neighborhood(parent, violations, self.dependency_graph, **kwargs)

    def repair(self, parent: Any, **kwargs: Any) -> RepairResult:
        kwargs.setdefault("variable_names", self.variable_names)
        return repair_neighborhood(
            parent,
            self.dependency_graph,
            self.full_checker,
            self.solver,
            **kwargs,
        )

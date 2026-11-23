"""Public-source Requirement IR, candidate binding and deterministic decision checks."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

from .cleanroom import FAIL, PASS, UNKNOWN

CHECKER_VERSION = "public_decision_checker_v0.1"
SUPPORTED_KINDS = {
    "demand_balance", "conditional_bounds", "unique_coverage",
    "temporal_sequence", "objective_recompute",
}


@dataclass(frozen=True)
class SourceRef:
    source_file: str
    quote: str
    sha256: str

    def issues(self, public_files: dict[str, str]) -> list[str]:
        content = public_files.get(self.source_file)
        if content is None:
            return [f"source is not public: {self.source_file}"]
        issues = []
        if not self.quote or self.quote not in content:
            issues.append(f"source quote is not verbatim: {self.source_file}")
        if hashlib.sha256(content.encode()).hexdigest() != self.sha256:
            issues.append(f"source hash mismatch: {self.source_file}")
        return issues


@dataclass(frozen=True)
class Requirement:
    requirement_id: str
    kind: str
    source: SourceRef
    output_mapping: dict
    payload: dict = field(default_factory=dict)
    hard: bool = True
    unit: str = ""
    activation: str = "always"


@dataclass(frozen=True)
class RequirementIR:
    problem_id: str
    objective_sense: str
    requirements: tuple[Requirement, ...]
    omission_defaults: dict[str, str] = field(default_factory=dict)
    unresolved: tuple[str, ...] = ()
    schema_version: str = "requirement_ir_v0.1"

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "problem_id": self.problem_id,
            "objective_sense": self.objective_sense,
            "omission_defaults": self.omission_defaults,
            "unresolved": list(self.unresolved),
            "requirements": [{
                "requirement_id": item.requirement_id,
                "kind": item.kind,
                "hard": item.hard,
                "unit": item.unit,
                "activation": item.activation,
                "source": {
                    "source_file": item.source.source_file,
                    "quote": item.source.quote,
                    "sha256": item.source.sha256,
                },
                "output_mapping": item.output_mapping,
                "payload": item.payload,
            } for item in self.requirements],
        }

    def validation_issues(self, public_files: dict[str, str]) -> list[str]:
        issues = list(self.unresolved)
        if not self.problem_id:
            issues.append("missing problem_id")
        if self.objective_sense not in {"minimize", "maximize"}:
            issues.append("unresolved objective_sense")
        if not self.requirements:
            issues.append("no requirements were supplied")
        seen = set()
        for item in self.requirements:
            if not item.requirement_id or item.requirement_id in seen:
                issues.append(f"duplicate or empty requirement id: {item.requirement_id}")
            seen.add(item.requirement_id)
            if item.kind not in SUPPORTED_KINDS:
                issues.append(f"unsupported requirement kind: {item.requirement_id}:{item.kind}")
            if not item.output_mapping.get("decision_key"):
                issues.append(f"missing output binding: {item.requirement_id}")
            if not item.activation:
                issues.append(f"missing activation condition: {item.requirement_id}")
            issues.extend(f"{item.requirement_id}:{issue}" for issue in item.source.issues(public_files))
            if not _finite_json(item.payload):
                issues.append(f"non-finite or invalid payload: {item.requirement_id}")
        for field_name, default in self.omission_defaults.items():
            if not field_name or not default or default == "unknown":
                issues.append(f"unresolved omission default: {field_name}")
        return issues


def _finite_json(value) -> bool:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_finite_json(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _finite_json(item) for key, item in value.items())
    return False


def candidate_binding_gate(ir: RequirementIR, public_files: dict[str, str], solver_code: str,
                           bindings: dict[str, dict]) -> dict:
    issues = ir.validation_issues(public_files)
    for item in ir.requirements:
        binding = bindings.get(item.requirement_id)
        if not isinstance(binding, dict):
            issues.append(f"missing candidate binding: {item.requirement_id}")
            continue
        anchor = binding.get("code_anchor")
        if not isinstance(anchor, str) or not anchor or anchor not in solver_code:
            issues.append(f"missing code anchor: {item.requirement_id}")
        if not binding.get("output_fields"):
            issues.append(f"missing emitted output fields: {item.requirement_id}")
    return {
        "ready_for_solve": not issues,
        "model_verified": False,
        "model_verification_note": "Text anchors establish binding coverage, not semantic equivalence of arbitrary Python.",
        "business_status": "not_evaluated",
        "post_solve_obligations": [item.requirement_id for item in ir.requirements if item.hard],
        "unresolved": issues,
    }


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value) else None


def _index(value) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return (str(value),)


def _key(requirement_id: str, index, rule_part: str) -> str:
    return json.dumps([requirement_id, list(_index(index)), rule_part], ensure_ascii=False)


def _violation(requirement_id: str, index, rule_part: str, status: str, detail: str) -> dict:
    return {"key": _key(requirement_id, index, rule_part), "requirement_id": requirement_id,
            "index": list(_index(index)), "rule_part": rule_part, "status": status, "detail": detail}


class PublicDecisionChecker:
    def __init__(self, ir: RequirementIR, public_files: dict[str, str]):
        self.ir = ir
        self.public_files = public_files
        self._initial_sha256 = self._digest()

    def _digest(self) -> str:
        payload = {"checker_version": CHECKER_VERSION, "ir": self.ir.to_dict()}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @property
    def checker_sha256(self) -> str:
        return self._initial_sha256

    def assert_unchanged(self) -> None:
        if self._digest() != self._initial_sha256:
            raise ValueError("Requirement IR or checker version changed during decision repair")

    @staticmethod
    def diff(before: dict, after: dict) -> dict:
        if before.get("checker_sha256") != after.get("checker_sha256"):
            raise ValueError("cannot compare violations across checker or IR versions")
        old = {item["key"] for item in before.get("violations", [])}
        new = {item["key"] for item in after.get("violations", [])}
        return {"fixed": sorted(old - new), "introduced": sorted(new - old),
                "remaining": sorted(old & new)}

    def _rows(self, item: Requirement, decisions: dict) -> list[dict] | None:
        rows = decisions.get(item.output_mapping["decision_key"])
        return rows if isinstance(rows, list) and all(isinstance(row, dict) for row in rows) else None

    def _missing_rows(self, item: Requirement) -> list[dict]:
        return [_violation(item.requirement_id, ("output",), "decision_rows", UNKNOWN,
                           "structured emitted decisions are missing or have the wrong schema")]

    def _demand_balance(self, item: Requirement, decisions: dict) -> list[dict]:
        rows = self._rows(item, decisions)
        if rows is None:
            return self._missing_rows(item)
        tolerance = float(item.payload.get("tolerance", 1e-6))
        violations = []
        for row in rows:
            index = row.get("index", ("missing",))
            values = {name: _number(row.get(name)) for name in ("demand", "served", "unmet")}
            rate = _number(row.get("minimum_service_rate", item.payload.get("minimum_service_rate")))
            if any(value is None for value in values.values()) or rate is None:
                violations.append(_violation(item.requirement_id, index, "numeric_inputs", UNKNOWN,
                                             "demand, served, unmet and service floor must be finite numbers"))
                continue
            demand, served, unmet = values["demand"], values["served"], values["unmet"]
            if min(demand, served, unmet) < 0:
                violations.append(_violation(item.requirement_id, index, "nonnegative", FAIL,
                                             "demand, served and unmet must be nonnegative"))
            if abs(served + unmet - demand) > tolerance:
                violations.append(_violation(item.requirement_id, index, "demand_conservation", FAIL,
                                             "served plus unmet does not equal demand"))
            if served + tolerance < demand * rate:
                violations.append(_violation(item.requirement_id, index, "service_floor", FAIL,
                                             "served demand is below the public minimum service rate"))
        return violations

    def _conditional_bounds(self, item: Requirement, decisions: dict) -> list[dict]:
        rows = self._rows(item, decisions)
        if rows is None:
            return self._missing_rows(item)
        tolerance = float(item.payload.get("tolerance", 1e-6))
        violations = []
        for row in rows:
            index = row.get("index", ("missing",))
            use, flow = _number(row.get("use")), _number(row.get("flow"))
            minimum = _number(row.get("minimum_flow", item.payload.get("minimum_flow", 0.0)))
            capacity = _number(row.get("capacity", item.payload.get("capacity")))
            if any(value is None for value in (use, flow, minimum, capacity)) or use not in {0.0, 1.0}:
                violations.append(_violation(item.requirement_id, index, "numeric_inputs", UNKNOWN,
                                             "use must be binary and flow bounds must be finite"))
                continue
            if use == 0.0 and abs(flow) > tolerance:
                violations.append(_violation(item.requirement_id, index, "inactive_flow", FAIL,
                                             "positive flow is assigned to an inactive link"))
            if use == 1.0 and flow + tolerance < minimum:
                violations.append(_violation(item.requirement_id, index, "minimum_flow", FAIL,
                                             "active link flow is below its public lower bound"))
            if use == 1.0 and flow > capacity + tolerance:
                violations.append(_violation(item.requirement_id, index, "capacity", FAIL,
                                             "active link flow exceeds public capacity"))
        return violations

    def _unique_coverage(self, item: Requirement, decisions: dict) -> list[dict]:
        rows = self._rows(item, decisions)
        if rows is None:
            return self._missing_rows(item)
        areas = {}
        violations = []
        for row in rows:
            index = row.get("index", ("missing",))
            area_id = str(row.get("area_id"))
            population = _number(row.get("population"))
            served = row.get("served")
            if population is None or not isinstance(served, bool):
                violations.append(_violation(item.requirement_id, index, "numeric_inputs", UNKNOWN,
                                             "population must be finite and served must be boolean"))
                continue
            current = {"population": population, "served": served}
            if area_id in areas and areas[area_id] != current:
                violations.append(_violation(item.requirement_id, index, "conflicting_duplicate", FAIL,
                                             "duplicate area rows disagree about population or coverage"))
            areas[area_id] = current
        total = sum(row["population"] for row in areas.values())
        covered = sum(row["population"] for row in areas.values() if row["served"])
        rate = _number(item.payload.get("minimum_coverage_rate"))
        if rate is None:
            violations.append(_violation(item.requirement_id, ("global",), "coverage_rate", UNKNOWN,
                                         "minimum coverage rate is missing"))
        elif covered + float(item.payload.get("tolerance", 1e-6)) < total * rate:
            violations.append(_violation(item.requirement_id, ("global",), "coverage_floor", FAIL,
                                         "uniquely counted covered population is below the public floor"))
        return violations

    def _temporal_sequence(self, item: Requirement, decisions: dict) -> list[dict]:
        routes = decisions.get(item.output_mapping["decision_key"])
        if not isinstance(routes, list) or not all(isinstance(route, list) for route in routes):
            return self._missing_rows(item)
        tolerance = float(item.payload.get("tolerance", 1e-6))
        violations = []
        for route_index, route in enumerate(routes):
            previous_end = None
            for step_index, step in enumerate(route):
                if not isinstance(step, dict):
                    violations.append(_violation(item.requirement_id, (route_index, step_index),
                                                 "decision_rows", UNKNOWN, "route step must be an object"))
                    continue
                index = step.get("index", (route_index, step_index))
                names = ("arrival", "service_start", "service_end", "earliest", "latest",
                         "service_duration", "travel_from_previous")
                values = {name: _number(step.get(name)) for name in names}
                if any(value is None for value in values.values()):
                    violations.append(_violation(item.requirement_id, index, "numeric_inputs", UNKNOWN,
                                                 "all temporal fields must be finite numbers"))
                    previous_end = None
                    continue
                arrival, start = values["arrival"], values["service_start"]
                end, duration = values["service_end"], values["service_duration"]
                if previous_end is not None and arrival + tolerance < previous_end + values["travel_from_previous"]:
                    violations.append(_violation(item.requirement_id, index, "travel_continuity", FAIL,
                                                 "arrival does not allow the required previous service and travel"))
                if start + tolerance < arrival:
                    violations.append(_violation(item.requirement_id, index, "arrival_order", FAIL,
                                                 "service starts before arrival"))
                if start + tolerance < values["earliest"] or start > values["latest"] + tolerance:
                    violations.append(_violation(item.requirement_id, index, "time_window", FAIL,
                                                 "service start violates its public time window"))
                if end + tolerance < start + duration:
                    violations.append(_violation(item.requirement_id, index, "service_duration", FAIL,
                                                 "service duration is shorter than required"))
                previous_end = end
        return violations

    def _objective_recompute(self, item: Requirement, decisions: dict) -> tuple[list[dict], float | None]:
        rows = self._rows(item, decisions)
        if rows is None:
            return self._missing_rows(item), None
        reported = _number(decisions.get(item.output_mapping["reported_key"]))
        if reported is None:
            return [_violation(item.requirement_id, ("objective",), "reported_objective", UNKNOWN,
                               "reported objective is missing or non-finite")], None
        total = 0.0
        violations = []
        for row in rows:
            index = row.get("index", ("term",))
            value, coefficient = _number(row.get("value")), _number(row.get("coefficient"))
            if value is None or coefficient is None:
                violations.append(_violation(item.requirement_id, index, "numeric_inputs", UNKNOWN,
                                             "objective terms must be finite numbers"))
                continue
            total += value * coefficient
        tolerance = float(item.payload.get("tolerance", 1e-6))
        if not violations and abs(total - reported) > tolerance * max(1.0, abs(total), abs(reported)):
            violations.append(_violation(item.requirement_id, ("objective",), "objective_consistency", FAIL,
                                         "reported objective differs from emitted-decision recomputation"))
        return violations, total

    def check(self, decisions: dict) -> dict:
        self.assert_unchanged()
        issues = self.ir.validation_issues(self.public_files)
        if issues:
            violations = [_violation("__ir__", ("schema",), "unresolved", UNKNOWN, issue)
                          for issue in issues]
            return {"business_status": UNKNOWN, "verdicts": {}, "violations": violations,
                    "objective": None, "checker_sha256": self.checker_sha256,
                    "veto_enabled": False, "reconstructed_omissions": {}}
        violations = []
        verdicts = {}
        objective = None
        reconstructed = {}
        for field_name in decisions.get("omitted_fields", []):
            default = self.ir.omission_defaults.get(field_name)
            if default is None:
                violations.append(_violation("__output__", (field_name,), "omission_default", UNKNOWN,
                                             "no public omission default is available"))
            else:
                reconstructed[field_name] = default
        for item in self.ir.requirements:
            if item.kind == "objective_recompute":
                current, objective = self._objective_recompute(item, decisions)
            else:
                current = getattr(self, f"_{item.kind}")(item, decisions)
            violations.extend(current)
            statuses = {row["status"] for row in current}
            verdicts[item.requirement_id] = UNKNOWN if UNKNOWN in statuses else FAIL if FAIL in statuses else PASS
        if any(row["rule_part"] == "omission_default" for row in violations):
            verdicts["__output__"] = UNKNOWN
        statuses = set(verdicts.values())
        business_status = UNKNOWN if UNKNOWN in statuses else FAIL if FAIL in statuses else PASS
        return {"business_status": business_status, "verdicts": verdicts, "violations": violations,
                "objective": objective, "checker_sha256": self.checker_sha256,
                "veto_enabled": False, "reconstructed_omissions": reconstructed}

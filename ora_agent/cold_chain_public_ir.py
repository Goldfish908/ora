"""Public-source requirement adapter for cold-chain locker capacity planning."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path

from .cleanroom import FAIL, PASS, UNKNOWN
from .requirement_ir import PublicDecisionChecker, Requirement, RequirementIR, SourceRef

PROBLEM_ID = "cold_chain_locker_capacity_planning"
APP_DIR = (Path(__file__).resolve().parents[1] / "ORAgentBench" / "harbor_tasks" /
           PROBLEM_ID / "environment" / "app")
PUBLIC_FILENAMES = (
    "PROBLEM_STATEMENT.md",
    "data/config.json",
    "data/demand_zones.csv",
    "data/lockers.csv",
    "data/locker_modules.csv",
    "data/zone_locker_arcs.csv",
    "submissions/solution_template.csv",
)

_RULES_QUOTE = (
    "A locker must be opened before it can receive modules or serve demand. "
    "Orders can only be assigned along feasible arcs. Each demand zone must meet its "
    "service target. Ambient, chilled, and frozen orders consume only matching module "
    "capacity. Module counts are integer and limited by locker-temperature rules. "
    "Locker staff hours and energy use cannot be exceeded."
)
_OPEN_QUOTE = "A locker must be opened before it can receive modules or serve demand."
_ARC_QUOTE = "Orders can only be assigned along feasible arcs."
_TEMPERATURE_QUOTE = (
    "Ambient, chilled, and frozen orders consume only matching module capacity."
)
_MODULE_QUOTE = "Module counts are integer and limited by locker-temperature rules."
_RESOURCE_QUOTE = "Locker staff hours and energy use cannot be exceeded."
_EXPECTED_COLUMNS = ["row_type", "locker_id", "zone_id", "temperature_zone", "value"]


def load_public_files(app_dir: str | Path = APP_DIR) -> dict[str, str]:
    root = Path(app_dir)
    return {name: (root / name).read_text(encoding="utf-8") for name in PUBLIC_FILENAMES}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _source(public_files: dict[str, str], quote: str) -> SourceRef:
    content = public_files["PROBLEM_STATEMENT.md"]
    return SourceRef("PROBLEM_STATEMENT.md", quote, _sha256(content))


def _data_source(public_files: dict[str, str], name: str) -> dict:
    content = public_files[name]
    return {"source_file": name, "quote": content.splitlines()[0], "sha256": _sha256(content)}


def _data_sources(public_files: dict[str, str], *names: str) -> list[dict]:
    return [_data_source(public_files, name) for name in names]


def build_requirement_ir(public_files: dict[str, str] | None = None) -> RequirementIR:
    files = load_public_files() if public_files is None else public_files
    config = json.loads(files["data/config.json"])
    tolerance = float(config["feasibility_tolerance"])
    common = {"tolerance": tolerance}
    requirements = (
        Requirement(
            "demand_balance_and_service", "demand_balance", _source(files, _RULES_QUOTE),
            {"decision_key": "demand", "row_index": ["zone_id"],
             "fields": ["demand", "served", "unmet", "minimum_service_rate"]},
            {**common, "data_sources": _data_sources(files, "data/demand_zones.csv")},
            unit="orders",
        ),
        Requirement(
            "assignment_open_locker", "conditional_bounds", _source(files, _OPEN_QUOTE),
            {"decision_key": "assignment_open", "row_index": ["zone_id", "locker_id"],
             "fields": ["use", "flow", "minimum_flow", "capacity"]},
            {**common, "data_sources": _data_sources(files, "data/lockers.csv",
                                                       "data/demand_zones.csv")},
            unit="orders",
        ),
        Requirement(
            "assignment_feasible_arc", "conditional_bounds", _source(files, _ARC_QUOTE),
            {"decision_key": "illegal_arc", "row_index": ["zone_id", "locker_id"],
             "fields": ["use", "flow", "minimum_flow", "capacity"]},
            {**common, "data_sources": _data_sources(files, "data/zone_locker_arcs.csv")},
            unit="orders",
        ),
        Requirement(
            "module_open_and_maximum", "conditional_bounds", _source(files, _RULES_QUOTE),
            {"decision_key": "module_bounds", "row_index": ["locker_id", "temperature_zone"],
             "fields": ["use", "flow", "minimum_flow", "capacity"]},
            {**common, "data_sources": _data_sources(files, "data/lockers.csv",
                                                       "data/locker_modules.csv")},
            unit="modules",
        ),
        Requirement(
            "module_integrality", "demand_balance", _source(files, _MODULE_QUOTE),
            {"decision_key": "module_integrality", "row_index": ["locker_id", "temperature_zone"],
             "fields": ["demand", "served", "unmet", "minimum_service_rate"],
             "equation": "nearest_integer + 0 = emitted_module_count"},
            {**common, "data_sources": _data_sources(files, "data/locker_modules.csv")},
            unit="modules",
        ),
        Requirement(
            "matching_temperature_capacity", "conditional_bounds", _source(files, _TEMPERATURE_QUOTE),
            {"decision_key": "temperature_capacity", "row_index": ["locker_id", "temperature_zone"],
             "fields": ["use", "flow", "minimum_flow", "capacity"]},
            {**common, "data_sources": _data_sources(files, "data/demand_zones.csv",
                                                       "data/locker_modules.csv")},
            unit="orders",
        ),
        Requirement(
            "opening_staff_hours_bound", "conditional_bounds", _source(files, _RESOURCE_QUOTE),
            {"decision_key": "staff", "row_index": ["locker_id"],
             "fields": ["use", "flow", "minimum_flow", "capacity"]},
            {**common, "data_sources": _data_sources(files, "data/lockers.csv"),
             "scope": "fixed staff_hours associated with each emitted open decision only"},
            unit="staff_hours",
        ),
        Requirement(
            "locker_energy_limit", "conditional_bounds", _source(files, _RESOURCE_QUOTE),
            {"decision_key": "energy", "row_index": ["locker_id"],
             "fields": ["use", "flow", "minimum_flow", "capacity"]},
            {**common, "data_sources": _data_sources(files, "data/lockers.csv",
                                                       "data/locker_modules.csv")},
            unit="kWh",
        ),
    )
    return RequirementIR(
        problem_id=PROBLEM_ID,
        objective_sense="minimize",
        requirements=requirements,
        omission_defaults={"open": "0", "module": "0", "assignment": "0", "unmet": "0"},
    )


def uncovered_rules() -> list[dict]:
    return [
        {"rule": "staff_limit_beyond_fixed_opening_hours", "status": UNKNOWN,
         "detail": "No global staff budget or per-order/module staff consumption is public."},
        {"rule": "objective_optimality", "status": UNKNOWN,
         "detail": "Feasibility and emitted-row checks cannot establish objective optimality."},
        {"rule": "official_business_truth_equivalence", "status": UNKNOWN,
         "detail": "Public-rule coverage is not equivalent to the official evaluator's business truth."},
    ]


def _csv_rows(content: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content)))


def _public_data(public_files: dict[str, str]) -> tuple[dict, dict, dict, set]:
    zones = {row["zone_id"]: row for row in _csv_rows(public_files["data/demand_zones.csv"])}
    lockers = {row["locker_id"]: row for row in _csv_rows(public_files["data/lockers.csv"])}
    modules = {(row["locker_id"], row["temperature_zone"]): row
               for row in _csv_rows(public_files["data/locker_modules.csv"])}
    arcs = {(row["zone_id"], row["locker_id"])
            for row in _csv_rows(public_files["data/zone_locker_arcs.csv"])}
    return zones, lockers, modules, arcs


def _mapping_violation(index, rule_part: str, status: str, detail: str) -> dict:
    indices = [str(value) for value in (index if isinstance(index, (list, tuple)) else (index,))]
    return {"key": json.dumps(["__output__", indices, rule_part], ensure_ascii=False),
            "requirement_id": "__output__", "index": indices, "rule_part": rule_part,
            "status": status, "detail": detail}


def solution_to_decisions(csv_text: str, public_files: dict[str, str] | None = None) -> dict:
    files = load_public_files() if public_files is None else public_files
    zones, lockers, module_specs, arcs = _public_data(files)
    tolerance = float(json.loads(files["data/config.json"])["feasibility_tolerance"])
    reader = csv.DictReader(io.StringIO(csv_text))
    issues = []
    if reader.fieldnames != _EXPECTED_COLUMNS:
        issues.append(_mapping_violation(
            ("header",), "solution_schema", UNKNOWN,
            "solution.csv must use the five public columns in their published order"))

    opens: dict[str, float] = {}
    modules: dict[tuple[str, str], float] = {}
    assignments: dict[tuple[str, str], float] = {}
    unmet: dict[str, float] = {}
    seen = set()

    for row_number, row in enumerate(reader, 2):
        row_type = (row.get("row_type") or "").strip()
        locker_id = (row.get("locker_id") or "").strip()
        zone_id = (row.get("zone_id") or "").strip()
        temperature = (row.get("temperature_zone") or "").strip()
        row_index = ("csv_row", row_number)
        try:
            value = float(row.get("value") or "")
            if not math.isfinite(value):
                raise ValueError
        except (TypeError, ValueError):
            issues.append(_mapping_violation(
                row_index, "finite_value", UNKNOWN, "decision value must be a finite number"))
            continue

        if row_type not in {"open", "module", "assignment", "unmet"}:
            issues.append(_mapping_violation(
                row_index, "row_type", FAIL, "row_type is not one of the four public row types"))
            continue

        semantic_temperature = temperature
        if row_type in {"assignment", "unmet"} and zone_id in zones:
            semantic_temperature = zones[zone_id]["temperature_zone"]
        semantic_key = (row_type, locker_id, zone_id, semantic_temperature)
        if semantic_key in seen:
            issues.append(_mapping_violation(
                row_index, "duplicate_decision", UNKNOWN,
                "the public schema does not define duplicate-row aggregation; "
                "a deterministic aggregate is used"))
        seen.add(semantic_key)

        if row_type == "open":
            if locker_id not in lockers:
                issues.append(_mapping_violation(
                    row_index, "unknown_locker", FAIL, "open row names no public candidate locker"))
                continue
            if zone_id or temperature:
                issues.append(_mapping_violation(
                    row_index, "open_identifiers", FAIL, "open rows must leave zone and temperature blank"))
            opens[locker_id] = (max(value, opens[locker_id]) if locker_id in opens else value)
            continue

        if row_type == "module":
            if locker_id not in lockers or (locker_id, temperature) not in module_specs:
                issues.append(_mapping_violation(
                    row_index, "unknown_module", FAIL,
                    "module row must name a public locker and supported temperature"))
                continue
            if zone_id:
                issues.append(_mapping_violation(
                    row_index, "module_identifiers", FAIL, "module rows must leave zone blank"))
            key = (locker_id, temperature)
            modules[key] = modules.get(key, 0.0) + value
            continue

        if row_type == "assignment":
            if locker_id not in lockers or zone_id not in zones:
                issues.append(_mapping_violation(
                    row_index, "unknown_assignment_identifier", FAIL,
                    "assignment rows must name a public zone and candidate locker"))
                continue
            required_temperature = zones[zone_id]["temperature_zone"]
            if temperature and temperature != required_temperature:
                issues.append(_mapping_violation(
                    row_index, "assignment_temperature", FAIL,
                    "assignment temperature must be blank or repeat the zone requirement"))
            key = (zone_id, locker_id)
            assignments[key] = assignments.get(key, 0.0) + value
            continue

        if locker_id:
            issues.append(_mapping_violation(
                row_index, "unmet_locker", FAIL, "unmet rows must leave locker blank"))
        if zone_id not in zones:
            issues.append(_mapping_violation(
                row_index, "unknown_unmet_zone", FAIL, "unmet row names no public demand zone"))
            continue
        required_temperature = zones[zone_id]["temperature_zone"]
        if temperature and temperature != required_temperature:
            issues.append(_mapping_violation(
                row_index, "unmet_temperature", FAIL,
                "unmet temperature must be blank or repeat the zone requirement"))
        unmet[zone_id] = unmet.get(zone_id, 0.0) + value

    total_demand = sum(float(row["orders"]) for row in zones.values())
    served_by_zone = {zone_id: 0.0 for zone_id in zones}
    served_by_module = {key: 0.0 for key in module_specs}
    for (zone_id, locker_id), value in assignments.items():
        served_by_zone[zone_id] += value
        temperature = zones[zone_id]["temperature_zone"]
        module_key = (locker_id, temperature)
        if module_key in served_by_module:
            served_by_module[module_key] += value

    demand_rows = []
    for zone_id in sorted(zones):
        zone = zones[zone_id]
        demand_rows.append({
            "index": (zone_id,), "demand": float(zone["orders"]),
            "served": served_by_zone[zone_id], "unmet": unmet.get(zone_id, 0.0),
            "minimum_service_rate": float(zone["minimum_service_rate"]),
        })

    assignment_open_rows = []
    illegal_arc_rows = []
    for zone_id, locker_id in sorted(assignments):
        value = assignments[zone_id, locker_id]
        assignment_open_rows.append({
            "index": (zone_id, locker_id), "use": opens.get(locker_id, 0.0),
            "flow": value, "minimum_flow": 0.0, "capacity": total_demand,
        })
        if (zone_id, locker_id) not in arcs:
            illegal_arc_rows.append({
                "index": (zone_id, locker_id), "use": 1.0, "flow": value,
                "minimum_flow": 0.0, "capacity": 0.0,
            })

    module_bound_rows = []
    integrality_rows = []
    for locker_id, temperature in sorted(modules):
        count = modules[locker_id, temperature]
        spec = module_specs[locker_id, temperature]
        module_bound_rows.append({
            "index": (locker_id, temperature), "use": opens.get(locker_id, 0.0),
            "flow": count, "minimum_flow": 0.0, "capacity": float(spec["max_modules"]),
        })
        integrality_rows.append({
            "index": (locker_id, temperature), "demand": count,
            "served": float(round(count)), "unmet": 0.0, "minimum_service_rate": 0.0,
        })

    temperature_rows = []
    energy_by_locker = {locker_id: 0.0 for locker_id in lockers}
    for locker_id, temperature in sorted(module_specs):
        spec = module_specs[locker_id, temperature]
        count = modules.get((locker_id, temperature), 0.0)
        temperature_rows.append({
            "index": (locker_id, temperature), "use": 1.0,
            "flow": served_by_module[locker_id, temperature], "minimum_flow": 0.0,
            "capacity": count * float(spec["capacity_per_module"]),
        })
        energy_by_locker[locker_id] += count * float(spec["energy_kwh_per_module"])

    staff_rows = []
    energy_rows = []
    for locker_id in sorted(lockers):
        locker = lockers[locker_id]
        opened = opens.get(locker_id, 0.0)
        staff_hours = float(locker["staff_hours"])
        staff_rows.append({
            "index": (locker_id,), "use": opened, "flow": staff_hours * opened,
            "minimum_flow": 0.0, "capacity": staff_hours,
        })
        energy_rows.append({
            "index": (locker_id,), "use": opened, "flow": energy_by_locker[locker_id],
            "minimum_flow": 0.0, "capacity": float(locker["energy_kwh_limit"]),
        })

    return {
        "demand": demand_rows,
        "assignment_open": assignment_open_rows,
        "illegal_arc": illegal_arc_rows,
        "module_bounds": module_bound_rows,
        "module_integrality": integrality_rows,
        "temperature_capacity": temperature_rows,
        "staff": staff_rows,
        "energy": energy_rows,
        "omitted_fields": [],
        "omission_defaults_applied": {"open": 0.0, "module": 0.0,
                                      "assignment": 0.0, "unmet": 0.0},
        "tolerance": tolerance,
        "_mapping_violations": issues,
    }


def solution_file_to_decisions(path: str | Path, public_files: dict[str, str] | None = None) -> dict:
    return solution_to_decisions(Path(path).read_text(encoding="utf-8"), public_files)


def check_decisions(decisions: dict, ir: RequirementIR | None = None,
                    public_files: dict[str, str] | None = None) -> dict:
    files = load_public_files() if public_files is None else public_files
    requirement_ir = build_requirement_ir(files) if ir is None else ir
    result = PublicDecisionChecker(requirement_ir, files).check(decisions)
    extra = decisions.get("_mapping_violations", [])
    if not isinstance(extra, list) or not all(isinstance(item, dict) for item in extra):
        extra = [_mapping_violation(("mapping",), "mapping_issues", UNKNOWN,
                                    "mapping issues are missing or malformed")]
    result["violations"].extend(extra)
    result["violations"].sort(key=lambda item: item["key"])
    for requirement_id in {item["requirement_id"] for item in extra}:
        statuses = {item["status"] for item in result["violations"]
                    if item["requirement_id"] == requirement_id}
        result["verdicts"][requirement_id] = (
            UNKNOWN if UNKNOWN in statuses else FAIL if FAIL in statuses else PASS)
    statuses = set(result["verdicts"].values())
    result["business_status"] = UNKNOWN if UNKNOWN in statuses else FAIL if FAIL in statuses else PASS
    result["veto_enabled"] = False
    result["uncovered_rules"] = uncovered_rules()
    result["coverage_note"] = "PASS covers only the encoded public constraints, not official business truth."
    return result


def check_solution_csv(csv_text: str, public_files: dict[str, str] | None = None) -> dict:
    files = load_public_files() if public_files is None else public_files
    return check_decisions(solution_to_decisions(csv_text, files), public_files=files)


def check_solution_file(path: str | Path, public_files: dict[str, str] | None = None) -> dict:
    files = load_public_files() if public_files is None else public_files
    return check_decisions(solution_file_to_decisions(path, files), public_files=files)

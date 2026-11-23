from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from ora_agent.cleanroom import FAIL, PASS, UNKNOWN
from ora_agent.cold_chain_public_ir import (
    build_requirement_ir,
    check_decisions,
    check_solution_csv,
    check_solution_file,
    load_public_files,
    solution_to_decisions,
)
from ora_agent.requirement_ir import PublicDecisionChecker

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_SOLUTION = REPO_ROOT / "tests/fixtures/cold_chain_root_solution.csv"
FIRST_REPAIR_SOLUTION = REPO_ROOT / "tests/fixtures/cold_chain_first_repair_solution.csv"
OFFICIAL_REPORTED_ERROR_COUNT = 75


def synthetic_files() -> dict[str, str]:
    files = load_public_files()
    files["data/config.json"] = json.dumps({
        "feasibility_tolerance": 1e-5,
        "solver_mip_gap": 0.0005,
        "unserved_penalty_per_order": 32.0,
    })
    files["data/demand_zones.csv"] = """zone_id,district,temperature_zone,orders,minimum_service_rate
z001,east,ambient,10,0.8
z002,east,chilled,8,0.75
"""
    files["data/lockers.csv"] = """locker_id,district,open_cost,staff_hours,energy_kwh_limit
lk01,east,10,5,5
lk02,east,12,6,8
"""
    files["data/locker_modules.csv"] = """locker_id,temperature_zone,capacity_per_module,max_modules,module_cost,energy_kwh_per_module
lk01,ambient,20,1,2,2
lk01,chilled,20,1,3,3
lk02,ambient,20,1,2,2
lk02,chilled,20,1,3,3
"""
    files["data/zone_locker_arcs.csv"] = """zone_id,locker_id,travel_minutes,delivery_cost_per_order
z001,lk01,5,1
z001,lk02,6,1
z002,lk01,5,1
"""
    return files


CLEAN_MINIMUM = """row_type,locker_id,zone_id,temperature_zone,value
open,lk01,,,1
module,lk01,,ambient,1
module,lk01,,chilled,1
assignment,lk01,z001,,8
assignment,lk01,z002,chilled,6
unmet,,z001,,2
unmet,,z002,chilled,2
"""

CLEAN_SPLIT = """row_type,locker_id,zone_id,temperature_zone,value
open,lk01,,,1
open,lk02,,,1
module,lk01,,ambient,1
module,lk01,,chilled,1
module,lk02,,ambient,1
assignment,lk01,z001,,4
assignment,lk02,z001,ambient,6
assignment,lk01,z002,,8
"""

CLEAN_FULL_WITH_ZERO_UNMET = """row_type,locker_id,zone_id,temperature_zone,value
open,lk01,,,1
module,lk01,,ambient,1
module,lk01,,chilled,1
assignment,lk01,z001,ambient,10
assignment,lk01,z002,,8
unmet,,z001,ambient,0
unmet,,z002,,0
"""


def violation_key(requirement_id: str, index: list[str], rule_part: str) -> str:
    return json.dumps([requirement_id, index, rule_part], ensure_ascii=False)


def test_public_ir_has_verifiable_rule_and_data_provenance():
    files = load_public_files()
    ir = build_requirement_ir(files)
    assert ir.validation_issues(files) == []
    assert {item.requirement_id for item in ir.requirements} == {
        "demand_balance_and_service",
        "assignment_open_locker",
        "assignment_feasible_arc",
        "module_open_and_maximum",
        "module_integrality",
        "matching_temperature_capacity",
        "opening_staff_hours_bound",
        "locker_energy_limit",
    }
    for requirement in ir.requirements:
        assert requirement.source.issues(files) == []
        for source in requirement.payload["data_sources"]:
            content = files[source["source_file"]]
            assert source["quote"] in content
            assert hashlib.sha256(content.encode()).hexdigest() == source["sha256"]


@pytest.mark.parametrize("solution", [CLEAN_MINIMUM, CLEAN_SPLIT, CLEAN_FULL_WITH_ZERO_UNMET],
                         ids=["minimum-service", "split-full-service", "explicit-zero-unmet"])
def test_three_clean_solutions_pass_covered_public_rules(solution):
    result = check_solution_csv(solution, synthetic_files())
    assert result["business_status"] == PASS
    assert result["violations"] == []
    assert result["veto_enabled"] is False
    assert result["uncovered_rules"]
    assert all(item["status"] == UNKNOWN for item in result["uncovered_rules"])


def test_wrong_demand_balance_and_service_floor_have_stable_keys():
    wrong = CLEAN_MINIMUM.replace("assignment,lk01,z001,,8", "assignment,lk01,z001,,7")
    first = check_solution_csv(wrong, synthetic_files())
    second = check_solution_csv(wrong, synthetic_files())
    assert first["business_status"] == FAIL
    assert {item["key"] for item in first["violations"]} == {
        violation_key("demand_balance_and_service", ["z001"], "demand_conservation"),
        violation_key("demand_balance_and_service", ["z001"], "service_floor"),
    }
    assert [item["key"] for item in first["violations"]] == [
        item["key"] for item in second["violations"]]


def test_wrong_illegal_arc_and_unopened_locker_service_are_failures():
    wrong = CLEAN_MINIMUM.replace(
        "assignment,lk01,z002,chilled,6",
        "assignment,lk01,z002,chilled,5\nassignment,lk02,z002,chilled,1",
    )
    result = check_solution_csv(wrong, synthetic_files())
    assert result["business_status"] == FAIL
    assert {item["key"] for item in result["violations"]} == {
        violation_key("assignment_open_locker", ["z002", "lk02"], "inactive_flow"),
        violation_key("assignment_feasible_arc", ["z002", "lk02"], "capacity"),
        violation_key("matching_temperature_capacity", ["lk02", "chilled"], "capacity"),
    }


def test_wrong_module_maximum_and_energy_limit_are_failures():
    wrong = CLEAN_MINIMUM.replace("module,lk01,,chilled,1", "module,lk01,,chilled,2")
    result = check_solution_csv(wrong, synthetic_files())
    assert result["business_status"] == FAIL
    assert {item["key"] for item in result["violations"]} == {
        violation_key("module_open_and_maximum", ["lk01", "chilled"], "capacity"),
        violation_key("locker_energy_limit", ["lk01"], "capacity"),
    }


def test_module_integrality_and_ambiguous_duplicate_are_not_silent_passes():
    fractional = CLEAN_MINIMUM.replace("module,lk01,,ambient,1", "module,lk01,,ambient,1.5")
    fractional_result = check_solution_csv(fractional, synthetic_files())
    assert fractional_result["business_status"] == FAIL
    assert violation_key("module_integrality", ["lk01", "ambient"], "demand_conservation") in {
        item["key"] for item in fractional_result["violations"]}

    duplicate = CLEAN_MINIMUM + "unmet,,z001,,2\n"
    duplicate_result = check_solution_csv(duplicate, synthetic_files())
    assert duplicate_result["business_status"] == UNKNOWN
    assert any(item["rule_part"] == "duplicate_decision" and item["status"] == UNKNOWN
               for item in duplicate_result["violations"])


def test_service_floor_near_miss_respects_public_tolerance():
    files = synthetic_files()
    decisions = solution_to_decisions(CLEAN_MINIMUM, files)
    demand = next(row for row in decisions["demand"] if row["index"] == ("z001",))
    demand["served"] -= 2e-5
    demand["unmet"] += 2e-5
    result = check_decisions(decisions, public_files=files)
    assert result["business_status"] == FAIL
    assert [item["rule_part"] for item in result["violations"]] == ["service_floor"]

    within = solution_to_decisions(CLEAN_MINIMUM, files)
    demand = next(row for row in within["demand"] if row["index"] == ("z001",))
    demand["served"] -= 5e-6
    demand["unmet"] += 5e-6
    assert check_decisions(within, public_files=files)["business_status"] == PASS


def test_temperature_capacity_near_miss_respects_public_tolerance():
    files = synthetic_files()
    decisions = solution_to_decisions(CLEAN_MINIMUM, files)
    capacity = next(row for row in decisions["temperature_capacity"]
                    if row["index"] == ("lk01", "ambient"))
    capacity["flow"] = capacity["capacity"] + 2e-5
    result = check_decisions(decisions, public_files=files)
    assert result["business_status"] == FAIL
    assert [item["rule_part"] for item in result["violations"]] == ["capacity"]

    within = solution_to_decisions(CLEAN_MINIMUM, files)
    capacity = next(row for row in within["temperature_capacity"]
                    if row["index"] == ("lk01", "ambient"))
    capacity["flow"] = capacity["capacity"] + 5e-6
    assert check_decisions(within, public_files=files)["business_status"] == PASS


def test_saved_root_is_fail_with_48_service_floor_violations():
    result = check_solution_file(ROOT_SOLUTION)
    assert result["business_status"] == FAIL
    assert len(result["violations"]) == 48
    assert {item["requirement_id"] for item in result["violations"]} == {
        "demand_balance_and_service"}
    assert {item["rule_part"] for item in result["violations"]} == {"service_floor"}
    assert all(item["status"] == FAIL for item in result["violations"])
    assert result["veto_enabled"] is False


def test_saved_first_repair_has_74_errors_one_below_reported_count():
    first = check_solution_file(FIRST_REPAIR_SOLUTION)
    second = check_solution_file(FIRST_REPAIR_SOLUTION)
    assert first["business_status"] == FAIL
    assert len(first["violations"]) == OFFICIAL_REPORTED_ERROR_COUNT - 1
    counts = Counter((item["requirement_id"], item["rule_part"])
                     for item in first["violations"])
    assert counts == {
        ("demand_balance_and_service", "demand_conservation"): 44,
        ("matching_temperature_capacity", "capacity"): 30,
    }
    assert [item["key"] for item in first["violations"]] == [
        item["key"] for item in second["violations"]]
    assert all(item["status"] == FAIL for item in first["violations"])

    root = check_solution_file(ROOT_SOLUTION)
    difference = PublicDecisionChecker.diff(root, first)
    assert len(difference["fixed"]) == 48
    assert len(difference["introduced"]) == 74
    assert difference["remaining"] == []


def test_real_solution_csv_is_mapped_to_structured_decisions():
    files = load_public_files()
    decisions = solution_to_decisions(FIRST_REPAIR_SOLUTION.read_text(encoding="utf-8"), files)
    z001 = next(row for row in decisions["demand"] if row["index"] == ("z001",))
    assert z001 == {
        "index": ("z001",), "demand": 24.0, "served": 53.0,
        "unmet": 0.0, "minimum_service_rate": 0.912,
    }
    assert len(decisions["assignment_open"]) == 76
    assert len(decisions["module_bounds"]) == 28
    assert len(decisions["staff"]) == 12
    assert len(decisions["energy"]) == 12

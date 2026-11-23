import hashlib

import pytest

from ora_agent.cleanroom import FAIL, PASS, UNKNOWN
from ora_agent.requirement_ir import (
    PublicDecisionChecker,
    Requirement,
    RequirementIR,
    SourceRef,
    candidate_binding_gate,
)


def public_packet():
    text = (
        "Serve at least 80% of orders and conserve demand. "
        "Active links have capacity and minimum flow. "
        "Count each area population once. Recompute the objective from decisions."
    )
    return {"PROBLEM_STATEMENT.md": text}


def source(text_name="PROBLEM_STATEMENT.md", quote="Serve at least 80% of orders"):
    content = public_packet()[text_name]
    return SourceRef(text_name, quote, hashlib.sha256(content.encode()).hexdigest())


def requirement(kind="demand_balance", key="zones", requirement_id="R-demand", payload=None):
    return Requirement(
        requirement_id, kind, source(), {"decision_key": key},
        payload if payload is not None else {"minimum_service_rate": 0.8},
    )


def checker_for(item, omissions=None):
    ir = RequirementIR("synthetic", "minimize", (item,), omissions or {})
    return PublicDecisionChecker(ir, public_packet())


def test_source_binding_and_presolve_gate_do_not_claim_semantic_verification():
    item = requirement()
    ir = RequirementIR("synthetic", "minimize", (item,))
    gate = candidate_binding_gate(
        ir, public_packet(), "m.addCons(served + unmet == demand)",
        {"R-demand": {"code_anchor": "served + unmet == demand", "output_fields": ["served", "unmet"]}},
    )
    assert gate["ready_for_solve"]
    assert not gate["model_verified"]
    assert gate["business_status"] == "not_evaluated"
    assert gate["post_solve_obligations"] == ["R-demand"]
    gate["unresolved"] = []
    bad = candidate_binding_gate(ir, public_packet(), "m.optimize()", {})
    assert not bad["ready_for_solve"]
    assert bad["unresolved"]


def test_forged_source_and_unresolved_omission_are_unknown_not_pass():
    item = requirement()
    forged = SourceRef("hidden/reference.json", "gold", "bad-hash")
    item = Requirement(item.requirement_id, item.kind, forged, item.output_mapping, item.payload)
    result = checker_for(item).check({"zones": []})
    assert result["business_status"] == UNKNOWN
    assert not result["veto_enabled"]
    valid = checker_for(requirement()).check({
        "zones": [{"index": "z1", "demand": 10, "served": 8, "unmet": 2}],
        "omitted_fields": ["unlisted_row"],
    })
    assert valid["business_status"] == UNKNOWN


def test_demand_conservation_floor_and_stable_repair_diff():
    checker = checker_for(requirement())
    clean = {"zones": [{"index": "z1", "demand": 10, "served": 8, "unmet": 2}]}
    assert checker.check(clean)["business_status"] == PASS
    floor = checker.check({"zones": [{"index": "z1", "demand": 10, "served": 7, "unmet": 3}]})
    assert floor["business_status"] == FAIL
    assert floor["violations"][0]["rule_part"] == "service_floor"
    balance = checker.check({"zones": [{"index": "z1", "demand": 10, "served": 8, "unmet": 1}]})
    assert balance["violations"][0]["rule_part"] == "demand_conservation"
    difference = checker.diff(floor, balance)
    assert difference["fixed"] == [floor["violations"][0]["key"]]
    assert difference["introduced"] == [balance["violations"][0]["key"]]


def test_unique_population_coverage_deduplicates_serve_links():
    item = requirement("unique_coverage", "areas", "R-coverage", {"minimum_coverage_rate": 0.5})
    checker = checker_for(item)
    rows = [
        {"index": "link-a", "area_id": "a", "population": 100, "served": True},
        {"index": "link-b", "area_id": "a", "population": 100, "served": True},
        {"index": "link-c", "area_id": "b", "population": 100, "served": False},
    ]
    assert checker.check({"areas": rows})["business_status"] == PASS
    stricter = requirement("unique_coverage", "areas", "R-coverage", {"minimum_coverage_rate": 0.6})
    result = checker_for(stricter).check({"areas": rows})
    assert result["business_status"] == FAIL
    assert result["violations"][0]["rule_part"] == "coverage_floor"


def test_conditional_bounds_cover_inactive_lower_and_capacity_without_false_blocking_zero_use():
    item = requirement("conditional_bounds", "links", "R-links", {})
    checker = checker_for(item)
    clean = {"links": [{"index": "l1", "use": 1, "flow": 0, "minimum_flow": 0, "capacity": 10}]}
    assert checker.check(clean)["business_status"] == PASS
    cases = [
        ({"index": "l1", "use": 0, "flow": 1, "minimum_flow": 0, "capacity": 10}, "inactive_flow"),
        ({"index": "l1", "use": 1, "flow": 5, "minimum_flow": 6, "capacity": 10}, "minimum_flow"),
        ({"index": "l1", "use": 1, "flow": 11, "minimum_flow": 0, "capacity": 10}, "capacity"),
    ]
    for row, rule_part in cases:
        result = checker.check({"links": [row]})
        assert result["business_status"] == FAIL
        assert result["violations"][0]["rule_part"] == rule_part


def temporal_step(index, arrival, start, end, travel):
    return {
        "index": index, "arrival": arrival, "service_start": start, "service_end": end,
        "earliest": 0, "latest": 30, "service_duration": 5, "travel_from_previous": travel,
    }


def test_temporal_sequence_checks_windows_duration_and_travel():
    item = requirement("temporal_sequence", "routes", "R-time", {})
    checker = checker_for(item)
    clean = {"routes": [[temporal_step("s1", 0, 5, 10, 0), temporal_step("s2", 20, 20, 25, 5)]]}
    assert checker.check(clean)["business_status"] == PASS
    wrong = {"routes": [[temporal_step("s1", 0, 5, 10, 0), temporal_step("s2", 15, 20, 25, 10)]]}
    result = checker.check(wrong)
    assert result["business_status"] == FAIL
    assert result["violations"][0]["rule_part"] == "travel_continuity"
    late = {"routes": [[temporal_step("s1", 0, 31, 36, 0)]]}
    assert any(row["rule_part"] == "time_window" for row in checker.check(late)["violations"])


def test_objective_recompute_and_nonfinite_values():
    item = requirement("objective_recompute", "objective_terms", "R-objective", {})
    item = Requirement(
        item.requirement_id, item.kind, item.source,
        {"decision_key": "objective_terms", "reported_key": "reported_objective"}, {},
    )
    checker = checker_for(item)
    decisions = {
        "objective_terms": [
            {"index": "service", "value": 2, "coefficient": 5},
            {"index": "discount", "value": 3, "coefficient": -1},
        ],
        "reported_objective": 7,
    }
    clean = checker.check(decisions)
    assert clean["business_status"] == PASS
    assert clean["objective"] == 7
    decisions["reported_objective"] = 8
    assert checker.check(decisions)["business_status"] == FAIL
    decisions["reported_objective"] = float("nan")
    assert checker.check(decisions)["business_status"] == UNKNOWN


def test_public_omission_reconstruction_and_checker_immutability():
    item = requirement()
    checker = checker_for(item, {"nurse_day": "rest"})
    clean = checker.check({
        "zones": [{"index": "z1", "demand": 10, "served": 8, "unmet": 2}],
        "omitted_fields": ["nurse_day"],
    })
    assert clean["business_status"] == PASS
    assert clean["reconstructed_omissions"] == {"nurse_day": "rest"}
    checker.ir.omission_defaults["new_field"] = "zero"
    with pytest.raises(ValueError, match="changed"):
        checker.check({"zones": []})


def test_repair_diff_rejects_different_checker_versions():
    checker = checker_for(requirement())
    first = checker.check({"zones": [{"index": "z1", "demand": 10, "served": 7, "unmet": 3}]})
    second = dict(first, checker_sha256="different")
    with pytest.raises(ValueError, match="versions"):
        checker.diff(first, second)

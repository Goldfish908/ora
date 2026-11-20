from scripts.retailopt_governance import build_governor


def manifest():
    data = {"products": ["p"], "locations": ["l"], "periods": 1,
            "shelf_life": {"p": 2}, "demand_curve": {"p": [2]},
            "demand_share": {"l": 1.0}, "network": {"sub_edges": []}}
    clean = {"I": {}, "sales": {"p|l|1|1": 1.0, "p|l|1|2": 1.0}, "lost": {}, "sub": {}}
    wrong_initial = {"I": {"p|l|1|1": 1.0}, "sales": clean["sales"], "lost": {}, "sub": {}}
    wrong_demand = {"I": {}, "sales": clean["sales"], "lost": {"p|l|1": 1.0}, "sub": {}}
    cases = []
    for index in range(3):
        cases.append({"case_id": f"clean{index}", "expected": "pass", "mutation": "clean_reference",
                      "artifact": {"data": data, "solution": clean}})
        cases.append({"case_id": f"initial{index}", "expected": "fail", "mutation": "fabricated_initial_inventory",
                      "artifact": {"data": data, "solution": wrong_initial}})
        cases.append({"case_id": f"demand{index}", "expected": "fail", "mutation": "demand_balance_broken",
                      "artifact": {"data": data, "solution": wrong_demand}})
    return {"cases": cases}


def test_scoped_checks_gain_veto_only_after_paired_precision_replay():
    governor = build_governor(manifest(), include_demand=True)
    assert governor.checks["L1_execution"].status == "veto_enabled"
    assert governor.checks["L2_initial_inventory"].status == "veto_enabled"
    assert governor.checks["L2_demand_balance"].status == "veto_enabled"
    assert governor.final_accept({"L1_execution": "pass", "L2_initial_inventory": "pass",
                                  "L2_demand_balance": "pass"}) == (True, [])
    accepted, reasons = governor.final_accept({"L1_execution": "pass", "L2_initial_inventory": "fail",
                                                "L2_demand_balance": "pass"})
    assert not accepted and "L2_initial_inventory:fail" in reasons

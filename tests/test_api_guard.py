import pytest

from ora_agent.api_guard import repair_known_api_errors
from ora_agent.oragentbench import validate_solver_code


def test_guard_repairs_only_narrow_known_api_errors():
    code = '''from pypscip import Model, QuickSum
m = Model()
m.setParam("gaprel", 0.0005)
m.setObjective(quicksum([]), sense="min")
x = m.getObjval()
n = m.getNsolns()
'''
    repaired, applied = repair_known_api_errors(code)
    assert "from pyscipopt import Model, quicksum" in repaired
    assert 'setRealParam("limits/gap"' in repaired
    assert 'sense="minimize"' in repaired
    assert "getObjVal()" in repaired
    assert "getNSols()" in repaired
    assert {item["category"] for item in applied} == {
        "wrong_import", "gap_parameter", "objective_sense", "objective_method", "solution_count_method"}
    variant, _ = repair_known_api_errors("from scipyopt import Model, quicksum\n")
    assert "from pyscipopt import Model, quicksum" in variant


def test_guard_rejects_syntactically_invalid_result():
    with pytest.raises(ValueError):
        repair_known_api_errors('from pypscip import Model, QuickSum\nif True print(1')


def test_guard_leaves_other_code_unchanged():
    assert repair_known_api_errors("print('ok')") == ("print('ok')", [])


def test_guard_runs_before_completeness_validation():
    code = ("import scipopt as sp\n"
            "opt = sp.Optimize()\n"
            "x = opt.createVar('x', vtype='B')\n"
            "opt.setUb(x, 1)\n"
            "opt.getNvars()\n"
            "opt.getNconss()\n"
            "opt.solve()\n"
            "with open('/app/submissions/solution.csv', 'w') as handle:\n"
            "    handle.write('')\n" + "#" * 500)
    repaired, _ = repair_known_api_errors(code)
    validate_solver_code(repaired)
    assert "opt = Model()" in repaired
    assert "opt.addVar" in repaired
    assert "opt.chgVarUb" in repaired
    assert "opt.getNVars()" in repaired
    assert "opt.getNConss()" in repaired
    assert "opt.optimize()" in repaired
    singular, applied = repair_known_api_errors("opt.getNCons()\n")
    assert singular == "opt.getNConss()\n"
    assert applied[0]["category"] == "constraint_count_method"


def test_guard_replaces_nonexistent_scip_constructor():
    code = "from pyscipopt import SCIP\nmodel = SCIP()\n"
    repaired, applied = repair_known_api_errors(code)
    assert repaired == "from pyscipopt import Model\nmodel = Model()\n"
    assert {item["category"] for item in applied} == {"wrong_import", "model_construction"}


def test_guard_removes_scip_from_a_multi_import_without_duplicate_model():
    code = "from pyscipopt import Model, quicksum, SCIP\nmodel = SCIP()\n"
    repaired, applied = repair_known_api_errors(code)
    assert repaired == "from pyscipopt import Model, quicksum\nmodel = Model()\n"
    assert {item["category"] for item in applied} == {"wrong_import", "model_construction"}
    assert repair_known_api_errors("class SCIP:\n    pass\nmodel = SCIP()\n") == (
        "class SCIP:\n    pass\nmodel = SCIP()\n", [])


def test_output_schema_repair_is_explicit_and_scoped_to_public_contract():
    from ora_agent.api_guard import repair_public_output_contract

    code = 'rows.append(["material_purchase", t, m, pl, "", "", "1"])\nrows.append(["plant_startup", t, pl, pl, "", "", "1"])'
    document = "Allowed row types are procure_material and startup."
    repaired, applied = repair_public_output_contract(code, "industrial_supply_planning", document)
    assert "procure_material" in repaired
    assert "startup" in repaired
    assert "material_purchase" not in repaired
    assert "plant_startup" not in repaired
    assert all(item["category"] == "public_output_contract" for item in applied)
    assert repair_public_output_contract(code, "unrelated_task", document) == (code, [])
    assert repair_public_output_contract(code, "industrial_supply_planning", "No output contract") == (code, [])
    assert repair_known_api_errors(code) == (code, [])


def test_verified_quicksum_and_objective_transformations():
    code = ("from pyscipopt import Model\n"
            "m = Model()\n"
            "x = m.addVar(vtype='B')\n"
            "m.setObjective(0)\n"
            "m.changeCoeff(x, 2.5)\n"
            "m.addCons(m.quicksum([x]) <= 1)\n"
            "m.setMaximize()\n"
            "m.optimize()\n")
    repaired, applied = repair_known_api_errors(code)
    assert "from pyscipopt import quicksum" in repaired
    assert "m.quicksum" not in repaired
    assert "quicksum([x])" in repaired
    assert "m.setObjective(m.getObjective() + 2.5 * x)" in repaired
    assert {item["category"] for item in applied} == {"module_quicksum", "objective_coefficient"}


def test_guard_preserves_valid_python311_fstring_source():
    code = ('from pyscipopt import Model\n'
            'm = Model()\n'
            'x = m.addVar(vtype="B")\n'
            'm.addCons(m.quicksum([x]) <= 1)\n'
            'w = {"max_latency_ms": 5}\n'
            'print(f"latency {w[\'max_latency_ms\']}")\n')
    repaired, _ = repair_known_api_errors(code)
    assert 'print(f"latency {w[\'max_latency_ms\']}")' in repaired
    compile(repaired, "solve.py", "exec")


def test_gaprel_alias_and_maximize_direction():
    code = ('from pyscipopt import Model\n'
            'm = Model()\n'
            'x = m.addVar(vtype="B", obj=1.0)\n'
            'm.setRealParam("gaprel", 0.0005)\n'
            'm.setMinimize(False)\n'
            'm.optimize()\n')
    repaired, applied = repair_known_api_errors(code)
    assert 'setRealParam("limits/gap", 0.0005)' in repaired
    assert 'setMinimize(False)' not in repaired
    assert 'setMaximize()' in repaired
    assert {item["category"] for item in applied} == {"gap_parameter", "objective_direction"}


def test_gaplimit_is_added_to_status_allowlist_without_duplicate():
    code = ('from pyscipopt import Model\n'
            'status = "gaplimit"\n'
            'if status not in ("optimal", "gap", "timelimit", "bestsollimit", "gaptime"):\n'
            '    raise RuntimeError("discard a valid solution")\n')
    repaired, applied = repair_known_api_errors(code)
    assert '"gaplimit"' in repaired
    assert applied[0]["category"] == "solver_status_acceptance"
    _, second = repair_known_api_errors(repaired)
    assert all(item["category"] != "solver_status_acceptance" for item in second)

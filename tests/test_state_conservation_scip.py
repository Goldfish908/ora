import pytest

from scripts.scoped_ir_state_conservation import (
    CASES,
    binding_for,
    independent_score,
    repair_initialization,
)


def test_controlled_scorer_rejects_phantom_initial_inventory():
    case = CASES[0]
    solution = {"variables": {"stock_0": 1, "stock_1": 0, "production": 0, "demand": 1},
                "objective": 0}
    score = independent_score(case, solution)
    assert score["business_correct"] is False
    assert score["checks"]["flow_conservation"] is True
    assert score["checks"]["explicit_initial_state"] is False


def test_initialization_repair_inserts_constraint_before_optimize():
    case = CASES[1]
    code = '''from pyscipopt import Model
m = Model()
opening = m.addVar(name="opening", lb=0)
m.optimize()
'''
    repaired = repair_initialization(code, binding_for(case))
    assert 'm.addCons(opening == 0, "scoped_initial_state")' in repaired
    assert repaired.index("addCons") < repaired.index("m.optimize")


def test_initialization_repair_refuses_missing_variable_binding():
    with pytest.raises(ValueError, match="matching PySCIPOpt addVar"):
        repair_initialization("m.optimize()\n", binding_for(CASES[0]))

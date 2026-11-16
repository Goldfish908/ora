from scripts.m3_industryor import countable_witness_feedback, feedback_msg


CONFIG = {"1": {"evidence": "The variables count food items."}}


def test_countable_witness_must_fire_on_continuous_food_variables():
    code = 'x = m.addVar(name="Steak", lb=0, vtype="C")'
    feedback = countable_witness_feedback(CONFIG, 1, code)
    assert "COUNTABLE_INTEGER" in feedback
    assert "INTEGER" in feedback


def test_countable_witness_must_pass_integer_and_unregistered_cases():
    integer = 'x = m.addVar(name="Steak", lb=0, vtype="I")'
    continuous = 'x = m.addVar(name="Steak", lb=0, vtype="C")'
    assert countable_witness_feedback(CONFIG, 1, integer) is None
    assert countable_witness_feedback(CONFIG, 2, continuous) is None
    assert countable_witness_feedback({}, 1, continuous) is None


def test_guard_feedback_reaches_repair_loop():
    feedback = "Deterministic witness COUNTABLE_INTEGER: use INTEGER"
    assert feedback_msg({"guard_feedback": feedback}) == feedback


def test_default_scip_variable_is_continuous_and_can_be_forced_integer():
    from scripts.m3_industryor import force_integer_variables, has_continuous_variables
    code = 'x = m.addVar(name="Food_1", lb=0, obj=3)'
    assert has_continuous_variables(code)
    assert countable_witness_feedback(CONFIG, 1, code)
    integer = force_integer_variables(code)
    assert not has_continuous_variables(integer)
    assert "vtype='I'" in integer.replace('"', "'")
    assert countable_witness_feedback(CONFIG, 1, integer) is None

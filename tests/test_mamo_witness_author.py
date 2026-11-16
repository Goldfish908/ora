from scripts.m3_industryor import countable_witness_feedback
from scripts.mamo_witness_author import evidence_matches


def test_evidence_must_be_verbatim_problem_text():
    question = "Each bottle of cola provides 150 calories."
    assert evidence_matches("bottle of cola", question)
    assert evidence_matches("Each   bottle\nof cola", question)
    assert not evidence_matches("continuous liquid", question)
    assert not evidence_matches("", question)


def test_guard_uses_authored_entity_not_food_assumption():
    config = {"9": {"entity": "individual brownies", "evidence": "each brownie"}}
    code = 'x = m.addVar(name="brownie", vtype="C")'
    feedback = countable_witness_feedback(config, 9, code)
    assert "individual brownies" in feedback
    assert "food" not in feedback

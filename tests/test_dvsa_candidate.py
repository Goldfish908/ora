from scripts.dvsa_candidate import render_prompt


def test_candidate_prompt_preserves_json_and_does_not_add_public_answer():
    prompt = render_prompt("BWOR-TEST", "Question with {braces}.", '{"x": {"domain": "real", "lb": 0}}')
    assert 'schema_version equal to "dvsa.model.v0.1"' in prompt
    assert "problem_id equal to BWOR-TEST" in prompt
    assert "Question with {braces}." in prompt
    assert '{"x": {"domain": "real", "lb": 0}}' in prompt
    assert "5450" not in prompt

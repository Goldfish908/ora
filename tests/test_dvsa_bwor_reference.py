from scripts.dvsa_bwor_reference import load_rows, render_prompt


def test_reference_prompt_preserves_json_example_and_literal_question_braces():
    prompt = render_prompt("BWOR-TEST", "A question with {literal_braces}.")
    assert '"schema_version": "dvsa.model.v0.1"' in prompt
    assert '"problem_id": "BWOR-TEST"' in prompt
    assert "A question with {literal_braces}." in prompt


def test_reference_loader_returns_only_authorized_dev_ids():
    rows = load_rows("dev")
    expected = set(open("data/dvsa/bwor/dev.txt").read().splitlines())
    assert {row["id"] for row in rows} == expected
    assert len(rows) == 16


def test_public_answer_is_not_inserted_into_reference_prompt():
    row = load_rows("dev")[0]
    prompt = render_prompt(row["id"], row["en_question"])
    assert str(row["answer"]) not in prompt
    assert "reference answer or target objective" in prompt

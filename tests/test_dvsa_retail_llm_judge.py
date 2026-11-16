from pathlib import Path

from scripts.dvsa_retail_llm_judge import eligible_artifacts, render_prompt

ROOT = Path(__file__).resolve().parents[1]


def test_retail_fixed_artifacts_have_expected_labels_and_no_prompt_leak():
    artifacts = eligible_artifacts(
        ROOT / "work/mem_evo/replay_gen1/m1_pilot_schema_sol_gen1.jsonl",
        ROOT / "work/mem_evo/replay_gen1/sandbox")
    assert len(artifacts) == 16
    assert sum(row["wrong"] for row in artifacts) == 10
    assert sum(not row["wrong"] for row in artifacts) == 6
    assert {rule for row in artifacts for rule in row["expected_rules"]} <= {"C-INIT", "C-DEMAND"}
    prompt = render_prompt(artifacts[0], "test memory")
    assert "reference_objective" not in prompt
    assert '"wrong"' not in prompt
    assert "initial_score" not in prompt
    assert artifacts[0]["original_key"] not in artifacts[0]["artifact_id"]

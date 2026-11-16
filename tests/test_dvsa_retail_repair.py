import inspect
import json

from scripts import dvsa_retail_repair
from scripts.dvsa_retail_repair import (compact, render_prompt, run_repair_code,
                                        trigger)


def test_repair_trigger_distinguishes_semantic_and_execution_recovery():
    assert trigger("dvsa", {"status": "SATISFIED"}, True) == "no_call"
    assert trigger("dvsa", {"status": "VIOLATED"}, True) == "dvsa_violation"
    assert trigger("direct_legacy_witness", {"status": "VIOLATED"}, True) == "legacy_witness_violation"
    assert trigger("dvsa", {"status": "UNKNOWN"}, False) == "execution_failure_unknown_semantics"
    assert trigger("no_memory", {"status": "not_provided"}, True) == "scheduled_self_review"


def test_every_arm_executes_its_own_response_not_previous_arm_code():
    source = inspect.getsource(dvsa_retail_repair.main)
    assert "run_repair_code(repair_code" in source
    assert "run_repair_code(code," not in source


def test_real_code_execution_and_solution_roundtrip(tmp_path):
    code = """import json
print('status: optimal')
print('objective: 4')
json.dump({'objective': 4, 'Q': {}, 'sales': {}, 'I': {}, 'W': {}, 'lost': {}, 'sub': {}, 'X': {}}, open('solution.json', 'w'))
"""
    result = run_repair_code(code, tmp_path, {"value": 2}, timeout=10)
    assert result["exec_status"] == "ok"
    assert result["solver_status"] == "optimal"
    assert result["solution"]["objective"] == 4
    assert json.loads((tmp_path / "data.json").read_text()) == {"value": 2}


def test_feedback_compaction_and_prompt_preserve_code_without_reference_answer():
    feedback = {"status": "VIOLATED", "violations": [
        {"asset_id": "a", "violations": [{"lhs": i} for i in range(20)]}]}
    compacted = compact(feedback)
    assert len(compacted["violations"][0]["violations"]) == 8
    prompt = render_prompt("business", "code {x}", "{}", "", json.dumps(compacted))
    assert "code {x}" in prompt
    assert "5450" not in prompt


def test_execution_recovery_is_limited_to_failed_execution_after_a_solver_attempt():
    from scripts.dvsa_retail_execution_recovery import needs_recovery
    assert needs_recovery({"final_score": {"status": "no_solution"}, "solver_calls": 1})
    assert not needs_recovery({"final_score": {"status": "scored"}, "solver_calls": 1})
    assert not needs_recovery({"final_score": {"status": "no_solution"}, "solver_calls": 0})


def test_direct_legacy_receives_same_text_memory_as_text_arm():
    source = inspect.getsource(dvsa_retail_repair.main)
    assert '{"text_memory", "dvsa", "direct_legacy_witness"}' in source

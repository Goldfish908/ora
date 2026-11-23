import json

from scripts.industryor_memory_evolution import (
    allocate_ids,
    paired_metrics,
    prepare,
    proposal_messages,
    question_rows,
)


def test_prepare_partitions_ids_and_selects_dev_only_cluster(tmp_path):
    prepare(tmp_path)
    splits = allocate_ids()
    assert [len(splits[name]) for name in ("dev", "gapcheck", "test")] == [40, 30, 30]
    assert set(splits["dev"]) | set(splits["gapcheck"]) | set(splits["test"]) == set(range(1, 101))
    assert not (set(splits["dev"]) & set(splits["gapcheck"])
                or set(splits["dev"]) & set(splits["test"])
                or set(splits["gapcheck"]) & set(splits["test"]))
    cluster = json.loads((tmp_path / "dev_cluster.json").read_text())
    assert cluster["signature"] == "pyscipopt_addvar_v"
    assert cluster["n_problems"] >= 3
    assert {int(task_id.split("_")[1]) for task_id in cluster["task_ids"]} <= set(splits["dev"])


def test_proposal_prompt_has_no_answers_or_non_dev_questions(tmp_path):
    prepare(tmp_path)
    prompt = proposal_messages(tmp_path)[0]["content"]
    rows = question_rows()
    splits = allocate_ids()
    assert "en_answer" not in prompt
    assert str(rows[splits["dev"][0]]["en_answer"]) not in prompt
    for split in ("gapcheck", "test"):
        for problem_id in splits[split]:
            assert rows[problem_id]["en_question"] not in prompt


def result(task_id, seed, success, calls):
    return {"task_id": task_id, "problem_id": int(task_id.split("_")[1]), "seed": seed,
            "status": "completed", "execution_success": success,
            "repair_cost": {"logical_llm_calls": calls}, "final": {"accepted": False}}


def test_paired_metrics_is_macro_by_problem_and_does_not_need_answers():
    control = [result("prob_001_A", seed, False, 1) for seed in (1, 2, 3)]
    control += [result("prob_002_A", seed, True, 1) for seed in (1, 2, 3)]
    treatment = [result("prob_001_A", seed, True, 0) for seed in (1, 2, 3)]
    treatment += [result("prob_002_A", seed, True, 0) for seed in (1, 2, 3)]
    asset = {"kind": "execution", "form": "guard", "guard": "addvar_v_to_vtype"}
    metrics = paired_metrics(control, treatment, asset)
    assert metrics["n_problems"] == 2
    assert metrics["execution_gain"] == 0.5
    assert metrics["execution_harm"] == 0
    assert metrics["llm_call_reduction"] == 1
    assert metrics["guard_contract_passed"] is True


def task_with_code(code):
    return {"signature": "pyscipopt_addvar_v", "selected": {"code": code}}


def test_guard_inference_uses_dev_variable_role_evidence():
    from scripts.industryor_memory_evolution import infer_guard
    named = [task_with_code("x = m.addVar(v='x1', vtype='I')")]
    typed = [task_with_code("x = m.addVar(v='I')")]
    ambiguous = [task_with_code("x = m.addVar(v='x1')")]
    assert infer_guard(named, "pyscipopt_addvar_v") == "addvar_v_to_name"
    assert infer_guard(typed, "pyscipopt_addvar_v") == "addvar_v_to_vtype"
    assert infer_guard(ambiguous, "pyscipopt_addvar_v") is None

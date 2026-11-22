import json

from ora_agent.cleanroom_analysis import failure_class, pair_win_safe, summarize_records


def record(task="task", true=False, phantom=False, generation_error=None, return_code=0,
           feasible=False, quality=0.0, official_errors=None, runner_code=0):
    return {"task": task, "true_correct": true, "phantom_proxy": phantom,
            "generation_error": generation_error, "execution": {"return_code": return_code},
            "feasible": feasible, "quality": quality, "objective": None, "proxy_match": phantom,
            "official": {"runner": {"return_code": runner_code},
                         "evaluation": {"errors": official_errors or []}, "reward_details": {}}}


def test_failure_classes_do_not_treat_failed_execution_as_unknown():
    assert failure_class(record(generation_error="ValueError: incomplete_artifact: no solver optimize call")) \
        == "incomplete_artifact"
    assert failure_class(record(return_code=1)) == "execution_error"
    assert failure_class(record(official_errors=["uncovered clinic"])) == "business_infeasible"
    assert failure_class(record(feasible=True, quality=0.3)) == "quality_shortfall"
    assert failure_class(record(phantom=True)) == "phantom_proxy"
    assert failure_class(record(runner_code=1)) == "evaluation_unknown"


def test_generation_cost_reads_both_phases(tmp_path):
    workspace = tmp_path / "attempt_0/app"
    generation = workspace.parent / "generation"
    generation.mkdir(parents=True)
    for phase, tokens in (("model", 100), ("solver", 250)):
        (generation / f"{phase}_generation.json").write_text(json.dumps({"response": {
            "usage": {"prompt_tokens": tokens, "completion_tokens": tokens // 2,
                      "total_tokens": tokens + tokens // 2,
                      "completion_tokens_details": {"reasoning_tokens": 3}},
            "request_wall_s": 1.25}}))
    row = record()
    row["workspace"] = str(workspace)
    summary = summarize_records([row])
    assert summary["cost"]["llm_calls"] == 2
    assert summary["cost"]["prompt_tokens"] == 350
    assert summary["cost"]["total_tokens"] == 525
    assert summary["cost"]["reasoning_tokens"] == 6
    assert summary["cost"]["llm_latency_seconds"] == 2.5
    assert summary["cost"]["missing_usage_calls"] == 0
    assert summary["unknown"] == 1


def test_generation_cost_includes_a_runtime_patch(tmp_path):
    workspace = tmp_path / "attempt_0/app"
    generation = workspace.parent / "generation"
    generation.mkdir(parents=True)
    (generation / "runtime_patch_generation.json").write_text(json.dumps({"response": {
        "usage": {"prompt_tokens": 40, "completion_tokens": 5, "total_tokens": 45},
        "request_wall_s": 0.75}}))
    row = record()
    row["workspace"] = str(workspace)
    summary = summarize_records([row])
    assert summary["cost"]["llm_calls"] == 1
    assert summary["cost"]["total_tokens"] == 45
    assert summary["cost"]["missing_usage_calls"] == 0


def test_pairing_requires_same_coverage_and_preserves_wins():
    before = [record("a", true=True), record("b", phantom=True)]
    after = [record("a", true=False), record("b", true=True)]
    comparison = pair_win_safe(before, after)
    assert comparison["lost_true_correct"] == ["a"]
    assert comparison["gained_true_correct"] == ["b"]
    assert comparison["removed_phantom"] == ["b"]
    assert not comparison["win_safe"]
    assert pair_win_safe(before, before)["win_safe"]
    assert not pair_win_safe(before, after[:1])["win_safe"]


def test_generation_cost_includes_decision_repair(tmp_path):
    workspace = tmp_path / "attempt_0/app"
    generation = workspace.parent / "generation"
    generation.mkdir(parents=True)
    (generation / "decision_repair_generation.json").write_text(json.dumps({"response": {
        "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
        "request_wall_s": 0.5}}))
    row = record()
    row["workspace"] = str(workspace)
    summary = summarize_records([row])
    assert summary["cost"]["llm_calls"] == 1
    assert summary["cost"]["total_tokens"] == 25
    assert summary["cost"]["llm_latency_seconds"] == 0.5

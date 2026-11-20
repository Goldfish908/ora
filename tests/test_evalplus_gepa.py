import json
import sys
from types import SimpleNamespace

import pytest

if sys.version_info < (3, 10):
    pytest.skip("official GEPA requires Python 3.10+", allow_module_level=True)

from scripts.evalplus_gepa import EvalPlusAdapter, split_ids


def test_evalplus_split_is_complete_and_disjoint():
    problems = {f"HumanEval/{index}": {} for index in range(164)}
    splits = split_ids(problems)
    assert [len(splits[name]) for name in ("dev", "gapcheck", "test")] == [40, 60, 64]
    assert set(splits["dev"]) | set(splits["gapcheck"]) | set(splits["test"]) == set(problems)
    assert not (set(splits["dev"]) & set(splits["gapcheck"])
                or set(splits["dev"]) & set(splits["test"])
                or set(splits["gapcheck"]) & set(splits["test"]))


def test_reflection_has_original_test_feedback_but_not_plus_verdict():
    record = {"task_id": "HumanEval/0", "problem": "def f(x):", "code": "def f(x): return x",
              "feedback": "Original HumanEval tests: fail", "plus_status": "fail"}
    dataset = EvalPlusAdapter.make_reflective_dataset(
        object(), {"conventions": ""}, SimpleNamespace(trajectories=[record]), ["conventions"])
    serialized = json.dumps(dataset)
    assert "Original HumanEval tests" in serialized
    assert "plus_status" not in serialized
    assert "def f(x)" in serialized


def test_analysis_maps_slash_task_ids_to_rollout_paths(tmp_path):
    from scripts.retailopt_gepa import analyze, digest_text
    record = {"executable": True, "proxy_match": True, "true_correct": True,
              "phantom": False, "phantom_proxy": False, "new_llm_calls": 0,
              "completion_tokens": 0, "total_tokens": 0, "llm_latency_s": 0}
    directory = tmp_path / "rollouts" / digest_text("")
    directory.mkdir(parents=True)
    (directory / "HumanEval_100.json").write_text(json.dumps(record))
    result = SimpleNamespace(candidates=[{"conventions": ""}], parents=[[]],
                             discovery_eval_counts=[0], val_aggregate_scores=[1.0])
    analysis = analyze(result, [{"scenario_id": "HumanEval/100"}], tmp_path)
    assert analysis["curves"][0]["records"] == 1
    assert analysis["curves"][0]["runner_errors"] == 0
    assert analysis["curves"][0]["true_correct"] == 1


def test_cached_generation_error_is_retried(tmp_path, monkeypatch):
    from scripts import evalplus_gepa as module
    from scripts.retailopt_gepa import digest_text

    adapter = EvalPlusAdapter.__new__(EvalPlusAdapter)
    adapter.outdir = tmp_path
    adapter.problems = {"HumanEval/0": {"prompt": "def f(x):", "entry_point": "f"}}
    adapter.expected = {"HumanEval/0": {}}
    adapter.run_seed = 0
    adapter.task_splits = {}
    adapter.governor = None
    adapter.audit_manifest = None
    adapter.evolve_verification = False
    adapter.config = SimpleNamespace(model="Qwen3_8-27B")
    path = tmp_path / "rollouts" / digest_text("") / "HumanEval_0.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"candidate_sha256": digest_text(""), "task_id": "HumanEval/0",
                                "generation_error": "HTTP 503"}))
    calls = []

    def chat(*args, **kwargs):
        calls.append(args)
        return {"content": "def f(x):\n    return x", "usage": {}}

    monkeypatch.setattr(module.llm_mod, "chat", chat)
    monkeypatch.setattr(module, "check_correctness", lambda *args, **kwargs: {
        "base": ("pass", []), "plus": ("pass", [])})
    record = adapter._rollout("HumanEval/0", {"conventions": ""})
    assert len(calls) == 1
    assert record["generation_error"] is None
    assert record["proxy_match"] is True
    assert adapter._rollout("HumanEval/0", {"conventions": ""})["new_llm_calls"] == 0
    assert len(calls) == 1


def test_cached_generation_error_is_retried_and_returned_on_repeated_failure(tmp_path, monkeypatch):
    from ora_agent import llm as llm_mod

    adapter = EvalPlusAdapter.__new__(EvalPlusAdapter)
    adapter.outdir = tmp_path
    adapter.problems = {"HumanEval/0": {"prompt": "def f(x):", "entry_point": "f"}}
    adapter.expected = {}
    adapter.run_seed = 0
    adapter.task_splits = {}
    adapter.governor = None
    adapter.evolve_verification = False
    adapter.config = SimpleNamespace(model="test-model")
    directory = tmp_path / "rollouts" / "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    directory.mkdir(parents=True)
    (directory / "HumanEval_0.json").write_text(json.dumps({
        "candidate_sha256": directory.name, "task_id": "HumanEval/0",
        "generation_error": "HTTP 503"}))

    def fail_request(*args, **kwargs):
        raise RuntimeError("service unavailable")

    monkeypatch.setattr(llm_mod, "chat", fail_request)
    batch = adapter.evaluate(["HumanEval/0"], {"conventions": ""})
    assert batch.scores == [0.0]
    assert batch.outputs[0]["base_status"] == "runner_error"
    assert batch.outputs[0]["generation_error"] == "RuntimeError: service unavailable"
    assert batch.outputs[0]["new_llm_calls"] == 1

import json

from ora_agent.binding_protocol import BindingProposal, validate_proposal
from scripts.internal_cold_start import generate, proposal_prompt


def test_prompt_contains_only_schema_question_and_source_span():
    prompt = proposal_prompt("resource_bound", "Food has protein.", "protein", '{"x": {}}')
    assert "[PROBLEM]\nFood has protein." in prompt
    assert "[REQUIRED VERBATIM SOURCE SPAN]\nprotein" in prompt
    assert '"x": {}' in prompt
    assert "resource_bound" in prompt
    assert "no reference model or answer is available" in prompt


def test_generate_records_raw_response_without_storing_config(tmp_path, monkeypatch):
    payload = {"mechanism_id": "resource_bound", "source_span": "protein",
               "terms": [], "relation": "ge", "limit": 700}

    def chat(*args, **kwargs):
        return {"content": json.dumps(payload), "model": "Qwen3_8-27B",
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
                "latency_s": 0.1, "finish_reason": "stop"}

    monkeypatch.setattr("scripts.internal_cold_start.llm_mod.chat", chat)
    proposal, record = generate("resource_bound", "Food has protein.", "protein", "{}",
                                tmp_path, None)
    assert proposal.mechanism_id == "resource_bound"
    assert proposal.source_span == "protein"
    assert proposal.payload == payload
    assert record["llm_calls"] == 1
    saved = json.loads((tmp_path / "generation.json").read_text())
    assert saved["response"]["model"] == "Qwen3_8-27B"
    assert "config" not in saved
    assert "api_key" not in saved


def test_generate_rejects_unexpected_mechanism_without_retry(tmp_path, monkeypatch):
    calls = []

    def chat(*args, **kwargs):
        calls.append(args)
        return {"content": '{"mechanism_id":"objective_recompute"}', "usage": {}}

    monkeypatch.setattr("scripts.internal_cold_start.llm_mod.chat", chat)
    proposal, record = generate("resource_bound", "Food has protein.", "protein", "{}",
                                tmp_path, None)
    assert len(calls) == 1
    assert proposal.mechanism_id == "invalid_response"
    assert record["parse_error"] == "unexpected mechanism_id"
    result = validate_proposal(proposal, "Food has protein.", [])
    assert result["status"] == "unknown"
    assert result["accepted"] is False


def test_non_string_source_span_fails_closed():
    proposal = BindingProposal("resource_bound", "cold_start_proposal",
                               ["not a string"], {"terms": []})
    result = validate_proposal(proposal, "Food has protein.", [])
    assert result["status"] == "unknown"
    assert result["accepted"] is False


def test_saved_generation_is_reused_without_another_llm_call(tmp_path, monkeypatch):
    calls = []
    payload = {"mechanism_id": "resource_bound", "source_span": "protein",
               "terms": [], "relation": "ge", "limit": 700}

    def chat(*args, **kwargs):
        calls.append(args)
        return {"content": json.dumps(payload), "usage": {"total_tokens": 5}}

    monkeypatch.setattr("scripts.internal_cold_start.llm_mod.chat", chat)
    generate("resource_bound", "Food has protein.", "protein", "{}", tmp_path, None)
    _, resumed = generate("resource_bound", "Food has protein.", "protein", "{}", tmp_path, None)
    assert len(calls) == 1
    assert resumed["reused_saved_response"] is True
    assert resumed["llm_calls"] == 1
    assert resumed["response"]["usage"]["total_tokens"] == 5

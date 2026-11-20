import json
from pathlib import Path

from ora_agent import llm as llm_mod
from ora_agent.cleanroom_spec_audit import audit_specification
from ora_agent.oragentbench import TaskPacket

ROOT = Path(__file__).resolve().parents[1]


def config():
    return llm_mod.LLMConfig("http://localhost", "test-key", "test-model")


def packet():
    return TaskPacket.load(ROOT / "ORAgentBench/harbor_tasks/additive_microfactory_order_planning",
                           "manufacturing", "dev")


def test_spec_audit_records_provenance_support(tmp_path, monkeypatch):
    def fake_chat(messages, **kwargs):
        return {"tool_calls": [{"function": {"name": "submit_spec_audit", "arguments": json.dumps({
            "changed_features_covered": True, "scope_confirmed": True,
            "ungrounded_rules": [], "changed_rules": ["integer production"],
            "coverage_note": "covered"})}}]}
    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    result = audit_specification([packet()], "old", "new", config(), tmp_path)
    assert result["changed_features_covered"]
    assert not result["independent_semantic_truth"]
    assert (tmp_path / "specification_audit.json").exists()


def test_spec_audit_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_mod, "chat", lambda *args, **kwargs: {"tool_calls": []})
    result = audit_specification([packet()], "old", "new", config(), tmp_path)
    assert not result["changed_features_covered"]
    assert not result["scope_confirmed"]
    assert result["error"]

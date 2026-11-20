import json
from pathlib import Path

import pytest

from ora_agent import llm as llm_mod
from ora_agent.oragentbench import TaskPacket, generate_artifacts, parse_artifacts

ROOT = Path(__file__).resolve().parents[1]


def test_two_phase_artifact_generation(tmp_path, monkeypatch):
    packet = TaskPacket.load(ROOT / "ORAgentBench/harbor_tasks/additive_microfactory_order_planning",
                             "manufacturing", "dev")
    calls = []

    def fake_chat(messages, **kwargs):
        name = kwargs["extra"]["tools"][0]["function"]["name"]
        calls.append(name)
        if name == "submit_model":
            args = {"model_md": "# Model"}
        else:
            args = {"solve_py": "print(1)", "solve_log_md": "# Log"}
        return {"model": "test-model", "finish_reason": "stop",
                "tool_calls": [{"function": {"name": name, "arguments": json.dumps(args)}}]}

    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    config = llm_mod.LLMConfig("http://localhost", "test-key", "test-model")
    artifacts = generate_artifacts(packet, "spec", config, tmp_path)
    assert calls == ["submit_model", "submit_solver"]
    assert artifacts["model_md"] == "# Model"
    assert artifacts["solve_py"] == "print(1)"
    assert (tmp_path / "model_generation.json").exists()
    assert (tmp_path / "solver_generation.json").exists()


def test_truncated_artifact_is_explicit_failure():
    with pytest.raises(ValueError, match="truncated"):
        parse_artifacts({"finish_reason": "length", "tool_calls": []})

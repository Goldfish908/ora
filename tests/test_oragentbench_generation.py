import json
from pathlib import Path

import pytest

from ora_agent import llm as llm_mod
from ora_agent.oragentbench import TaskPacket, generate_artifacts, parse_artifacts, validate_solver_code

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
            code = ("from pyscipopt import Model\nm = Model()\nm.optimize()\n"
                    "sol_path = '/app/submissions/solution.csv'\n" + "#" * 500)
            args = {"solve_py": code, "solve_log_md": "# Log"}
        return {"model": "test-model", "finish_reason": "stop",
                "tool_calls": [{"function": {"name": name, "arguments": json.dumps(args)}}]}

    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    config = llm_mod.LLMConfig("http://localhost", "test-key", "test-model")
    artifacts = generate_artifacts(packet, "spec", config, tmp_path)
    assert calls == ["submit_model", "submit_solver"]
    assert artifacts["model_md"] == "# Model"
    assert artifacts["solve_py"].endswith("#" * 500)
    assert (tmp_path / "model_generation.json").exists()
    assert (tmp_path / "solver_generation.json").exists()


def test_evidence_regeneration_excludes_previous_artifacts():
    packet = TaskPacket.load(ROOT / "ORAgentBench/harbor_tasks/additive_microfactory_order_planning",
                             "manufacturing", "dev")
    repair = {"artifacts": {"solve_py": "old code"},
              "evidence": {"search_guidance": {"regenerate_from_evidence": True}}}
    messages = packet.prompt("spec", repair)
    assert "PREVIOUS ARTIFACTS" not in messages[1]["content"]
    assert "EVIDENCE-GUIDED REGENERATION" in messages[0]["content"]

    repair["evidence"]["search_guidance"]["regenerate_from_evidence"] = False
    messages = packet.prompt("spec", repair)
    assert "PREVIOUS ARTIFACTS" in messages[1]["content"]
    assert "TARGETED REPAIR" in messages[0]["content"]


def test_truncated_artifact_is_explicit_failure():
    with pytest.raises(ValueError, match="truncated"):
        parse_artifacts({"finish_reason": "length", "tool_calls": []})


def test_stub_is_not_accepted_as_complete_solver():
    with pytest.raises(ValueError, match="incomplete_artifact"):
        validate_solver_code("from pypcipopt import *  # placeholder")


def test_exception_pass_is_not_an_empty_function():
    code = ("from pyscipopt import Model\n"
            "def solve():\n"
            "    m = Model()\n"
            "    try:\n"
            "        m.optimize()\n"
            "    except ValueError:\n"
            "        pass\n"
            "    with open('/app/submissions/solution.csv', 'w') as handle:\n"
            "        handle.write('')\n" + "#" * 500)
    validate_solver_code(code)

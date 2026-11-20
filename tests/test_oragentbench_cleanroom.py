from pathlib import Path

import pytest

from ora_agent.cleanroom import FAIL, PASS
from ora_agent.cleanroom_witness import ExecutionContract, OfficialTaskPass
from ora_agent.oragentbench import TaskPacket, official_metrics, parse_artifacts

ROOT = Path(__file__).resolve().parents[1]


def test_public_packet_excludes_hidden_files():
    packet = TaskPacket.load(ROOT / "ORAgentBench/harbor_tasks/additive_microfactory_order_planning",
                             "manufacturing", "dev")
    prompt = str(packet.prompt(""))
    assert "orders.csv" in prompt
    assert "solve_reference.py" not in prompt
    assert "reference_metrics.json" not in prompt
    assert "evaluate_solution.py" not in prompt


def test_artifact_parser_requires_one_complete_tool_call():
    response = {"tool_calls": [{"function": {"name": "submit_artifacts", "arguments":
        '{"model_md":"model","solve_py":"print(1)","solve_log_md":"log"}'}}]}
    assert parse_artifacts(response)["solve_py"] == "print(1)"
    with pytest.raises(ValueError):
        parse_artifacts({"tool_calls": []})


def test_official_pass_threshold():
    assert official_metrics({"evaluation": {"profit": 2.0},
                             "reward": {"feasibility": 1.0, "quality": 0.5}})["true_correct"]
    assert not official_metrics({"evaluation": {"profit": 2.0},
                                 "reward": {"feasibility": 1.0, "quality": 0.4}})["true_correct"]


def test_witness_evaluators_do_not_confuse_execution_with_business_pass(tmp_path):
    submissions = tmp_path / "submissions"
    submissions.mkdir()
    (submissions / "solution.csv").write_text("solution")
    assert ExecutionContract()({"execution": {"return_code": 0}, "workspace": tmp_path}).status == PASS
    assert ExecutionContract()({"execution": {"return_code": 1}, "workspace": tmp_path}).status == FAIL

    passing = {"evaluation": {"profit": 2.0}, "reward": {"feasibility": 1.0, "quality": 2.0}}
    failing = {"evaluation": {"profit": 2.0}, "reward": {"feasibility": 0.0, "quality": 0.0}}
    assert OfficialTaskPass()({"official": passing}).status == PASS
    assert OfficialTaskPass()({"official": failing}).status == FAIL

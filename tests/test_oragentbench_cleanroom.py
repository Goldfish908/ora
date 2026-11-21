from pathlib import Path

import pytest

from ora_agent.cleanroom import FAIL, PASS
from ora_agent.cleanroom_witness import ExecutionContract, OfficialTaskPass, semantic_findings
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


def test_semantic_findings_distinguish_model_and_output_activation_missing(tmp_path):
    record = {"official": {"evaluation": {"errors": ["Inbound lane capacity/activation violated"]}},
              "artifacts": {"solve_py": "x = 1"}}
    findings = semantic_findings(record, tmp_path)
    assert {item["type"] for item in findings} == {
        "missing_activation_variable_in_model_and_output",
        "missing_activation_variable_in_model_and_output"}
    record["artifacts"]["solve_py"] = "use_plant_dc = 1"
    (tmp_path / "submissions").mkdir()
    (tmp_path / "submissions/solution.csv").write_text("variable,month,item,from,to,mode_id,quantity_tons\n")
    findings = semantic_findings(record, tmp_path)
    assert findings[0]["type"] == "missing_activation_row_in_output"
    assert findings[1]["type"] == "missing_activation_variable_in_model_and_output"


def test_activation_findings_become_explicit_repair_requirements():
    packet = TaskPacket.load(ROOT / "ORAgentBench/harbor_tasks/additive_microfactory_order_planning",
                             "manufacturing", "dev")
    messages = packet.prompt("", repair={
        "artifacts": {"solve_py": "x = 1"},
        "evidence": {"semantic_findings": [{"variable": "use_plant_dc", "type": "missing"}]}})
    system = messages[0]["content"]
    assert "REQUIRED ACTIVATION CONTRACT" in system
    assert "use_plant_dc" in system
    assert "min_shipment * activation" in system


def test_wrong_workspace_mutation_is_idempotent(tmp_path):
    from ora_agent.cleanroom_witness import _wrong_workspace

    source = tmp_path / "source"
    (source / "submissions").mkdir(parents=True)
    (source / "submissions/solution.csv").write_text("valid,header\n1,2\n")
    destination = tmp_path / "wrong"
    _wrong_workspace(source, destination, "missing_solution")
    _wrong_workspace(source, destination, "missing_solution")
    assert not (destination / "submissions/solution.csv").exists()
    _wrong_workspace(source, destination, "invalid_schema")
    _wrong_workspace(source, destination, "invalid_schema")
    assert (destination / "submissions/solution.csv").read_text() == "wrong,columns\n1,2,3\n"

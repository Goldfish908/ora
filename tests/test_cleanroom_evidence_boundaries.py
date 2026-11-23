import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ora_agent import cleanroom_witness
from ora_agent.cleanroom import EvidenceMemory, UNKNOWN
from ora_agent.cleanroom_analysis import failure_class
from ora_agent.cleanroom_witness import OfficialTaskPass
from ora_agent.decision_repair import (
    prepare_decision_repair_workspace,
    validate_decision_repair_code,
)
from ora_agent.oragentbench import TaskPacket, official_metrics

ROOT = Path(__file__).resolve().parents[1]


def official_payload(feasibility=1.0, quality=1.0, errors=None, runner_code=0):
    return {
        "evaluation": {
            "feasible": feasibility == 1.0,
            "objective": 2.0,
            "errors": errors or [],
        },
        "reward": {"feasibility": feasibility, "quality": quality},
        "reward_details": {},
        "runner": {"return_code": runner_code, "timed_out": False},
    }


@pytest.mark.parametrize("value", ["0.0", -1.0, True, float("nan"), float("inf")])
def test_invalid_feasibility_is_unknown_not_a_business_pass(value):
    metrics = official_metrics(official_payload(feasibility=value))
    assert metrics["evaluation_unknown"]
    assert not metrics["true_correct"]
    assert not metrics["feasible"]
    assert metrics["quality"] == 0.0
    assert metrics["objective"] is None
    assert OfficialTaskPass()({"official": official_payload(feasibility=value)}).status == UNKNOWN


@pytest.mark.parametrize("value", ["1.0", True, -0.1, float("nan"), float("inf")])
def test_invalid_quality_is_unknown(value):
    metrics = official_metrics(official_payload(quality=value))
    assert metrics["evaluation_unknown"]
    assert not metrics["true_correct"]


@pytest.mark.parametrize("payload", [
    {key: value for key, value in official_payload().items() if key != "reward"},
    official_payload(errors=["contradictory business error"]),
    official_payload(runner_code=1),
])
def test_missing_or_contradictory_official_payload_is_unknown(payload):
    metrics = official_metrics(payload)
    assert metrics["evaluation_unknown"]
    assert not metrics["true_correct"]
    assert OfficialTaskPass()({"official": payload}).status == UNKNOWN


def test_unknown_precedes_true_and_phantom_in_failure_attribution():
    record = {
        "true_correct": True,
        "phantom_proxy": True,
        "unknown": True,
        "official": official_payload(runner_code=1),
    }
    assert failure_class(record) == "evaluation_unknown"


def test_unknown_root_short_circuits_before_any_repair_generation(tmp_path, monkeypatch):
    memory = EvidenceMemory()
    packet = SimpleNamespace(
        name="task", domain="manufacturing", split="transfer",
        scope={"dataset": "oragentbench", "domain": "manufacturing"},
    )
    record = {
        "task": "task", "true_correct": True, "phantom_proxy": False,
        "unknown": True, "feasible": False, "quality": 0.0, "objective": None,
        "execution": {"return_code": 0}, "official": official_payload(runner_code=1),
        "artifacts": {"solve_py": "solver"}, "workspace": str(tmp_path / "root/app"),
    }
    monkeypatch.setattr(
        cleanroom_witness, "evaluate_witness",
        lambda *args: {"manufacturing_official_task_pass": UNKNOWN},
    )

    def unexpected_repair(*args, **kwargs):
        raise AssertionError("UNKNOWN must not enter repair generation")

    monkeypatch.setattr(cleanroom_witness, "repair_once", unexpected_repair)
    result = cleanroom_witness.repair_bounded(
        memory, packet, record, "spec", None, tmp_path / "repair",
    )
    assert result["status"] == "evaluation_unknown"
    assert result["attempts_used"] == 0
    assert result["history"] == []
    assert not result["final_accept"]
    assert not result["record"]["true_correct"]
    assert result["record"]["unknown"]


@pytest.mark.parametrize("tool_name,repair_kind", [
    ("submit_artifacts", "complete_artifacts"),
    ("submit_runtime_patch", "runtime_patch"),
    ("submit_decision_repair", "decision_repair"),
])
def test_repair_prompts_exclude_reference_derived_proxy_bits(tool_name, repair_kind):
    packet = TaskPacket.load(
        ROOT / "ORAgentBench/harbor_tasks/additive_microfactory_order_planning",
        "manufacturing", "dev",
    )
    packet = replace(packet, split="transfer")
    repair = {
        "artifacts": {"solve_py": "solver"},
        "decision_artifact": "a,b\n1,2\n",
        "evidence": {
            "execution": {"return_code": 0},
            "observed_metrics": {
                "feasible": False, "quality": 0.0, "objective": 100.0,
                "proxy_match": True, "phantom_proxy": True,
            },
            "search_guidance": {"repair_kind": repair_kind},
        },
    }
    messages = packet.prompt("spec", repair, tool_name=tool_name)
    prompt = "\n".join(message["content"] for message in messages)
    assert "proxy_match" not in prompt
    assert "phantom_proxy" not in prompt
    assert '"objective": 100.0' in prompt


def valid_decision_code():
    return (
        "import csv\n"
        "source = '/app/submissions/solution_original.csv'\n"
        "out = '/app/submissions/solution.csv'\n"
        "with open(source) as handle:\n"
        "    rows = list(csv.reader(handle))\n"
        "with open(out, 'w') as handle:\n"
        "    csv.writer(handle).writerows(rows)\n" + "#" * 300
    )


@pytest.mark.parametrize("injection", [
    "import importlib\nsolver = importlib.import_module('pyscipopt')\n",
    "import os\nos.system('echo forbidden')\n",
    "import asyncio\nasyncio.create_subprocess_exec('forbidden')\n",
])
def test_decision_repair_rejects_dynamic_solver_imports_and_external_processes(injection):
    with pytest.raises(ValueError):
        validate_decision_repair_code(injection + valid_decision_code())


def test_decision_repair_requires_real_incumbent_read_and_solution_write():
    code = (
        "source = '/app/submissions/solution_original.csv'\n"
        "out = '/app/submissions/solution.csv'\n"
        "print('open(source) and solution_original.csv are only mentioned, not read')\n"
        "print(out)\n" + "#" * 300
    )
    with pytest.raises(ValueError, match="read the incumbent and write"):
        validate_decision_repair_code(code)


def test_decision_workspace_preserves_parent_solver_bytes_with_api_guard_enabled(tmp_path):
    packet = TaskPacket.load(
        ROOT / "ORAgentBench/harbor_tasks/additive_microfactory_order_planning",
        "manufacturing", "transfer",
    )
    original = tmp_path / "original"
    (original / "submissions").mkdir(parents=True)
    parent_solver = b"from pyscipopt import Model\n# guarded parent bytes\n"
    (original / "submissions/solve.py").write_bytes(parent_solver)
    (original / "submissions/solution.csv").write_text("a,b\n1,2\n")
    artifacts = {
        "model_md": "model", "solve_py": "unguarded artifact", "solve_log_md": "log",
        "repair_solution_py": valid_decision_code(), "repair_log_md": "repair log",
    }
    workspace = tmp_path / "workspace"
    prepare_decision_repair_workspace(
        packet, workspace, artifacts, original, api_guard=True,
    )
    assert (workspace / "submissions/solve.py").read_bytes() == parent_solver


def evaluation_packet(tmp_path):
    root = tmp_path / "task"
    (root / "tests").mkdir(parents=True)
    (root / "tests/test.sh").write_text("exit 0\n")
    return SimpleNamespace(root=root)


def evaluation_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "submissions").mkdir(parents=True)
    (workspace / "submissions/solution.csv").write_text("a,b\n1,2\n")
    return workspace


def write_passing_verifier(logs):
    verifier = logs / "verifier"
    verifier.mkdir(parents=True)
    (verifier / "evaluation.json").write_text(
        '{"feasible": true, "objective": 2.0, "errors": []}',
    )
    (verifier / "reward.json").write_text('{"feasibility": 1.0, "quality": 1.0}')
    (verifier / "reward_details.json").write_text('{}')


def test_official_evaluation_uses_fresh_logs_and_readonly_decisions(tmp_path, monkeypatch):
    from ora_agent.oragentbench import official_evaluate

    packet = evaluation_packet(tmp_path)
    workspace = evaluation_workspace(tmp_path)

    def fake_docker(name, mounts, command, timeout):
        assert mounts[0][2] is True
        write_passing_verifier(mounts[2][0])
        return {"return_code": 0, "timed_out": False, "wall_seconds": 0.1}

    monkeypatch.setattr("ora_agent.oragentbench._docker", fake_docker)
    payload = official_evaluate(packet, workspace, tmp_path / "official")
    assert official_metrics(payload)["true_correct"]
    assert payload["evaluation_inputs"]["decision_sha256"]


def test_official_evaluation_never_reuses_stale_pass_logs(tmp_path, monkeypatch):
    from ora_agent.oragentbench import official_evaluate

    packet = evaluation_packet(tmp_path)
    workspace = evaluation_workspace(tmp_path)
    outdir = tmp_path / "official"
    write_passing_verifier(outdir / "logs")
    monkeypatch.setattr(
        "ora_agent.oragentbench._docker",
        lambda *args: (_ for _ in ()).throw(AssertionError("stale logs must stop before evaluation")),
    )
    payload = official_evaluate(packet, workspace, outdir)
    assert official_metrics(payload)["evaluation_unknown"]
    assert not official_metrics(payload)["true_correct"]


def test_official_evaluation_detects_decision_mutation(tmp_path, monkeypatch):
    from ora_agent.oragentbench import official_evaluate

    packet = evaluation_packet(tmp_path)
    workspace = evaluation_workspace(tmp_path)

    def fake_docker(name, mounts, command, timeout):
        write_passing_verifier(mounts[2][0])
        (workspace / "submissions/solution.csv").write_text("a,b\n9,9\n")
        return {"return_code": 0, "timed_out": False, "wall_seconds": 0.1}

    monkeypatch.setattr("ora_agent.oragentbench._docker", fake_docker)
    payload = official_evaluate(packet, workspace, tmp_path / "official")
    assert official_metrics(payload)["evaluation_unknown"]
    assert not official_metrics(payload)["true_correct"]


def test_missing_runner_is_unknown_even_with_high_reward():
    payload = official_payload()
    del payload["runner"]
    metrics = official_metrics(payload)
    assert metrics["evaluation_unknown"]
    assert not metrics["true_correct"]


def test_runtime_patch_cannot_delete_constraints_or_flip_objective_sense():
    from ora_agent.oragentbench import apply_runtime_patch

    code = (
        "from pyscipopt import Model\n"
        "m = Model()\nx = m.addVar()\nm.addCons(x <= 1)\n"
        "m.setMinimize()\nm.optimize()\n"
        "sol_path = '/app/submissions/solution.csv'\n" + "#" * 500
    )
    with pytest.raises(ValueError, match="removes model constraints"):
        apply_runtime_patch(code, [{"old_string": "m.addCons(x <= 1)\n", "new_string": ""}])
    with pytest.raises(ValueError, match="objective sense"):
        apply_runtime_patch(code, [{"old_string": "m.setMinimize()", "new_string": "m.setMaximize()"}])


def test_decision_runtime_patch_is_limited_to_the_reported_function():
    from ora_agent.decision_repair import apply_decision_runtime_patch

    code = valid_decision_code() + (
        "\ndef repair():\n    value = 1\n    return value\n"
        "\ndef unrelated_output_guard():\n    return 2\n"
    )
    reported = "def repair():\n    value = 1\n    return value"
    unrelated = "def unrelated_output_guard():\n    return 2"
    with pytest.raises(ValueError, match="reported function"):
        apply_decision_runtime_patch(
            code,
            [{"old_string": unrelated, "new_string": "def unrelated_output_guard():\n    return 0"}],
            {"function_source": reported},
        )
    patched = apply_decision_runtime_patch(
        code,
        [{"old_string": reported, "new_string": "def repair():\n    value = 2\n    return value"}],
        {"function_source": reported},
    )
    assert "value = 2" in patched
    assert unrelated in patched


def test_restored_specification_recomputes_text_hash():
    from ora_agent.cleanroom import SpecificationAsset, restore_specifications

    memory = EvidenceMemory()
    memory.register_specification(SpecificationAsset(
        "spec", "original text", {"dataset": "oragentbench", "domain": "manufacturing"},
    ))
    payload = memory.public_state(include_spec_text=True)
    payload["specifications"][0]["text"] = "modified text"
    with pytest.raises(ValueError, match="text hash mismatch"):
        restore_specifications(payload)

import json
from pathlib import Path

import pytest

from ora_agent import llm as llm_mod
from ora_agent.oragentbench import (
    TaskPacket, apply_runtime_patch, generate_artifacts, parse_artifacts, validate_solver_code,
)

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


def test_runtime_repair_keeps_solver_and_supplies_expression_contract():
    packet = TaskPacket.load(ROOT / "ORAgentBench/harbor_tasks/additive_microfactory_order_planning",
                             "manufacturing", "dev")
    repair = {"artifacts": {"solve_py": "if lhs != 0:\n    pass"},
              "evidence": {"execution": {"return_code": 1},
                           "search_guidance": {"regenerate_from_evidence": False}}}
    messages = packet.prompt("spec", repair)
    assert "PREVIOUS ARTIFACTS" in messages[1]["content"]
    assert "RUNTIME REPAIR CONTRACT" in messages[0]["content"]
    assert "if terms:" in messages[0]["content"]


def test_runtime_patch_preserves_all_unedited_source(tmp_path, monkeypatch):
    packet = TaskPacket.load(ROOT / "ORAgentBench/harbor_tasks/additive_microfactory_order_planning",
                             "manufacturing", "dev")
    code = ("from pyscipopt import Model\nm = Model()\nm.optimize()\n"
            "sol_path = '/app/submissions/solution.csv'\n" + "#" * 500)
    previous = {"model_md": "# Model", "solve_py": code, "solve_log_md": "# Log"}
    repair = {"artifacts": previous, "evidence": {"execution": {"return_code": 1},
              "search_guidance": {"regenerate_from_evidence": False, "repair_kind": "runtime_patch"}}}
    calls = []

    def fake_chat(messages, **kwargs):
        name = kwargs["extra"]["tools"][0]["function"]["name"]
        calls.append(name)
        edits = [{"old_string": "m = Model()", "new_string": "m = Model('patched')"}]
        return {"model": "test-model", "finish_reason": "stop",
                "tool_calls": [{"function": {"name": name, "arguments": json.dumps({"edits": edits})}}]}

    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    config = llm_mod.LLMConfig("http://localhost", "test-key", "test-model")
    artifacts = generate_artifacts(packet, "spec", config, tmp_path, repair=repair)
    assert calls == ["submit_runtime_patch"]
    assert artifacts["solve_py"] == code.replace("m = Model()", "m = Model('patched')")
    assert artifacts["model_md"] == previous["model_md"]
    assert (tmp_path / "runtime_patch_generation.json").exists()
    assert not (tmp_path / "model_generation.json").exists()


def test_ambiguous_runtime_patch_is_rejected_without_modifying_source():
    code = ("from pyscipopt import Model\nm = Model()\nm.optimize()\n"
            "m = Model()\nsol_path = '/app/submissions/solution.csv'\n" + "#" * 500)
    with pytest.raises(ValueError, match="exactly once"):
        apply_runtime_patch(code, [{"old_string": "m = Model()", "new_string": "m = Model('new')"}])


def test_runtime_patch_cannot_delete_a_cost_expression_to_hide_an_error():
    code = ("from pyscipopt import Model\nm = Model()\nm.optimize()\n"
            "cost_obj = undefined_cost\nsol_path = '/app/submissions/solution.csv'\n" + "#" * 500)
    with pytest.raises(ValueError, match="removes objective or cost bindings"):
        apply_runtime_patch(code, [{"old_string": "cost_obj = undefined_cost\n", "new_string": ""}])


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


def test_undefined_global_is_rejected_before_solver_execution():
    code = ("from pyscipopt import Model\nm = Model()\nm.optimize()\n"
            "cost_obj = fixed_cost\nsol_path = '/app/submissions/solution.csv'\n" + "#" * 500)
    with pytest.raises(ValueError, match="unresolved global names: fixed_cost"):
        validate_solver_code(code)


def test_star_import_does_not_cause_false_undefined_global_error():
    code = ("from pyscipopt import *\nm = Model()\nm.optimize()\n"
            "sol_path = '/app/submissions/solution.csv'\n" + "#" * 500)
    validate_solver_code(code)


def test_decision_repair_generation_preserves_solver_and_incumbent(tmp_path, monkeypatch):
    from ora_agent.decision_repair import generate_decision_repair, prepare_decision_repair_workspace

    packet = TaskPacket.load(ROOT / "ORAgentBench/harbor_tasks/additive_microfactory_order_planning",
                             "manufacturing", "dev")
    code = ("import csv, json, os\n"
            "source = '/app/submissions/solution_original.csv'\n"
            "out = '/app/submissions/solution.csv'\n"
            "with open(source) as handle:\n"
            "    rows = list(csv.reader(handle))\n"
            "with open(out, 'w') as handle:\n"
            "    csv.writer(handle).writerows(rows)\n" + "#" * 300)
    previous = {"model_md": "# Model", "solve_py": "original solver", "solve_log_md": "# Log"}
    repair = {"artifacts": previous, "decision_artifact": "a,b\n1,2\n",
              "evidence": {"execution": {"return_code": 0}, "official_errors": ["bad"],
                           "search_guidance": {"repair_kind": "decision_repair",
                                               "regenerate_from_evidence": False}}}
    calls = []

    def fake_chat(messages, **kwargs):
        name = kwargs["extra"]["tools"][0]["function"]["name"]
        calls.append(name)
        payload = {"repair_py": code, "repair_log_md": "# Repair"}
        return {"model": "test-model", "finish_reason": "stop",
                "tool_calls": [{"function": {"name": name, "arguments": json.dumps(payload)}}]}

    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    config = llm_mod.LLMConfig("http://localhost", "test-key", "test-model")
    outdir = tmp_path / "generation"
    artifacts = generate_decision_repair(packet, "spec", config, outdir, 0, repair)
    assert calls == ["submit_decision_repair"]
    assert artifacts["solve_py"] == previous["solve_py"]
    assert artifacts["repair_solution_py"] == code
    messages = json.loads((outdir / "decision_repair_generation.json").read_text())["messages"]
    assert "AGENT-GENERATED INCUMBENT" in messages[1]["content"]
    assert "PREVIOUS ARTIFACTS" not in messages[1]["content"]

    original = tmp_path / "original"
    (original / "submissions").mkdir(parents=True)
    (original / "submissions/solution.csv").write_text(repair["decision_artifact"])
    workspace = tmp_path / "workspace"
    prepare_decision_repair_workspace(packet, workspace, artifacts, original)
    assert (workspace / "submissions/solution_original.csv").read_text() == repair["decision_artifact"]
    assert (workspace / "submissions/repair_solution.py").read_text() == code


def test_decision_repair_rejects_nonstandard_library_and_dynamic_code():
    from ora_agent.decision_repair import validate_decision_repair_code

    code = ("import pandas\nsource = '/app/submissions/solution_original.csv'\n"
            "out = '/app/submissions/solution.csv'\n"
            "with open(source) as handle:\n"
            "    rows = handle.read()\n"
            "with open(out, 'w') as handle:\n"
            "    handle.write(rows)\n" + "#" * 300)
    with pytest.raises(ValueError, match="standard library"):
        validate_decision_repair_code(code)
    with pytest.raises(ValueError, match="dynamic code execution"):
        validate_decision_repair_code(code.replace("import pandas", "import json\nexec('x = 1')"))


def test_decision_repair_allows_fractions_from_standard_library():
    from ora_agent.decision_repair import validate_decision_repair_code

    code = ("from fractions import Fraction\nimport csv\n"
            "source = '/app/submissions/solution_original.csv'\n"
            "out = '/app/submissions/solution.csv'\n"
            "ratio = Fraction(1, 2)\n"
            "root = '/app'\n"
            "with open(source) as handle:\n"
            "    rows = list(csv.reader(handle))\n"
            "with open(out, 'w') as handle:\n"
            "    csv.writer(handle).writerows(rows)\n" + "#" * 300)
    validate_decision_repair_code(code)


def test_decision_runtime_patch_preserves_solver_and_original_incumbent(tmp_path, monkeypatch):
    from ora_agent.decision_repair import generate_decision_code_patch, prepare_decision_repair_workspace

    packet = TaskPacket.load(ROOT / "ORAgentBench/harbor_tasks/additive_microfactory_order_planning",
                             "manufacturing", "dev")
    code = ("import csv, json, os\n"
            "source = '/app/submissions/solution_original.csv'\n"
            "out = '/app/submissions/solution.csv'\n"
            "var_index = {}\nrow = []\nidx = ('c', 'd')\nval = 1.0\n"
            "row[idx] = val\n"
            "with open(source) as handle:\n"
            "    rows = list(csv.reader(handle))\n"
            "with open(out, 'w') as handle:\n"
            "    csv.writer(handle).writerows(rows)\n" + "#" * 300)
    previous = {"model_md": "# Model", "solve_py": "original solver", "solve_log_md": "# Log",
                "repair_solution_py": code, "repair_log_md": "# Decision"}
    repair = {"artifacts": previous, "decision_artifact": "a,b\n1,2\n",
              "evidence": {"execution": {"return_code": 1, "stderr": "TypeError"},
                           "search_guidance": {"repair_kind": "decision_runtime_patch",
                                               "regenerate_from_evidence": False}}}

    def fake_chat(messages, **kwargs):
        name = kwargs["extra"]["tools"][0]["function"]["name"]
        edits = [{"old_string": "row[idx] = val", "new_string": "row[var_index[idx]] = val"}]
        return {"model": "test-model", "finish_reason": "stop",
                "tool_calls": [{"function": {"name": name, "arguments": json.dumps({"edits": edits})}}]}

    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    config = llm_mod.LLMConfig("http://localhost", "test-key", "test-model")
    outdir = tmp_path / "generation"
    artifacts = generate_decision_code_patch(packet, "spec", config, outdir, 0, repair)
    assert artifacts["solve_py"] == previous["solve_py"]
    assert "row[var_index[idx]] = val" in artifacts["repair_solution_py"]
    messages = json.loads((outdir / "runtime_patch_generation.json").read_text())["messages"]
    assert "PREVIOUS ARTIFACTS" in messages[1]["content"]
    assert "RUNTIME REPAIR CONTRACT" not in messages[0]["content"]

    original = tmp_path / "original"
    (original / "submissions").mkdir(parents=True)
    (original / "submissions/solution_original.csv").write_text(repair["decision_artifact"])
    workspace = tmp_path / "workspace"
    prepare_decision_repair_workspace(packet, workspace, artifacts, original)
    assert (workspace / "submissions/solution_original.csv").read_text() == repair["decision_artifact"]
    assert "row[var_index[idx]] = val" in (workspace / "submissions/repair_solution.py").read_text()


def test_decision_failure_context_includes_reported_source_frame():
    from ora_agent.decision_repair import localized_failure_context

    code = "import csv\n\ndef add_row():\n    row = []\n    idx = ('c', 'd')\n    row[idx] = 1\n"
    stderr = ('Traceback (most recent call last):\n'
              '  File "/app/submissions/repair_solution.py", line 6, in add_row\n'
              '    row[idx] = 1\n'
              'TypeError: list indices must be integers or slices, not tuple')
    context = localized_failure_context(code, stderr)
    assert context["line"] == 6
    assert context["function"] == "add_row"
    assert "row[idx] = 1" in context["source_excerpt"]
    assert context["function_source"].startswith("def add_row")
    assert context["exception"].startswith("TypeError")


def test_followup_decision_repair_includes_previous_checker_code():
    packet = TaskPacket.load(ROOT / "ORAgentBench/harbor_tasks/additive_microfactory_order_planning",
                             "manufacturing", "dev")
    repair = {"artifacts": {"solve_py": "solver", "repair_solution_py": "old checker"},
              "decision_artifact": "a,b\n1,2\n",
              "evidence": {"execution": {"return_code": 0}, "official_errors": ["bad"],
                           "search_guidance": {"repair_kind": "decision_repair",
                                               "regenerate_from_evidence": True}}}
    messages = packet.prompt("spec", repair, tool_name="submit_decision_repair")
    assert "PREVIOUS DECISION REPAIR CODE" in messages[1]["content"]
    assert "old checker" in messages[1]["content"]

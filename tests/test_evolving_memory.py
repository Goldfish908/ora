import json

import pytest

from ora_agent.evolving_memory import (
    EvolvingMemoryRegistry,
    execution_signature,
    memory_view,
)
from ora_agent.memory_guards import (
    apply_memory_guard,
    repair_addvar_v_to_vtype,
    validate_guard_contract,
)
from scripts.industryor_semantic_dag import execute_candidate
from scripts.industryor_structured_pipeline import run_dag


def origin():
    return {"split": "dev", "source_ids": ["prob_001_A"], "trace_sha256": "abc"}


def spec(kind="execution", form="prompt"):
    return {"kind": kind, "form": form, "signature": "pyscipopt_addvar_v",
            "text": "When this exact addVar keyword error occurs, preserve the model and use the supported vtype keyword.",
            "guard": "addvar_v_to_vtype" if form == "guard" else None}


def metrics(gain=0.25, reduction=0.0, n=2):
    return {"n_problems": n, "execution_gain": gain, "execution_harm": 0,
            "false_business_accepts": 0, "llm_call_reduction": reduction,
            "guard_contract_passed": True, "business_labels_complete": True}


def test_execution_signature_is_specific():
    assert execution_signature({"stderr_tail": "addVar() got an unexpected keyword argument 'v'"}) == \
        "pyscipopt_addvar_v"
    assert execution_signature({"exec_status": "ok", "solver_status": "optimal", "objective": 2}) is None
    assert execution_signature({"exec_status": "ok", "solver_status": "infeasible"}) == "infeasible"


def test_prompt_lifecycle_selection_and_freeze(tmp_path):
    path = tmp_path / "registry.json"
    registry = EvolvingMemoryRegistry(path)
    asset = registry.propose(spec(), origin())
    assert asset["status"] == "candidate"
    assert registry.select({"stderr_tail": "addVar() got an unexpected keyword argument 'v'"}) == []
    registry.validate(asset["asset_id"], "dev", metrics())
    registry.validate(asset["asset_id"], "gapcheck", metrics(gain=0.1, n=1))
    assert registry.get(asset["asset_id"])["status"] == "promoted"
    selected = registry.select({"stderr_tail": "addVar() got an unexpected keyword argument 'v'"})
    assert [item["asset_id"] for item in selected] == [asset["asset_id"]]
    protocol = tmp_path / "protocol.md"
    protocol.write_text("frozen protocol")
    registry.freeze(protocol, [])
    with pytest.raises(RuntimeError, match="read-only"):
        registry.propose(spec(), origin())
    with pytest.raises(RuntimeError, match="read-only"):
        registry.retire(asset["asset_id"], "late test change", {})
    loaded = EvolvingMemoryRegistry(path)
    assert loaded.frozen is True
    assert loaded.get(asset["asset_id"])["status"] == "promoted"


def test_business_asset_cannot_use_objective_only_labels(tmp_path):
    registry = EvolvingMemoryRegistry(tmp_path / "registry.json")
    asset = registry.propose(spec(kind="business"), origin())
    evidence = metrics()
    evidence["business_labels_complete"] = False
    updated = registry.validate(asset["asset_id"], "dev", evidence)
    assert updated["status"] == "rejected"
    assert "business_labels_not_independent" in updated["validations"]["dev"]["reasons"]


def test_guard_cost_path_retirement_and_revision_lineage(tmp_path):
    registry = EvolvingMemoryRegistry(tmp_path / "registry.json")
    guard = registry.propose(spec(form="guard"), origin())
    registry.validate(guard["asset_id"], "dev", metrics(gain=0, reduction=1))
    registry.validate(guard["asset_id"], "gapcheck", metrics(gain=-0.05, reduction=1, n=1))
    assert registry.get(guard["asset_id"])["status"] == "promoted"
    registry.retire(guard["asset_id"], "later development regression", {"harm": 1})
    assert registry.select({"stderr_tail": "addVar() got an unexpected keyword argument 'v'"}) == []
    rejected = registry.propose(spec(), origin())
    registry.validate(rejected["asset_id"], "dev", metrics(gain=-1))
    revision = registry.propose(spec(), origin(), parent_id=rejected["asset_id"])
    assert revision["parent_id"] == rejected["asset_id"]


def test_registry_rejects_answer_leakage_and_non_dev_origin(tmp_path):
    registry = EvolvingMemoryRegistry(tmp_path / "registry.json")
    with pytest.raises(ValueError, match="answer reference|instance identifier"):
        registry.propose({**spec(), "text": "Use en_answer to choose the repaired objective value."}, origin())
    with pytest.raises(ValueError, match="dev traces"):
        registry.propose(spec(), {**origin(), "split": "test"})


def test_guard_contract_and_ast_preservation():
    assert validate_guard_contract("addvar_v_to_vtype")["passed"] is True
    source = "from pyscipopt import Model\nm=Model()\nx=m.addVar(v='I', lb=0)\ny=m.addVar(vtype='C')\n"
    patched = repair_addvar_v_to_vtype(source)
    assert "x=m.addVar(vtype='I', lb=0)" in patched
    assert "y=m.addVar(vtype='C')" in patched
    with pytest.raises(ValueError, match="both v and vtype"):
        apply_memory_guard("addvar_v_to_vtype", "m.addVar(v='I', vtype='I')")


def test_memory_view_separates_soft_text_and_hard_guard():
    asset = {**spec(form="guard"), "asset_id": "guard_test", "version": 1}
    view = memory_view([asset])
    assert view["guards"] == ["addvar_v_to_vtype"]
    assert "supported vtype" in view["text"]
    prompt_only = memory_view([asset], include_guards=False)
    assert prompt_only["guards"] == []


def test_dag_executes_promoted_guard_without_llm(tmp_path):
    code = ("from pyscipopt import Model\n"
            "m = Model()\n"
            "x = m.addVar(v='I', lb=0, ub=5)\n"
            "m.addCons(x >= 3)\n"
            "m.setObjective(x, 'minimize')\n"
            "m.optimize()\n")
    gate = {"status": "ready", "aliases": {}, "repair_aliases": {}}
    record, solution, score = execute_candidate(1, code, {}, tmp_path / "root")
    assert record["exec_status"] == "crash"
    selected = {"code": code, "record": record,
                "audit": {"gate": gate, "solution": solution, "score": score},
                "objective": None, "business_accepted": False}
    asset = {**spec(form="guard"), "asset_id": "guard_test", "version": 1,
             "status": "promoted", "kind": "execution"}

    def provider(current_record, current_score, current_gate):
        assets = [asset] if execution_signature(current_record) == asset["signature"] else []
        return memory_view(assets)

    result = run_dag(1, "Produce at least three integer units at minimum cost.", selected,
                     tmp_path / "dag", tmp_path / "shared", None,
                     memory_provider=provider, max_rounds=2)
    assert result["objective"] == 3
    assert result["record"]["exec_status"] == "ok"
    assert result["record"]["solver_status"] == "optimal"
    assert result["repair_records"] == []
    assert result["memory_trace"][0]["guard_used"] == "addvar_v_to_vtype"
    assert result["dag"]["total_llm_calls"] == 0
    assert any(node["action"] == "memory_guard:addvar_v_to_vtype"
               for node in result["dag"]["nodes"])


def test_name_guard_repairs_only_unambiguous_variable_names():
    from ora_agent.memory_guards import repair_addvar_v_to_name
    source = "m.addVar(v='x1', vtype='I')"
    assert repair_addvar_v_to_name(source) == "m.addVar(name='x1', vtype='I')"
    assert validate_guard_contract("addvar_v_to_name")["passed"] is True
    with pytest.raises(ValueError, match="ambiguous"):
        repair_addvar_v_to_name("m.addVar(v='I')")


def test_business_quality_uses_independent_business_gain(tmp_path):
    registry = EvolvingMemoryRegistry(tmp_path / "registry.json")
    asset = registry.propose(spec(kind="business"), origin())
    evidence = metrics(gain=-1)
    evidence.update(business_gain=0.3, business_harm=0)
    updated = registry.validate(asset["asset_id"], "dev", evidence)
    assert updated["status"] == "dev_passed"


def test_runner_error_blocks_promotion(tmp_path):
    registry = EvolvingMemoryRegistry(tmp_path / "registry.json")
    asset = registry.propose(spec(), origin())
    evidence = {**metrics(), "runner_errors": 1}
    updated = registry.validate(asset["asset_id"], "dev", evidence)
    assert updated["status"] == "rejected"
    assert "runner_errors" in updated["validations"]["dev"]["reasons"]


def test_name_guard_preserves_fstring_names():
    from ora_agent.memory_guards import repair_addvar_v_to_name
    source = "x = m.addVar(v=f'x_{i}', vtype='I')"
    assert repair_addvar_v_to_name(source) == "x = m.addVar(name=f'x_{i}', vtype='I')"

import json
from types import SimpleNamespace

from scripts.cleanroom_experiment import digest
from scripts import cleanroom_suite


def test_repair_batch_uses_same_spec_and_frozen_registry(tmp_path, monkeypatch):
    specification = "validated specification"
    record = {"task": "task", "candidate_sha256": digest(specification)}
    record_path = tmp_path / "B1/rollouts/task/record.json"
    record_path.parent.mkdir(parents=True)
    record_path.write_text(json.dumps(record))
    (tmp_path / "B1/run.json").write_text(json.dumps({
        "records": [{"task": "task", "record_path": str(record_path)}]}))
    spec_source = tmp_path / "gepa_result.json"
    spec_source.write_text(json.dumps({"candidates": [{"conventions": specification}]}))
    packet = SimpleNamespace(name="task", domain="manufacturing", split="audit",
                             scope={"dataset": "oragentbench", "domain": "manufacturing"})
    args = SimpleNamespace(out=tmp_path, dev_packets=[packet], witness_source=None,
                           seed=0, max_attempts=3, resume=False)
    monkeypatch.setattr(cleanroom_suite, "initialize_witness", lambda *args: {"authorized": True})
    monkeypatch.setattr(cleanroom_suite.llm_mod, "load_config", lambda: SimpleNamespace(model="test-model"))
    calls = []

    def fake_repair(memory, packet, record, spec, config, outdir, **kwargs):
        calls.append((record, spec, kwargs))
        return {"status": "preserved_win", "record": record, "attempts_used": 0}

    monkeypatch.setattr(cleanroom_suite, "repair_bounded", fake_repair)
    paths = cleanroom_suite.repair_batch(args, "B2", [packet], spec_source, None)
    assert len(paths) == 1 and paths[0].exists()
    assert calls[0][0]["candidate_sha256"] == digest(specification)
    assert calls[0][1] == specification
    assert calls[0][2]["max_attempts"] == 3
    state = json.loads((tmp_path / "B2/memory_frozen.json").read_text())
    assert state["frozen"]
    implementation = json.loads((tmp_path / "B2/task/implementation.json").read_text())
    assert implementation["specification_sha256"] == digest(specification)


def test_external_memory_requires_real_promotion_evidence(tmp_path):
    from ora_agent.cleanroom import EvidenceMemory, SpecificationAsset
    from scripts.cleanroom_suite import verified_promotion
    import pytest

    memory = EvidenceMemory()
    memory.register_specification(SpecificationAsset(
        "spec1", "text", {"dataset": "oragentbench", "domain": "manufacturing"}))
    memory.promote_specification("spec1", {"independent_replay": True,
                                          "changed_features_covered": True, "scope_confirmed": True})
    memory.freeze()
    path = tmp_path / "memory_promoted.json"
    path.write_text(json.dumps(memory.public_state(include_spec_text=True)))
    summary = {"independent_replay": True, "specification_status": "promoted",
               "audit": {"changed_features_covered": True, "scope_confirmed": True}}
    (tmp_path / "promotion_summary.json").write_text(json.dumps(summary))
    assert verified_promotion(path)["specification_status"] == "promoted"
    summary["independent_replay"] = False
    (tmp_path / "promotion_summary.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="independent replay"):
        verified_promotion(path)


def test_suite_uses_external_memory_for_b3_without_repromotion(tmp_path, monkeypatch):
    import hashlib
    import sys
    from ora_agent.cleanroom import EvidenceMemory, SpecificationAsset

    dev_config = tmp_path / "dev.json"
    dev_config.write_text(json.dumps({"tasks": [
        {"name": "additive_microfactory_order_planning", "domain": "manufacturing", "split": "dev"}]}))
    audit_config = tmp_path / "audit.json"
    audit_config.write_text(json.dumps({"tasks": [
        {"name": "industrial_water_reuse_blending", "domain": "manufacturing", "split": "transfer"}]}))
    gepa = tmp_path / "gepa"
    gepa.mkdir()
    (gepa / "gepa_result.json").write_text(json.dumps({
        "candidates": [{"conventions": ""}, {"conventions": "spec"}]}))
    (gepa / "analysis.json").write_text(json.dumps({
        "train_ids": [], "curves": [{"candidate_idx": 0, "official_proxy_mean": 0.0},
                                     {"candidate_idx": 1, "official_proxy_mean": 1.0}]}))
    (gepa / "implementation.json").write_text(json.dumps({
        "tasks_sha256": hashlib.sha256(dev_config.read_bytes()).hexdigest()}))
    memory = EvidenceMemory()
    memory.register_specification(SpecificationAsset(
        "spec1", "spec", {"dataset": "oragentbench", "domain": "manufacturing"}))
    memory.promote_specification("spec1", {"independent_replay": True,
                                          "changed_features_covered": True, "scope_confirmed": True})
    memory.freeze()
    memory_path = tmp_path / "memory_promoted.json"
    memory_path.write_text(json.dumps(memory.public_state(include_spec_text=True)))
    (tmp_path / "promotion_summary.json").write_text(json.dumps({
        "independent_replay": True, "specification_status": "promoted",
        "audit": {"changed_features_covered": True, "scope_confirmed": True}}))

    replays = []
    def fake_replay(args, arm, source=None, candidate=None, compare_to=None):
        replays.append((arm, source))
        path = args.out / arm / "run.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
        return path
    monkeypatch.setattr(cleanroom_suite, "replay", fake_replay)
    repairs = []
    def fake_repairs(args, arm, packets, spec_source, candidate=None):
        repairs.append((arm, spec_source))
        path = args.out / f"{arm}_repair.json"
        path.write_text("{}")
        return [path]
    monkeypatch.setattr(cleanroom_suite, "repair_batch", fake_repairs)
    commands = []
    def fake_command(args, script, *arguments):
        commands.append((script, arguments))
        if script == "scripts/cleanroom_batch_report.py":
            out = args.out / "report"
            out.mkdir()
            (out / "batch_summary.json").write_text("{}")
            (out / "report.md").write_text("report")
    monkeypatch.setattr(cleanroom_suite, "command", fake_command)
    out = tmp_path / "suite"
    monkeypatch.setattr(sys, "argv", ["cleanroom_suite.py", "--gepa-run", str(gepa),
                                     "--dev-tasks", str(dev_config), "--audit-tasks", str(audit_config),
                                     "--out", str(out), "--memory-source", str(memory_path)])
    cleanroom_suite.main()
    assert [arm for arm, _ in repairs] == ["B2", "B3"]
    assert repairs[0][1] == gepa / "gepa_result.json"
    assert repairs[1][1] == memory_path
    assert not any(script == "scripts/cleanroom_memory.py" for script, _ in commands)
    report_command = next(arguments for script, arguments in commands
                          if script == "scripts/cleanroom_batch_report.py")
    assert "--b3" in report_command
    result = json.loads((out / "suite_result.json").read_text())
    assert result["memory_promoted"]
    assert result["b3"] != "not_run"

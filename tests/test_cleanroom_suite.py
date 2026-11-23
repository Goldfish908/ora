import json
from types import SimpleNamespace

import pytest

from scripts.cleanroom_experiment import digest
from scripts import cleanroom_suite


@pytest.mark.parametrize("use_witness_override", [False, True])
def test_repair_batch_uses_same_spec_and_frozen_registry(tmp_path, monkeypatch, use_witness_override):
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
    witness_packet = SimpleNamespace(name="witness", domain="energy", split="audit",
                                     scope={"dataset": "oragentbench", "domain": "energy"})
    witness_packets = [witness_packet] if use_witness_override else None
    args = SimpleNamespace(out=tmp_path, dev_packets=[packet], witness_packets=witness_packets,
                           witness_source=None, seed=0, max_attempts=3, resume=False)
    initialization = []
    def fake_initialize(memory, packets, outdir, source):
        initialization.append((packets, source))
        return {"authorized": True}
    monkeypatch.setattr(cleanroom_suite, "initialize_witness", fake_initialize)
    monkeypatch.setattr(cleanroom_suite.llm_mod, "load_config", lambda: SimpleNamespace(model="test-model"))
    calls = []

    def fake_repair(memory, packet, record, spec, config, outdir, **kwargs):
        calls.append((record, spec, kwargs))
        return {"status": "preserved_win", "record": record, "attempts_used": 0}

    monkeypatch.setattr(cleanroom_suite, "repair_bounded", fake_repair)
    paths = cleanroom_suite.repair_batch(args, "B2", [packet], spec_source, None)
    assert initialization == [([witness_packet] if use_witness_override else [packet], None)]
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
    bind_promotion_evidence(tmp_path, path, summary)
    assert verified_promotion(path)["specification_status"] == "promoted"
    summary["independent_replay"] = False
    bind_promotion_evidence(tmp_path, path, summary)
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
        {"name": "industrial_water_reuse_blending", "domain": "manufacturing", "split": "transfer"},
        {"name": "real_world_3d_bin_packing", "domain": "packing_logistics", "split": "transfer"}]}))
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
    bind_promotion_evidence(tmp_path, memory_path, {
        "independent_replay": True, "specification_status": "promoted",
        "audit": {"changed_features_covered": True, "scope_confirmed": True}})

    replays = []
    def fake_replay(args, arm, source=None, candidate=None, compare_to=None, packets=None):
        replays.append((arm, source, packets))
        path = args.out / arm / "run.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
        return path
    monkeypatch.setattr(cleanroom_suite, "replay", fake_replay)
    repairs = []
    def fake_repairs(args, arm, packets, spec_source, candidate=None):
        repairs.append((arm, packets, spec_source))
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
    assert [arm for arm, _, _ in repairs] == ["B2", "B3"]
    assert len(repairs[0][1]) == 2
    assert [packet.name for packet in repairs[1][1]] == ["industrial_water_reuse_blending"]
    assert repairs[0][2] == gepa / "gepa_result.json"
    assert repairs[1][2] == memory_path
    assert [packet.name for packet in replays[-1][2]] == ["industrial_water_reuse_blending"]
    assert not any(script == "scripts/cleanroom_memory.py" for script, _ in commands)
    report_command = next(arguments for script, arguments in commands
                          if script == "scripts/cleanroom_batch_report.py")
    assert "--b3" in report_command
    result = json.loads((out / "suite_result.json").read_text())
    assert result["memory_promoted"]
    assert result["b3"] != "not_run"
    assert result["b3_not_run_tasks"] == ["real_world_3d_bin_packing"]


def test_suite_skip_memory_review_does_not_repromote_or_run_b3(tmp_path, monkeypatch):
    import hashlib
    import sys

    dev_config = tmp_path / "dev.json"
    dev_config.write_text(json.dumps({"tasks": [
        {"name": "additive_microfactory_order_planning", "domain": "manufacturing", "split": "dev"}]}))
    audit_config = tmp_path / "audit.json"
    audit_config.write_text(json.dumps({"tasks": [
        {"name": "ev_battery_recycling_network", "domain": "manufacturing", "split": "transfer"}]}))
    witness_config = tmp_path / "witness.json"
    witness_config.write_text(json.dumps({"tasks": [
        {"name": "smart_building_demand_response_dispatch", "domain": "energy", "split": "audit"}]}))
    gepa = tmp_path / "gepa"
    gepa.mkdir()
    (gepa / "gepa_result.json").write_text(json.dumps({
        "candidates": [{"conventions": ""}, {"conventions": "spec"}]}))
    (gepa / "analysis.json").write_text(json.dumps({
        "train_ids": [], "curves": [{"candidate_idx": 0, "official_proxy_mean": 0.0},
                                     {"candidate_idx": 1, "official_proxy_mean": 1.0}]}))
    (gepa / "implementation.json").write_text(json.dumps({
        "tasks_sha256": hashlib.sha256(dev_config.read_bytes()).hexdigest()}))
    monkeypatch.setattr(cleanroom_suite, "replay", lambda args, arm, source=None, candidate=None,
                        compare_to=None: args.out / arm / "run.json")
    repairs = []
    def fake_repairs(args, arm, packets, spec_source, candidate=None):
        repairs.append((arm, args.witness_packets))
        return [args.out / f"{arm}_repair.json"]
    monkeypatch.setattr(cleanroom_suite, "repair_batch", fake_repairs)
    commands = []
    def fake_command(args, script, *arguments):
        commands.append(script)
        if script == "scripts/cleanroom_batch_report.py":
            (args.out / "report").mkdir()
            (args.out / "report/batch_summary.json").write_text("{}")
            (args.out / "report/report.md").write_text("report")
    monkeypatch.setattr(cleanroom_suite, "command", fake_command)
    out = tmp_path / "suite"
    monkeypatch.setattr(sys, "argv", ["cleanroom_suite.py", "--gepa-run", str(gepa),
                                     "--dev-tasks", str(dev_config), "--audit-tasks", str(audit_config),
                                     "--witness-tasks", str(witness_config),
                                     "--out", str(out), "--skip-memory-review"])
    cleanroom_suite.main()
    assert repairs[0][0] == "B2"
    assert [packet.name for packet in repairs[0][1]] == ["smart_building_demand_response_dispatch"]
    assert "scripts/cleanroom_memory.py" not in commands
    result = json.loads((out / "suite_result.json").read_text())
    assert not result["memory_promoted"]
    assert result["memory_review"]["review_skipped_by_protocol"]
    assert result["b3"] == "not_run"
    implementation = json.loads((out / "suite_implementation.json").read_text())
    assert implementation["witness_tasks_sha256"] == hashlib.sha256(witness_config.read_bytes()).hexdigest()
    assert "witness_packets" not in implementation["arguments"]


def test_suite_resume_requires_matching_complete_fingerprint(tmp_path):
    previous = tmp_path / "suite_implementation.json"
    expected = {
        "source_files": {"solver.py": "hash"}, "gepa_result_sha256": "result",
        "gepa_analysis_sha256": "analysis", "seed": 0, "max_attempts": 3,
        "audit_packet_sha256": {"task": "packet"},
    }
    previous.write_text(json.dumps(expected))
    cleanroom_suite.validate_suite_resume(previous, expected)
    for key in expected:
        changed = dict(expected)
        changed[key] = "different"
        with pytest.raises(ValueError, match=key):
            cleanroom_suite.validate_suite_resume(previous, changed)
    previous.unlink()
    with pytest.raises(ValueError, match="unbound"):
        cleanroom_suite.validate_suite_resume(previous, expected)


def test_packet_fingerprint_binds_public_data_and_evaluator(tmp_path):
    root = tmp_path / "task"
    (root / "tests").mkdir(parents=True)
    (root / "tests/test.sh").write_text("first evaluator")
    packet = SimpleNamespace(
        instruction="instruction", problem_statement="problem",
        public_files={"data.csv": "a,b\n1,2\n"}, root=root,
    )
    initial = cleanroom_suite.packet_sha256(packet)
    packet.public_files["data.csv"] = "a,b\n9,9\n"
    assert cleanroom_suite.packet_sha256(packet) != initial
    packet.public_files["data.csv"] = "a,b\n1,2\n"
    assert cleanroom_suite.packet_sha256(packet) == initial
    (root / "tests/test.sh").write_text("changed evaluator")
    assert cleanroom_suite.packet_sha256(packet) != initial


def test_replay_resume_binds_generation_arguments(tmp_path):
    from ora_agent.llm import LLMConfig
    from scripts.cleanroom_experiment import record_implementation

    tasks = tmp_path / "tasks.json"
    tasks.write_text('{"tasks": []}')
    args = SimpleNamespace(tasks=str(tasks), seed=0, max_attempts=3, api_guard=True, resume=False)
    config = LLMConfig("http://localhost", "key", "model")
    record_implementation(tmp_path, args, config, resume=False)
    args.resume = True
    record_implementation(tmp_path, args, config, resume=True)
    args.seed = 1
    with pytest.raises(ValueError, match="arguments"):
        record_implementation(tmp_path, args, config, resume=True)


def bind_promotion_evidence(tmp_path, memory_path, summary):
    import hashlib

    manifests = {}
    for side in ("candidate", "baseline"):
        path = tmp_path / f"{side}_run.json"
        path.write_text(json.dumps({"evaluation": {"task_ids": ["audit_task"]}}))
        manifests[side] = (path, hashlib.sha256(path.read_bytes()).hexdigest())
    evidence = {
        "passed": True,
        "paired_comparison": {"win_safe": True, "gained_phantom": []},
        "task_ids": ["audit_task"],
    }
    for side, (path, content_hash) in manifests.items():
        evidence[f"{side}_manifest_path"] = str(path)
        evidence[f"{side}_manifest_sha256"] = content_hash
    evidence_path = tmp_path / "independent_replay_evidence.json"
    evidence_path.write_text(json.dumps(evidence))
    summary.update(
        memory_sha256=hashlib.sha256(memory_path.read_bytes()).hexdigest(),
        independent_replay_evidence_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        independent_replay_manifest_sha256=manifests["candidate"][1],
        independent_baseline_manifest_sha256=manifests["baseline"][1],
    )
    (tmp_path / "promotion_summary.json").write_text(json.dumps(summary))


@pytest.mark.parametrize("mutation", ["memory_text", "replay_manifest", "replay_tasks"])
def test_external_memory_rejects_broken_promotion_binding(tmp_path, mutation):
    import hashlib
    from ora_agent.cleanroom import EvidenceMemory, SpecificationAsset

    memory = EvidenceMemory()
    memory.register_specification(SpecificationAsset(
        "spec", "text", {"dataset": "oragentbench", "domain": "manufacturing"},
    ))
    memory.promote_specification("spec", {
        "independent_replay": True, "changed_features_covered": True, "scope_confirmed": True,
    })
    memory.freeze()
    memory_path = tmp_path / "memory_promoted.json"
    memory_path.write_text(json.dumps(memory.public_state(include_spec_text=True)))
    summary = {
        "independent_replay": True, "specification_status": "promoted",
        "audit": {"changed_features_covered": True, "scope_confirmed": True},
    }
    bind_promotion_evidence(tmp_path, memory_path, summary)
    if mutation == "memory_text":
        payload = json.loads(memory_path.read_text())
        payload["specifications"][0]["text"] = "modified"
        memory_path.write_text(json.dumps(payload))
    elif mutation == "replay_manifest":
        (tmp_path / "candidate_run.json").write_text('{"evaluation": {"task_ids": ["audit_task"]}, "changed": true}')
    else:
        evidence_path = tmp_path / "independent_replay_evidence.json"
        evidence = json.loads(evidence_path.read_text())
        evidence["task_ids"] = ["different_task"]
        evidence_path.write_text(json.dumps(evidence))
        summary["independent_replay_evidence_sha256"] = hashlib.sha256(
            evidence_path.read_bytes()).hexdigest()
        (tmp_path / "promotion_summary.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError):
        cleanroom_suite.verified_promotion(memory_path)

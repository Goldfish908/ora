import json
import sys
from types import SimpleNamespace

from scripts.cleanroom_domain_repairs import main
from scripts.cleanroom_experiment import digest


def test_domain_driver_reuses_shared_b1_and_separate_witness(tmp_path, monkeypatch):
    audit = [
        SimpleNamespace(name="smart", domain="energy", split="audit"),
        SimpleNamespace(name="microgrid", domain="energy", split="audit"),
        SimpleNamespace(name="tanker", domain="logistics", split="audit"),
    ]
    witness = [
        SimpleNamespace(name="smart", domain="energy", split="audit"),
        SimpleNamespace(name="microgrid", domain="energy", split="audit"),
        SimpleNamespace(name="hydrogen", domain="energy", split="audit"),
    ]
    monkeypatch.setattr("scripts.cleanroom_domain_repairs.load_tasks",
                        lambda path: witness if path.name == "witness.json" else audit)
    result = tmp_path / "gepa_result.json"
    result.write_text(json.dumps({"candidates": [{"conventions": ""}, {"conventions": "spec"}]}))
    audit_config = tmp_path / "audit.json"
    witness_config = tmp_path / "witness.json"
    audit_config.write_text("{}")
    witness_config.write_text("{}")
    (tmp_path / "B1").mkdir()
    (tmp_path / "B1/run.json").write_text("{}")
    calls = []

    def fake_repair(namespace, arm, packets, spec_source, candidate, baseline_arm=None):
        calls.append((namespace, arm, packets, candidate, baseline_arm))
        return []

    monkeypatch.setattr("scripts.cleanroom_domain_repairs.repair_batch", fake_repair)
    monkeypatch.setattr(sys, "argv", [
        "cleanroom_domain_repairs.py", "--suite-dir", str(tmp_path), "--arm", "B2_energy",
        "--audit-tasks", str(audit_config), "--witness-tasks", str(witness_config),
        "--gepa-result", str(result), "--candidate-idx", "1",
        "--candidate-sha256", digest("spec"),
    ])

    main()

    namespace, arm, packets, candidate, baseline_arm = calls[0]
    assert arm == "B2_energy" and baseline_arm == "B1"
    assert [packet.name for packet in packets] == ["smart", "microgrid"]
    assert namespace.witness_packets == witness
    assert candidate["candidate_sha256"] == digest("spec")
    manifest = json.loads((tmp_path / "B2_energy/domain_repair_result.json").read_text())
    assert manifest["domain"] == "energy"
    assert manifest["baseline_manifest_sha256"]

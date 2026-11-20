import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_memory_does_not_promote_without_independent_replay(tmp_path):
    (tmp_path / "result.json").write_text(json.dumps({
        "candidates": [{"conventions": ""}], "parents": [[None]]}))
    (tmp_path / "analysis.json").write_text(json.dumps({
        "val_ids": ["task"], "curves": [{
            "candidate_idx": 0, "official_proxy_mean": 0.0, "n": 1,
            "generation_errors": 0, "true_correct": 0, "phantom_proxy": 0,
        }]}))
    out = tmp_path / "out"
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    completed = subprocess.run([
        sys.executable, str(ROOT / "scripts/cleanroom_memory.py"),
        "--tasks", "configs/cleanroom_smoke_tasks.json",
        "--gepa-result", str(tmp_path / "result.json"),
        "--analysis", str(tmp_path / "analysis.json"),
        "--run-dir", str(out),
    ], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["specification_status"] == "rejected"
    assert not summary["independent_replay"]


def test_memory_promotes_only_with_replay_and_provenance(tmp_path, monkeypatch, capsys):
    (tmp_path / "result.json").write_text(json.dumps({
        "candidates": [{"conventions": ""}, {"conventions": "integer production"}],
        "parents": [[None], [0]]}))
    (tmp_path / "analysis.json").write_text(json.dumps({
        "val_ids": ["task"], "curves": [
            {"candidate_idx": 0, "official_proxy_mean": 0.0, "n": 1,
             "generation_errors": 0, "true_correct": 0, "phantom_proxy": 0},
            {"candidate_idx": 1, "official_proxy_mean": 1.0, "n": 1,
             "generation_errors": 0, "true_correct": 1, "phantom_proxy": 0},
        ]}))
    monkeypatch.setattr("scripts.cleanroom_memory.audit_specification", lambda *args, **kwargs: {
        "changed_features_covered": True, "scope_confirmed": True})
    monkeypatch.setattr("scripts.cleanroom_memory.llm_mod.load_config", lambda: None)
    monkeypatch.setattr(sys, "argv", [
        "cleanroom_memory.py", "--tasks", "configs/cleanroom_smoke_tasks.json",
        "--gepa-result", str(tmp_path / "result.json"),
        "--analysis", str(tmp_path / "analysis.json"),
        "--run-dir", str(tmp_path / "out")])
    from scripts.cleanroom_memory import main
    main()
    summary = json.loads(capsys.readouterr().out)
    assert summary["specification_status"] == "promoted"
    assert summary["independent_replay"]

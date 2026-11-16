import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.industryor_k3_report import build_report, validate

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "work/industryor_k3_smoke_v0.1"
FULL = ROOT / "work/industryor_k3_dev_v0.1"


@pytest.mark.skipif(not (SMOKE / "analysis.json").exists(), reason="k=3 smoke has not completed")
def test_smoke_k3_artifacts_separate_selection_from_oracle(tmp_path):
    validation = validate(SMOKE, require_complete=False)
    assert validation["results"] == 4
    assert validation["candidate_generations_verified"] == 12
    assert validation["selector_records_verified"] <= 4
    assert validation["source_snapshots_verified"] == 6
    report, image, data = build_report(SMOKE, tmp_path / "report.md", tmp_path, require_complete=False)
    assert "开发性新采样" in report.read_text()
    payload = json.loads(data.read_text())
    assert payload["n"] == 4
    assert payload["claims"]["sota"] is False
    assert payload["claims"]["oracle_is_deployable"] is False
    with Image.open(image) as figure:
        assert figure.format == "PNG"


@pytest.mark.skipif(not (FULL / "analysis.json").exists(), reason="full k=3 run has not completed")
def test_full_k3_artifacts_support_selected_and_pool_metrics(tmp_path):
    validation = validate(FULL)
    assert validation["results"] == 100
    assert validation["candidate_generations_verified"] == 300
    assert validation["selector_records_verified"] <= 100
    assert validation["source_snapshots_verified"] == 6
    report, image, data = build_report(FULL, tmp_path / "report.md", tmp_path)
    text = report.read_text()
    assert "历史 z2" in text
    assert "oracle 相对" in text
    payload = json.loads(data.read_text())
    assert payload["n"] == 100
    assert payload["summary"]["runner_errors"] == 0
    assert payload["claims"]["sota"] is False
    assert payload["claims"]["oracle_is_deployable"] is False
    with Image.open(image) as figure:
        assert figure.format == "PNG"

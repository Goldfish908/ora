import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.industryor_structured_report import build_report, validate

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "work/industryor_structured_smoke_v0.1"


@pytest.mark.skipif(not (SMOKE / "analysis.json").exists(), reason="structured smoke has not completed")
def test_incomplete_smoke_report_preserves_errors_and_old_artifacts(tmp_path):
    validation = validate(SMOKE, require_complete=False)
    assert validation["results"] == 8
    assert validation["source_snapshots_verified"] == 9
    report, image, data = build_report(SMOKE, tmp_path / "report.md", tmp_path,
                                       require_complete=False)
    text = report.read_text()
    assert "ERROR" in text
    assert "raw k=1=60/100" in text
    assert "raw k=3 selected=66/100" in text
    payload = json.loads(data.read_text())
    assert payload["claims"]["sota"] is False
    assert payload["claims"]["official_coopa_runner"] is False
    with Image.open(image) as figure:
        assert figure.format == "PNG"

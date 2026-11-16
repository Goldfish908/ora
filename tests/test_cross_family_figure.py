import json
from pathlib import Path

from PIL import Image

from scripts.cross_family_dag_figure import build_figure


def test_cross_family_figure_shows_same_recovery_and_extra_cost(tmp_path):
    image, path = build_figure(tmp_path)
    with Image.open(image) as figure:
        assert figure.format == "PNG" and figure.width >= 800 and figure.height >= 500
    data = json.loads(path.read_text())
    assert data["summary"]["dag_business_correct"] == 2
    assert data["summary"]["single_line_business_correct"] == 2
    assert data["summary"]["dag_solver_runs"] == 3
    assert data["summary"]["single_line_solver_runs"] == 2
    assert data["summary"]["extra_dag_solver_runs"] == 1
    assert data["summary"]["dag_gain"] == "not_demonstrated"

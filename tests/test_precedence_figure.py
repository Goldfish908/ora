import json

from PIL import Image

from scripts.precedence_figure import build_figure, load_results


def test_precedence_figure_preserves_natural_and_controls_boundary(tmp_path):
    results = load_results()
    assert results["natural"]["summary"]["repair_required"] == 0
    assert results["lifecycle"]["registry_decision"] == "not_promoted_controlled_only"
    image, path = build_figure(tmp_path)
    with Image.open(image) as figure:
        assert figure.format == "PNG" and figure.width >= 800 and figure.height >= 500
    data = json.loads(path.read_text())
    assert data["natural"]["independent_correct"] == 2
    assert data["natural"]["natural_repairs"] == 0
    assert data["natural"]["dag_evaluated"] is False
    assert data["controlled_repair"]["objective"] == 81
    assert data["controlled_repair"]["solver_runs"] == 1

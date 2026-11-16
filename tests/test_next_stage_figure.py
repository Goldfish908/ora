import json

from PIL import Image

from scripts.next_stage_figure import build_figure, load_results


def test_figure_uses_verified_results_and_writes_png(tmp_path):
    results = load_results()
    assert results["industry"]["arms"]["fixed"]["final_business_correct"] == 6
    assert results["bwor"]["arms"]["progress"]["final_reference_correct"] == 6
    figure, data_path = build_figure(tmp_path)
    with Image.open(figure) as image:
        assert image.format == "PNG"
        assert image.width >= 800 and image.height >= 500
    data = json.loads(data_path.read_text())
    assert data["tfidf_independent_top_choice"] == {"passed": 35, "attempted": 38}
    assert "frozen/sealed" not in data["scope"] or "not" in data["scope"]

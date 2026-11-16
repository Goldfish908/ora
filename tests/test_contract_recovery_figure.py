import json

from PIL import Image

from scripts.contract_recovery_figure import build_figure, load_results


def test_contract_recovery_figure_matches_positive_and_negative_controls(tmp_path):
    results = load_results()
    assert results["development"]["denominators"]["business_recovered_after_normalization"] == 3
    assert results["blind"]["denominators"]["business_recovered_after_normalization"] == 0
    image, data_path = build_figure(tmp_path)
    with Image.open(image) as figure:
        assert figure.format == "PNG"
        assert figure.width >= 800 and figure.height >= 500
    data = json.loads(data_path.read_text())
    assert data["development"]["legacy_correct"] == 2
    assert data["development"]["normalized_correct"] == 5
    assert data["blind"]["fixed_correct"] == data["blind"]["progress_correct"] == 4
    assert data["new_llm_calls"] == 0

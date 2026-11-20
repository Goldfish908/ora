from scripts.motivation_static_figure import build_figure, load_evidence


def test_motivation_figure_preserves_counts_and_exports(tmp_path):
    evidence = load_evidence()
    seed = evidence["seed"]
    assert seed["true_correct"] + seed["phantom_proxy"] + seed["truth_unknown"] == seed["n"]
    assert evidence["transitions"]["phantom_to_true"] == 16
    assert evidence["transitions"].get("true_to_phantom", 0) == 0
    assert evidence["transitions"].get("unknown_to_phantom", 0) == 0

    png, pdf = build_figure(evidence, tmp_path)
    assert png.stat().st_size > 10_000
    assert pdf.stat().st_size > 1_000

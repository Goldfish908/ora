from scripts.verification_amplification_report import mcnemar_exact, with_rates


def test_rates_use_distinct_denominators():
    row = with_rates({"n": 2, "executable": 1, "proxy_match": 1,
                      "true_correct": 0, "phantom": 1, "phantom_proxy": 1})
    assert row["executable_rate"] == 0.5
    assert row["proxy_rate"] == 0.5
    assert row["true_rate"] == 0
    assert row["phantom_share"] == 1
    assert row["phantom_proxy_share"] == 1


def test_mcnemar_exact_two_sided_values():
    assert mcnemar_exact(0, 0) == 1
    assert mcnemar_exact(1, 0) == 1
    assert mcnemar_exact(2, 0) == 0.5
    assert mcnemar_exact(3, 0) == 0.25

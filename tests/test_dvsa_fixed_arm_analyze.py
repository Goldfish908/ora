from scripts.dvsa_fixed_arm_analyze import dvsa_cells, mcnemar_exact
from scripts.dvsa_template_audit import controlled_mutations


def test_mcnemar_exact_uses_discordant_pairs_only():
    assert mcnemar_exact(5, 0) == 0.0625
    assert mcnemar_exact(1, 0) == 1
    assert mcnemar_exact(0, 0) == 1
    assert mcnemar_exact(3, 1) == 0.625


def test_dvsa_results_use_the_same_unique_solution_denominator_as_judges():
    model = {
        "schema_version": "dvsa.model.v0.1", "problem_id": "toy",
        "variables": {"x": {"domain": "real", "lb": 0}, "y": {"domain": "real", "lb": 0}},
        "data": {"limit": 4},
        "constraints": [
            {"constraint_id": "capacity", "source": "total capacity is four", "relation": "le",
             "lhs": {"add": [{"var": "x"}, {"var": "y"}]}, "rhs": {"path": "data.limit"}},
            {"constraint_id": "capacity_duplicate", "source": "total capacity is four", "relation": "le",
             "lhs": {"add": [{"var": "x"}, {"var": "y"}]}, "rhs": {"path": "data.limit"}},
        ],
        "objective": {"sense": "maximize", "expression": {"add": [{"var": "x"}, {"var": "y"}]}},
    }
    solution = {"variables": {"x": 2, "y": 2}, "objective": 4}
    cells = controlled_mutations(model, solution)
    evaluation = {"cells": [{"original_key": cell["key"], "detected": cell["wrong"],
                             "candidate_statuses": {"asset": "SATISFIED"}} for cell in cells]}
    reference = {"model": model, "solution": solution}
    rows = dvsa_cells(reference, evaluation)
    assert len(rows) == 3
    assert sum(row["wrong"] for row in rows) == 2
    assert sum(row["detected"] for row in rows) == 2
    assert not any(row["unknown"] for row in rows)

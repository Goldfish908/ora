import json

import numpy as np
import pytest

from ora_agent.repair_features import structural_features, style_features
from scripts.pairwise_repair_ranker import (
    MODEL_NAMES,
    audit_trace_directions,
    fit_model,
    grouped_oof,
    load_pairs,
    prediction_rows,
    reverse_rows,
    score_model,
    summarize_predictions,
)
from scripts.p3_build_sft import factory_prompt


def make_row(index=0, split="train"):
    return {
        "scenario_id": f"scenario_{index:03d}",
        "mutant": "drop_constraint",
        "prompt": "Sales availability and production capacity are required.",
        "chosen": (
            "from pyscipopt import Model\n"
            "m = Model()\n"
            f"x_{index} = m.addVar()\n"
            f"m.addCons(x_{index} <= {index + 1}, name='avail_{index}')\n"
            "m.optimize()\n"),
        "rejected": (
            "from pyscipopt import Model\n"
            "m = Model()\n"
            f"x_{index} = m.addVar()\n"
            "m.optimize()\n"),
        "source": "factory_pass",
        "split": split,
    }


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_load_pairs_removes_exact_duplicates_and_preserves_scenario_sides(tmp_path):
    first = make_row(0)
    second = make_row(1, "dev")
    path = tmp_path / "pairs.jsonl"
    write_rows(path, [first, first, second])
    raw, rows, audit = load_pairs(path)
    assert len(raw) == 3
    assert len(rows) == 2
    assert audit["exact_duplicates_removed"] == 1
    assert audit["scenarios_by_split"] == {"train": 1, "dev": 1}


def test_load_pairs_rejects_reversed_direction_and_mixed_scenario(tmp_path):
    first = make_row(0)
    reversed_pair = dict(first, chosen=first["rejected"], rejected=first["chosen"])
    path = tmp_path / "reversed.jsonl"
    write_rows(path, [first, reversed_pair])
    with pytest.raises(ValueError, match="reversed pair direction"):
        load_pairs(path)

    mixed = dict(make_row(1), scenario_id=first["scenario_id"], split="dev")
    write_rows(path, [first, mixed])
    with pytest.raises(ValueError, match="multiple split sides"):
        load_pairs(path)


def test_load_pairs_rejects_empty_or_identical_candidates(tmp_path):
    row = make_row(0)
    row["rejected"] = row["chosen"]
    path = tmp_path / "identical.jsonl"
    write_rows(path, [row])
    with pytest.raises(ValueError, match="identical"):
        load_pairs(path)


def test_trace_audit_verifies_factory_and_rescue_directions(tmp_path):
    factory = tmp_path / "factory"
    rescue = tmp_path / "rescue"
    factory.mkdir()
    rescue.mkdir()
    success = {
        "scenario_id": "success", "mutant_type": "drop_constraint",
        "problem_text": "problem", "broken_code": "broken", "violation_text": "bad",
        "repaired_code": "good", "mutant_valid": True,
        "gold_objective": 10.0, "objective_after": 10.0,
        "witness_verdict": {"verdict": "pass"},
        "exec_before": {"witness": "infeasible"},
    }
    failed = dict(success, scenario_id="rescued", repaired_code="bad repair",
                  witness_verdict={"verdict": "fail"}, objective_after=9.0)
    (factory / "samples_success.json").write_text(json.dumps(success))
    (factory / "samples_failed.json").write_text(json.dumps(failed))
    rescued = {
        "scenario_id": "rescued", "mutant_type": "drop_constraint",
        "rescued": True, "rescued_code": "rescued good", "gold_objective": 10.0,
        "history": [{"witness": "feasible", "grade": "match", "objective": 10.0}],
    }
    (rescue / "rescue_rescued.json").write_text(json.dumps(rescued))
    rows = [
        dict(make_row(0), scenario_id="success", prompt=factory_prompt(success),
             chosen="good", rejected="broken", source_line=1, pair_id="factory"),
        dict(make_row(1), scenario_id="rescued", prompt=factory_prompt(failed),
             chosen="rescued good", rejected="bad repair", source="rescue_pass",
             source_line=2, pair_id="rescue"),
    ]
    result = audit_trace_directions(rows, factory, rescue)
    assert result["matched_raw_pairs"] == {"factory_pass": 1, "rescue_pass": 1}
    reversed_result = audit_trace_directions(
        [dict(rows[0], chosen="broken", rejected="good")], factory, rescue)
    assert reversed_result["direction_excluded_raw_pairs"] == 1
    assert reversed_result["excluded_pairs"][0]["reason"] == "no_exact_verified_direction_match"

    failed["witness_verdict"] = {"verdict": "pass", "grade": "match"}
    (factory / "samples_failed.json").write_text(json.dumps(failed))
    ambiguous = audit_trace_directions([rows[1]], factory, rescue)
    assert ambiguous["matched_raw_pairs"] == {}
    assert ambiguous["excluded_pairs"][0]["reason"] == "rejected_was_verified_pass"


def test_features_separate_style_ast_and_allowlisted_execution():
    prompt = "Sales availability: sales[p,l,t,r] <= I[p,l,t,r] is required."
    code = "m.addCons(sales <= I, name='avail')\n# explanatory comment\n"
    style = style_features(prompt, code)
    structure = structural_features(prompt, code, {"exec_status": "ok"})
    assert style["comment_line_count"] == 1
    assert "call_addCons" not in style
    assert structure["call_addCons"] == 1
    assert structure["prompt_code_availability"] == 1
    assert structure["execution_ok"] == 1
    baseline = structural_features(prompt, code, {"exec_status": "ok"})
    forbidden = structural_features(prompt, code, {
        "exec_status": "ok", "source": "rescue_pass", "scenario_id": "secret",
        "chosen": "label", "reference_objective": 123,
    })
    assert baseline == forbidden
    invalid = structural_features(prompt, "not valid python ===")
    assert invalid["ast_valid"] == 0
    assert invalid["syntax_error"] == 1


def training_rows(count=12):
    return [make_row(index) for index in range(count)]


@pytest.mark.parametrize("model_name", MODEL_NAMES)
def test_pairwise_scores_are_antisymmetric_and_ignore_metadata(model_name):
    rows = training_rows()
    model = fit_model(model_name, rows, seed=42)
    margins = score_model(model, rows)
    reversed_margins = score_model(model, reverse_rows(rows))
    np.testing.assert_allclose(margins, -reversed_margins, atol=1e-10, rtol=0)

    changed_metadata = []
    for index, row in enumerate(rows):
        changed = dict(row)
        changed.update(scenario_id=f"hidden_{index}", source="rescue_pass",
                       mutant="hidden", split="dev", pair_id="label",
                       public_answer="answer", chosen_label=1)
        changed_metadata.append(changed)
    changed_model = fit_model(model_name, changed_metadata, seed=42)
    np.testing.assert_allclose(margins, score_model(changed_model, rows), atol=1e-10, rtol=0)


def test_grouped_validation_keeps_every_scenario_on_one_fold():
    rows = training_rows(20)
    margins, fold_ids, folds = grouped_oof("length_only", rows, seed=42, folds=5)
    assert len(folds) == 5
    assert np.all(margins != 0)
    for scenario in {row["scenario_id"] for row in rows}:
        indices = [index for index, row in enumerate(rows) if row["scenario_id"] == scenario]
        assert len(set(fold_ids[indices])) == 1
    for index, row in enumerate(rows):
        row.update(pair_id=str(index), source_line=index + 1)
    exported = prediction_rows(rows, {"length_only": margins}, {"length_only": fold_ids})
    assert len(exported) == len(rows)
    assert exported[0]["models"]["length_only"]["fold"] == int(fold_ids[0])


def test_metrics_cover_abstentions_and_scenario_bootstrap_is_deterministic():
    rows = [make_row(0), make_row(0), make_row(1), make_row(2)]
    margins = np.asarray([1.0, -1.0, 0.0, 2.0])
    first = summarize_predictions(rows, margins, seed=42, bootstrap=100)
    second = summarize_predictions(rows, margins, seed=42, bootstrap=100)
    assert first["coverage"] == 0.75
    assert first["pairwise_accuracy"] == pytest.approx(2 / 3)
    assert first["unconditional_accuracy_abstain_wrong"] == 0.5
    assert first["macro_scenario_accuracy"] == 0.75
    assert first["macro_scenario_bootstrap_ci95"] == second["macro_scenario_bootstrap_ci95"]
    by_scenario = {row["scenario_id"]: row for row in first["by_scenario"]}
    assert by_scenario["scenario_001"]["pairwise_accuracy"] is None

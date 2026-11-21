import json
from types import SimpleNamespace

import pytest

from scripts.cleanroom_experiment import digest
from scripts.cleanroom_replay import check_disjoint_from_gepa, selected_specifications


def args(source, candidate_idx=0, candidate_sha256=None):
    return SimpleNamespace(gepa_result=str(source), memory=None, candidate_idx=candidate_idx,
                           candidate_sha256=candidate_sha256, spec_id=None)


def packets(*names):
    return [SimpleNamespace(name=name) for name in names]


def test_explicit_candidate_and_hash_are_used_for_replay(tmp_path):
    result = tmp_path / "gepa_result.json"
    result.write_text(json.dumps({"candidates": [{"conventions": "empty"}, {"conventions": "spec"}]}))
    selected = selected_specifications(args(result, 1, digest("spec")), packets("a", "b"))
    assert selected == {"a": "spec", "b": "spec"}
    with pytest.raises(ValueError, match="hash"):
        selected_specifications(args(result, 1, "wrong"), packets("a"))


def test_selection_tasks_cannot_be_relabelled_as_disjoint(tmp_path):
    result = tmp_path / "gepa_result.json"
    result.write_text("{}")
    (tmp_path / "analysis.json").write_text(json.dumps({"train_ids": ["dev"], "val_ids": ["transfer"]}))
    with pytest.raises(ValueError, match="overlaps"):
        check_disjoint_from_gepa(result, packets("dev"), False)
    assert check_disjoint_from_gepa(result, packets("new"), False) == "subsequent_disjoint_replay"
    assert check_disjoint_from_gepa(result, packets("dev"), True) == "selection_set_replay"

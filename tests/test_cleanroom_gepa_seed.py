import json
from types import SimpleNamespace

from scripts.cleanroom_experiment import gepa_seed_candidate


def test_gepa_seed_defaults_to_empty_or_loads_explicit_candidate(tmp_path):
    assert gepa_seed_candidate(SimpleNamespace(gepa_seed_result=None)) == {"conventions": ""}
    path = tmp_path / "gepa_result.json"
    path.write_text(json.dumps({"candidates": [{"conventions": "seed"}, {"conventions": "C2"}]}))
    args = SimpleNamespace(gepa_seed_result=path, gepa_seed_idx=1)
    assert gepa_seed_candidate(args) == {"conventions": "C2"}

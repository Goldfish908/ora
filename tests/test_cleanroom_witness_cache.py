import json

import pytest

from scripts.cleanroom_witness_cache import materialize_oracle_cache


def test_materialize_oracle_cache_preserves_batch_artifacts(tmp_path):
    source = tmp_path / "source"
    app = source / "task/oracle/app"
    app.mkdir(parents=True)
    (app / "solution.csv").write_text("value\n1\n")
    result = {"metrics": {"true_correct": True}, "official": {"evaluation": {"feasible": True}}}
    (source / "oracle_results.json").write_text(json.dumps({"task": result}))
    out = tmp_path / "cache"

    manifest = materialize_oracle_cache(source, out, ["task"])

    assert json.loads((out / "task/oracle/result.json").read_text()) == result
    assert (out / "task/oracle/app/solution.csv").read_text() == "value\n1\n"
    assert manifest["task_names"] == ["task"]
    assert (app / "solution.csv").exists()
    with pytest.raises(ValueError, match="must be new"):
        materialize_oracle_cache(source, out, ["task"])

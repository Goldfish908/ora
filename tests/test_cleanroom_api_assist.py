from types import SimpleNamespace

from scripts.cleanroom_experiment import CleanroomAdapter


def batch():
    return SimpleNamespace(trajectories=[{
        "task": "task", "problem": {"public": True}, "artifacts": {"solve_py": "code"},
        "feedback": "proxy false",
    }])


def test_api_contract_is_optional_and_only_in_reflection(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.cleanroom_experiment.probe_pyscipopt_api",
                        lambda outdir: {"stdout": "getObjVal (self)"})
    adapter = CleanroomAdapter(tmp_path, 1, 0, None, api_assist=True)
    rows = adapter.make_reflective_dataset(None, batch(), ["conventions"])["conventions"]
    assert rows[0]["Inputs"]["environment_api_contract"] == "getObjVal (self)"

    monkeypatch.setattr("scripts.cleanroom_experiment.probe_pyscipopt_api",
                        lambda outdir: (_ for _ in ()).throw(AssertionError("must not probe")))
    adapter = CleanroomAdapter(tmp_path, 1, 0, None, api_assist=False)
    rows = adapter.make_reflective_dataset(None, batch(), ["conventions"])["conventions"]
    assert "environment_api_contract" not in rows[0]["Inputs"]

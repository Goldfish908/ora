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


def test_reflection_feedback_has_public_error_but_not_official_business_details(tmp_path, monkeypatch):
    packet = SimpleNamespace(name="task", domain="manufacturing", split="dev", root=tmp_path / "task",
                             instruction="instruction", problem_statement="problem", public_files={})
    monkeypatch.setattr("scripts.cleanroom_experiment.generate_artifacts",
                        lambda *args, **kwargs: {"model_md": "model", "solve_py": "code", "solve_log_md": "log"})

    def prepare(packet, workspace, artifacts, api_guard=False):
        workspace.mkdir(parents=True)

    monkeypatch.setattr("scripts.cleanroom_experiment.prepare_workspace", prepare)
    monkeypatch.setattr("scripts.cleanroom_experiment.execute_solver", lambda *args: {
        "return_code": 1, "timed_out": False, "stderr": "AttributeError: Model has no quicksum"})
    monkeypatch.setattr("scripts.cleanroom_experiment.official_evaluate", lambda *args: {
        "evaluation": {"feasible": False, "errors": ["OFFICIAL_BUSINESS_DETAIL"]},
        "reward": {"feasibility": 0.0, "quality": 0.0}, "reward_details": {},
        "runner": {"return_code": 0, "timed_out": False}})
    adapter = CleanroomAdapter(tmp_path, 1, 0, None)
    record = adapter._rollout(packet, {"conventions": ""})
    assert "AttributeError: Model has no quicksum" in record["feedback"]
    assert "OFFICIAL_BUSINESS_DETAIL" not in record["feedback"]
    rows = adapter.make_reflective_dataset(None, SimpleNamespace(trajectories=[record]), ["conventions"])
    assert "OFFICIAL_BUSINESS_DETAIL" not in rows["conventions"][0]["Feedback"]


def test_dev_official_feedback_is_explicit_and_never_leaks_to_transfer(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.cleanroom_experiment.generate_artifacts",
                        lambda *args, **kwargs: {"model_md": "model", "solve_py": "code", "solve_log_md": "log"})

    def prepare(packet, workspace, artifacts, api_guard=False):
        workspace.mkdir(parents=True)

    monkeypatch.setattr("scripts.cleanroom_experiment.prepare_workspace", prepare)
    monkeypatch.setattr("scripts.cleanroom_experiment.execute_solver", lambda *args: {
        "return_code": 0, "timed_out": False})
    monkeypatch.setattr("scripts.cleanroom_experiment.official_evaluate", lambda *args: {
        "evaluation": {"feasible": False, "errors": ["DEV_VIOLATION_COORDINATE"]},
        "reward": {"feasibility": 0.0, "quality": 0.0}, "reward_details": {}})

    for split in ("dev", "transfer"):
        packet = SimpleNamespace(name="task", domain="manufacturing", split=split,
                                 root=tmp_path / split / "task", instruction="instruction",
                                 problem_statement="problem", public_files={})
        adapter = CleanroomAdapter(tmp_path / split, 1, 0, None, dev_official_feedback=True)
        record = adapter._rollout(packet, {"conventions": ""})
        if split == "dev":
            assert "DEV_VIOLATION_COORDINATE" in record["feedback"]
            assert "Development-only" in record["feedback"]
        else:
            assert "DEV_VIOLATION_COORDINATE" not in record["feedback"]
            assert "Development-only" not in record["feedback"]

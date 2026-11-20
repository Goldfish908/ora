import json
from pathlib import Path

import yaml

from scripts.alphaopt_retailopt import (
    PROGRAM_PROMPT,
    SCIP_FOOTER,
    configure_official,
    convert_tasks,
    summarize_execution_records,
)

ROOT = Path(__file__).resolve().parents[1]


def test_task_conversion_preserves_proxy_answer_but_not_solver_contract(tmp_path):
    row = json.loads((ROOT / "data/m1_retailopt/example01.jsonl").read_text().splitlines()[0])
    convert_tasks([row], tmp_path / "tasks.json")
    task = json.loads((tmp_path / "tasks.json").read_text())[0]
    assert task["ground_truth"] == row["reference_objective"]
    assert task["task_id"] == row["scenario_id"]
    assert "[OUTPUT FORMAT]" not in task["description"]
    assert "gurobipy" not in PROGRAM_PROMPT
    assert "Q, sales, I, W, lost, sub, X" in PROGRAM_PROMPT
    assert "model.getNSols" in SCIP_FOOTER


def test_official_config_has_no_credentials_and_absolute_artifacts(tmp_path):
    train_path = tmp_path / "tasks.json"
    configure_official(tmp_path, train_path, 2, 1)
    text = (tmp_path / "train_config.yaml").read_text()
    config = yaml.safe_load(text)
    assert config["params"]["num_iterations"] == 2
    assert config["file_paths"]["train_output_dir"] == str(tmp_path / "learning")
    assert config["api_keys"]["OPENAI_API_KEY"] is None
    assert "ORA_LLM_API_KEY" not in text


def test_alphaopt_curve_recomputes_proxy_truth_and_phantom(tmp_path):
    directory = tmp_path / "learning/task/executions/iter_0/0001"
    directory.mkdir(parents=True)
    base = {"task_id": "task", "iteration": 0, "executable": True,
            "proxy_match": True, "true_correct": False,
            "phantom": True, "phantom_proxy": True}
    (directory / "alphaopt_execution.json").write_text(json.dumps(base))
    analysis = summarize_execution_records(tmp_path)
    assert analysis["n_rollouts"] == 1
    assert analysis["curves"][0]["proxy_match"] == 1
    assert analysis["curves"][0]["true_correct"] == 0
    assert analysis["curves"][0]["phantom"] == 1
    assert analysis["witness_used_for_optimality"] is False


def test_governance_blocks_proxy_success_before_official_optimality(tmp_path):
    from types import SimpleNamespace
    from scripts import alphaopt_retailopt as adapter
    from scripts.m1_reference import build_and_solve
    from scripts.retailopt_governance import build_governor

    cases_path = ROOT / "work/retailopt_governance_smoke_v0.2/cases.json"
    if not cases_path.exists():
        import pytest
        pytest.skip("trusted RetailOpt cases have not been generated")
    manifest = json.loads(cases_path.read_text())
    row = json.loads((ROOT / "data/m1_retailopt/example01.jsonl").read_text().splitlines()[0])
    metadata, solution = build_and_solve(json.loads(row["data"]), time_limit=30, handled_mode="received")
    data = json.loads(row["data"])
    product, location = data["products"][0], data["locations"][0]
    solution.setdefault("I", {})[f"{product}|{location}|1|{data['shelf_life'][product] - 1}"] = 1.0
    code = ("import json\n"
            "from pyscipopt import Model\n"
            "model = Model()\n"
            "Q, sales, I, W, lost, sub, X = {}, {}, {}, {}, {}, {}, {}\n"
            "model.optimize()\n"
            f"solution = {solution!r}\n"
            "json.dump(solution, open('solution.json', 'w'))\n"
            "print('status: optimal')\n"
            f"print('objective: {metadata['objective']!r}')\n")
    adapter.GOVERNOR = build_governor(manifest, include_demand=False)
    adapter.AUDIT_MANIFEST = manifest
    adapter.RULE_MODE = "r1"
    adapter.ATTEMPT_HISTORY.clear()
    adapter.CONTEXT.task = SimpleNamespace(id=row["scenario_id"])
    adapter.CONTEXT.row = row
    adapter.CONTEXT.iteration = 0
    adapter.CONTEXT.output_path = tmp_path
    try:
        result = adapter.current_execution(code)
        assert isinstance(result, str)
        assert "Governance rejected" in result
        assert "L2_initial_inventory:fail" in result
    finally:
        adapter.GOVERNOR = None
        adapter.AUDIT_MANIFEST = None
        adapter.RULE_MODE = "none"
        adapter.ATTEMPT_HISTORY.clear()


def test_program_contract_rejects_drafts_and_gurobi():
    from scripts.alphaopt_retailopt import validate_program
    valid = ("from pyscipopt import Model\n"
             "model = Model()\n"
             "Q, sales, I, W, lost, sub, X = {}, {}, {}, {}, {}, {}, {}\n"
             "model.optimize()\n")
    assert validate_program(valid) == []
    assert "placeholder_expression:sub_in_to_pt" in validate_program(valid + "sub_in_to_pt\n")
    assert "missing_tables:I,Q,W,X,lost,sales,sub" in validate_program("model.optimize()\n")
    assert "gurobi_residual" in validate_program(valid + "import gurobipy\n")
    assert "draft_placeholder" in validate_program(valid + "# placeholder\n")


def test_alphaopt_proxy_uses_official_absolute_tolerance(tmp_path):
    from types import SimpleNamespace
    from scripts import alphaopt_retailopt as adapter
    row = json.loads((ROOT / "data/m1_retailopt/example01.jsonl").read_text().splitlines()[0])
    objective = row["reference_objective"] + 0.2
    code = ("import json\n"
            "from pyscipopt import Model\n"
            "model = Model()\n"
            "Q, sales, I, W, lost, sub, X = {}, {}, {}, {}, {}, {}, {}\n"
            "model.optimize()\n"
            f"solution = {{'objective': {objective!r}, 'Q': {{}}, 'sales': {{}}, 'I': {{}}, 'W': {{}}, 'lost': {{}}, 'sub': {{}}, 'X': {{}}}}\n"
            "json.dump(solution, open('solution.json', 'w'))\n"
            "print('status: optimal')\n"
            f"print('objective: {objective!r}')\n")
    adapter.GOVERNOR = None
    adapter.RULE_MODE = "none"
    adapter.CONTEXT.task = SimpleNamespace(id=row["scenario_id"])
    adapter.CONTEXT.row = row
    adapter.CONTEXT.iteration = 0
    adapter.CONTEXT.output_path = tmp_path
    adapter.current_execution(code)
    assert adapter.CONTEXT.last_record["proxy_match"] is False

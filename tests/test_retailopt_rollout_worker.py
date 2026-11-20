import json
import subprocess
from pathlib import Path

from scripts.m1_reference import build_and_solve

ROOT = Path(__file__).resolve().parents[1]
RL_PYTHON = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"


def test_worker_recomputes_witness_independently(tmp_path):
    rows = [json.loads(line) for line in (ROOT / "data/m1_retailopt/example01.jsonl").read_text().splitlines()
            if line.strip()]
    row = next(row for row in rows if row.get("reference_objective") is not None)
    metadata, solution = build_and_solve(json.loads(row["data"]), time_limit=30, handled_mode="received")
    assert solution is not None
    code = ("import json\n"
            f"solution = {solution!r}\n"
            "json.dump(solution, open('solution.json', 'w'))\n"
            "print('status: optimal')\n"
            f"print('objective: {metadata['objective']!r}')\n")
    row["reference_objective"] = metadata["objective"]
    row_path = tmp_path / "row.json"
    row_path.write_text(json.dumps(row))
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "gen.py").write_text(code)
    completed = subprocess.run([RL_PYTHON, str(ROOT / "scripts/retailopt_rollout_worker.py"),
                                "--row", str(row_path), "--sandbox", str(sandbox)],
                               cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    record = json.loads((sandbox / "rollout.json").read_text())
    assert record["executable"] is True
    assert record["proxy_match"] is True
    assert record["true_correct"] is True
    assert record["phantom"] is False
    assert record["check_verdicts"] == {"L1_execution": "pass", "L2_retail_witness": "pass",
                                        "L2_initial_inventory": "pass", "L2_demand_balance": "pass"}

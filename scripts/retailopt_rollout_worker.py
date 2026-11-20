#!/usr/bin/env python3
"""Execute one RetailOpt candidate with the existing SCIP/witness Python."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.m1_pilot import grade, run_code, run_witness
from scripts.retailopt_governance import demand_balance_eval, initial_inventory_eval


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--row", required=True)
    parser.add_argument("--sandbox", required=True)
    args = parser.parse_args()
    row_path = Path(args.row)
    sandbox = Path(args.sandbox)
    sandbox.mkdir(parents=True, exist_ok=True)
    row = json.loads(row_path.read_text())
    (sandbox / "data.json").write_text(row["data"])
    code = (sandbox / "gen.py").read_text()
    record = run_code(code, sandbox)
    record.update(run_witness(row, sandbox))
    record["grade"] = grade(record.get("objective"), row.get("reference_objective"),
                            record.get("solver_status"))
    executable = record.get("exec_status") == "ok" and record.get("objective") is not None
    proxy_match = record["grade"] in {"match", "better_than_reference"}
    witness_fail = record.get("witness") == "infeasible"
    record.update(executable=executable, proxy_match=proxy_match,
                  true_correct=record.get("witness") == "feasible" and proxy_match,
                  phantom=executable and witness_fail,
                  phantom_proxy=proxy_match and witness_fail)
    execution_status = "pass" if executable else "fail"
    if record.get("witness") == "feasible":
        witness_status = "pass"
    elif witness_fail:
        witness_status = "fail"
    else:
        witness_status = "unknown"
    check_verdicts = {"L1_execution": execution_status, "L2_retail_witness": witness_status}
    solution_path = sandbox / "solution.json"
    if solution_path.exists():
        try:
            artifact = {"data": json.loads(row["data"]), "solution": json.loads(solution_path.read_text())}
            check_verdicts["L2_initial_inventory"] = initial_inventory_eval(artifact).status
            check_verdicts["L2_demand_balance"] = demand_balance_eval(artifact).status
        except (ValueError, TypeError, json.JSONDecodeError):
            check_verdicts["L2_initial_inventory"] = "unknown"
            check_verdicts["L2_demand_balance"] = "unknown"
    else:
        check_verdicts["L2_initial_inventory"] = "unknown"
        check_verdicts["L2_demand_balance"] = "unknown"
    record["check_verdicts"] = check_verdicts
    record.pop("stdout_artifact", None)
    record.pop("stderr_artifact", None)
    (sandbox / "rollout.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"scenario_id": row["scenario_id"], "exec_status": record.get("exec_status"),
                      "grade": record["grade"], "witness": record.get("witness")}))


if __name__ == "__main__":
    main()

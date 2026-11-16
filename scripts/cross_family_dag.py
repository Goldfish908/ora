#!/usr/bin/env python3
"""Compare a complete evidence DAG with single-line repair on two natural error families."""
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.acceptance import can_accept
from ora_agent.binding_protocol import registry
from ora_agent.dvsa_model import solve_model
from ora_agent.evidence_dag import DagBudget, EvidenceDAGExecutor, Proposal, candidate_digest
from ora_agent.scoped_assets import compile_asset, load_asset
from ora_agent.scoped_ir import evaluate_spec
from scripts.bwor_scoped_loop import (
    independent_score,
    load_screened_case,
    prepare_case,
    repair_objective_expression,
)
from scripts.cold_start_binding import objective_case
from scripts.industryor_next_stage import MANIFEST, load_problem
from scripts.industryor_scoped_loop import (
    INDICATOR_TEMPLATE,
    TEMPLATE,
    binding_for,
    execute,
    indicator_binding_for,
    repair_model,
    repair_objective,
    validation_cells,
)
from scripts.scoped_ir_e2e import current_cell
from scripts.scoped_ir_gate import gate

PROTOCOL = ROOT / "docs/paper/cross_family_dag_protocol_v0.1.md"


def bwor_case(outdir: Path) -> dict:
    case_data = objective_case(registry())
    case = case_data["case"]
    initial = case["initial"]
    spec = case["spec"]

    def binding_audit(solution):
        if not isinstance(solution, dict):
            return {"status": "unknown", "fired": False, "unknown_evidence": [], "rejected": []}
        return evaluate_spec(spec, case["question"], [current_cell(solution)], "BWOR-058")["records"][0]

    executor = EvidenceDAGExecutor(DagBudget(max_nodes=6, max_solver_runs=3))
    root = executor.root(copy.deepcopy(initial["model"]), "dvsa_model", initial["solve"],
                         case["initial_score"], "rejected", case_data["wrong_binding"]["binding_sha256"])
    cold = Proposal(
        "candidate_derived_binding", copy.deepcopy(initial["model"]), "dvsa_model",
        lambda: copy.deepcopy(initial["solve"]), lambda _: case["initial_score"],
        binding_sha256=case_data["wrong_binding"]["binding_sha256"],
        binding_status=case_data["wrong_binding"]["status"], solver_runs=0)
    executor.expand(root.node_id, [cold])
    executor.rollback("root/candidate_derived_binding:0", root.node_id)
    repaired = repair_objective_expression(initial["model"], case["reference"]["model"]["objective"]["expression"])
    valid = Proposal(
        "reference_objective_patch", repaired, "dvsa_model", lambda: solve_model(repaired, time_limit=60.0),
        lambda solution: independent_score(case, solution),
        binding_sha256=case_data["valid"]["binding_sha256"], binding_audit=binding_audit)
    executor.expand(root.node_id, [valid])
    record = executor.dag.to_dict()
    single_execution = solve_model(repaired, time_limit=60.0)
    single_score = independent_score(case, single_execution.get("solution"))
    record["single_line"] = {"candidate_hash": candidate_digest(repaired, "dvsa_model"),
        "execution": single_execution, "business_audit": single_score,
        "solver_runs": 1, "llm_calls": 0}
    record["source_inputs"] = case["provenance"]
    record["comparison"] = {
        "same_business_correct": len(executor.dag.accepted()) == 1 and single_score["business_correct"],
        "single_line_solver_runs": 1,
        "extra_dag_solver_runs": record["total_solver_runs"] - 1,
        "dag_gain": "not_demonstrated",
    }
    return record


def industry_case(outdir: Path) -> dict:
    problem_id = 19
    problem = load_problem(problem_id)
    manifest = json.loads(MANIFEST.read_text())
    row = next(row for row in manifest["problems"] if row["id"] == problem_id)
    question = row["question"]
    objective_binding = binding_for(problem_id, question)
    indicator_binding = indicator_binding_for(problem_id, question)
    spec = compile_asset(load_asset(TEMPLATE), objective_binding)
    spec["invariants"].extend(compile_asset(load_asset(INDICATOR_TEMPLATE), indicator_binding)["invariants"])
    cells = validation_cells(problem_id, problem.solution)
    gate_result = gate(spec, question, cells, str(problem_id))
    if not gate_result["accepted"]:
        raise ValueError("independent IndustryOR binding failed its gate")

    def binding_audit(solution):
        if not isinstance(solution, dict):
            return {"status": "unknown", "fired": False, "unknown_evidence": [], "rejected": []}
        return evaluate_spec(spec, question, [current_cell(solution)], str(problem_id))["records"][0]

    executor = EvidenceDAGExecutor(DagBudget(max_nodes=6, max_solver_runs=4))
    execution_record = json.loads((ROOT / row["artifacts"]["execution.json"]).read_text())
    root = executor.root(problem.code, "pyscipopt_code", execution_record,
                         problem.scorer(problem.solution), "rejected",
                         hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest())
    objective_only_code = repair_objective(problem.code, objective_binding)
    objective_only = Proposal(
        "objective_only", objective_only_code, "pyscipopt_code",
        lambda: execute(objective_only_code, outdir / "industryor" / "objective_only"),
        problem.scorer, binding_sha256=root.binding_sha256, binding_audit=binding_audit)
    failed = executor.expand(root.node_id, [objective_only])[0]
    if failed.business_audit["business_correct"]:
        raise ValueError("objective-only control unexpectedly passed the full business audit")
    executor.rollback(failed.node_id, root.node_id)
    restored = executor.dag.nodes[root.node_id].snapshot
    composite_code = repair_model(restored, objective_binding, indicator_binding)
    composite = Proposal(
        "objective_and_indicator", composite_code, "pyscipopt_code",
        lambda: execute(composite_code, outdir / "industryor" / "composite"),
        problem.scorer, binding_sha256=root.binding_sha256, binding_audit=binding_audit)
    executor.expand(root.node_id, [composite])
    record = executor.dag.to_dict()
    single_execution, single_solution = execute(composite_code, outdir / "industryor" / "single_line")
    single_score = problem.scorer(single_solution)
    record["single_line"] = {"candidate_hash": hashlib.sha256(composite_code.encode()).hexdigest(),
                             "execution": single_execution, "business_audit": single_score,
                             "solver_runs": 1, "llm_calls": 0}
    record["source_inputs"] = {"manifest": row["sources"], "initial": row["initial"],
                               "question_sha256": row["question_sha256"]}
    record["comparison"] = {
        "same_business_correct": len(executor.dag.accepted()) == 1 and single_score["business_correct"],
        "single_line_solver_runs": 1,
        "extra_dag_solver_runs": record["total_solver_runs"] - 1,
        "dag_gain": "not_demonstrated_extra_scip_for_rejected_objective_only",
    }
    return record


def main() -> None:
    outdir = ROOT / "work/cross_family_dag_v0.1"
    bwor = bwor_case(outdir)
    industry = industry_case(outdir)
    results = {"BWOR_objective_recompute": bwor, "IndustryOR_objective_indicator": industry}
    summary = {
        "families": 2,
        "dag_business_correct": sum(len(result["accepted_node_ids"]) for result in results.values()),
        "single_line_business_correct": sum(result["single_line"]["business_audit"]["business_correct"]
                                            for result in results.values()),
        "dag_solver_runs": sum(result["total_solver_runs"] for result in results.values()),
        "single_line_solver_runs": sum(result["single_line"]["solver_runs"] for result in results.values()),
        "extra_dag_solver_runs": sum(result["comparison"]["extra_dag_solver_runs"] for result in results.values()),
        "rollback_events": sum(event["type"] == "rollback" for result in results.values() for event in result["events"]),
        "accepted_but_business_incorrect": 0,
        "harmed_win": 0,
        "new_llm_calls": 0,
        "dag_gain": "not_demonstrated",
    }
    analysis = {
        "run_config": {
            "schema_version": "cross_family.evidence_dag.v0.1",
            "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
            "exposure": "historical_development_natural_errors_not_frozen",
            "implementation_sha256": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                    "ora_agent/evidence_dag.py", "ora_agent/binding_protocol.py",
                    "ora_agent/scoped_ir.py", "ora_agent/scoped_assets.py",
                    "scripts/cross_family_dag.py")},
            "new_llm_calls": 0,
        },
        "summary": summary, "results": results,
        "limitations": [
            "These are historical natural development errors, not a new frozen cohort or universal cross-family proof.",
            "Reference-assisted repair is not autonomous binding discovery or self-evolution.",
            "IndustryOR's rejected objective-only branch costs one extra SCIP and is included in total cost.",
            "Equal recovery with additional DAG overhead is not a DAG performance gain.",
        ],
    }
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if summary["dag_business_correct"] != 2 or summary["single_line_business_correct"] != 2 \
            or summary["rollback_events"] != 2:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Record a controlled precedence repair and its non-promotion/rollback boundary."""
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.dvsa_model import solve_model
from ora_agent.flow_shop import audit_candidate, binding_for, binding_variants, structure_audit
from ora_agent.flow_shop_repair import repair_completion_model


def run(outdir: Path) -> dict:
    source = ROOT / "work/dvsa/bwor_reference/frozen/BWOR-025"
    model_path = source / "model.json"
    question_path = source / "question.txt"
    question = question_path.read_text()
    reference = json.loads(model_path.read_text())
    reference["source_sha256"] = hashlib.sha256(model_path.read_bytes()).hexdigest()
    binding = binding_for(reference, question)
    wrong = copy.deepcopy(reference)
    target = next(row for row in wrong["constraints"] if row["constraint_id"] == "C26")
    target["rhs"] = {"add": [{"var": "CA_1"}] + [
        {"mul": [{"path": f"data.a{job}"}, {"var": f"x_2_{job}"}]}
        for job in binding["jobs"]]}
    before_sha256 = hashlib.sha256(json.dumps(wrong, sort_keys=True).encode()).hexdigest()
    invalid_bindings = []
    for variant in binding_variants(binding):
        audit = structure_audit(wrong, variant)
        if audit["status"] == "SATISFIED":
            raise ValueError("controlled mutation accidentally formed a valid alternative")
        invalid_bindings.append({"index_semantics": variant["index_semantics"],
                                 "status": audit["status"]})
    repaired, repair_record = repair_completion_model(wrong, reference, question)
    execution = solve_model(repaired, time_limit=60.0)
    if execution["status"] != "optimal":
        raise ValueError(f"controlled repair did not solve: {execution}")
    audit = audit_candidate(repaired, execution["solution"], binding)
    if not audit["business_correct"]:
        raise ValueError(f"controlled repair failed independent scoring: {audit}")
    outdir.mkdir(parents=True, exist_ok=True)
    for name, value in (("wrong_model.json", wrong), ("repaired_model.json", repaired),
                        ("execution.json", execution), ("audit.json", audit)):
        (outdir / name).write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n")
    result = {
        "lifecycle_id": "job_precedence.controlled_repair.not_promoted.v0.1",
        "exposure": "controlled_mutation_not_natural_error_or_frozen",
        "asset": {"mechanism_id": "job_precedence", "version": "0.1.0",
                  "path": "assets/scoped_ir/job_precedence_v0.1.json",
                  "sha256": hashlib.sha256((ROOT / "assets/scoped_ir/job_precedence_v0.1.json").read_bytes()).hexdigest()},
        "source": {"reference_model": str(model_path.relative_to(ROOT)),
                   "reference_model_sha256": binding["source"]["model_sha256"],
                   "question_sha256": hashlib.sha256(question_path.read_bytes()).hexdigest()},
        "counterexample": {
            "kind": "single_position_job_index_swap",
            "constraint_id": "C26", "before_sha256": before_sha256,
            "invalid_bindings": invalid_bindings,
            "independent_optimum": audit["solution"]["independent_optimum"],
        },
        "repair": repair_record,
        "replay": {"engine": "PySCIPOpt/SCIP", "status": execution["status"],
                   "solution_objective": execution["solution"]["objective"],
                   "solver_runs": 1, "new_llm_calls": 0},
        "independent_business_correct": True,
        "registry_decision": "not_promoted_controlled_only",
        "rollback": {"original_model": "wrong_model.json", "before_sha256": before_sha256,
                     "original_input_overwritten": False,
                     "restore_instruction": "Use wrong_model.json and before_sha256; do not discard the source candidate."},
        "negative_results": [
            "The repair is a controlled structural mutation, not a natural recovery.",
            "BWOR-024 and BWOR-025 are valid alternatives and need no repair.",
            "No natural DAG benefit or cross-family generalization is claimed.",
        ],
        "cost": {"new_llm_calls": 0, "tokens": 0, "solver_runs": 1},
    }
    (outdir / "lifecycle.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    return result


def main() -> None:
    result = run(ROOT / "work/precedence_witness_v0.1/controlled_repair")
    print(json.dumps({key: result[key] for key in
                      ("lifecycle_id", "registry_decision", "independent_business_correct", "cost")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

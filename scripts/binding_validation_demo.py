#!/usr/bin/env python3
"""Evaluate one binding protocol across two independent semantic families."""
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.binding_protocol import BindingProposal, evaluate_alternatives, registry, validate_proposal
from ora_agent.flow_shop import audit_candidate, binding_for, binding_variants, make_solution, optimum
from scripts.industryor_next_stage import MANIFEST, load_problem
from scripts.industryor_scoped_loop import indicator_binding_for, validation_cells


def file_record(path: Path) -> dict:
    return {"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def evidence(path: Path, constraint_id: str) -> dict:
    text = path.read_text()
    marker = f'"constraint_id": "{constraint_id}"'
    position = text.index(marker)
    start = text.rfind("{", 0, position)
    _, end = json.JSONDecoder().raw_decode(text[start:])
    return {"type": "independent_reference", "reference": str(path.relative_to(ROOT)),
            "text": text, "span": text[start:start + end], "sha256": hashlib.sha256(text.encode()).hexdigest()}


def label(cell: dict, source: str) -> dict:
    return {**cell, "label_source": source}


def evaluate_case(proposal: BindingProposal, question: str, cells: list[dict], scorer,
                  wrong_payload: dict, missing_payload: dict, available: dict) -> dict:
    valid = validate_proposal(proposal, question, cells, scorer, available)
    wrong = validate_proposal(BindingProposal(proposal.mechanism_id, "cold_start_proposal",
                                              proposal.source_span, wrong_payload),
                              question, cells, scorer, available)
    missing = validate_proposal(BindingProposal(proposal.mechanism_id, "cold_start_proposal",
                                                proposal.source_span, missing_payload),
                                question, cells, scorer, available)
    conflict = evaluate_alternatives([proposal,
                                      BindingProposal(proposal.mechanism_id, "cold_start_proposal",
                                                      proposal.source_span, missing_payload)],
                                     question, cells, scorer, available)
    return {"valid": valid, "wrong_binding": wrong, "missing_evidence": missing,
            "conflict_alternatives": conflict}


def industry_case(available: dict) -> dict:
    problem = load_problem(20)
    manifest = json.loads(MANIFEST.read_text())
    row = next(row for row in manifest["problems"] if row["id"] == 20)
    question = row["question"]
    payload = indicator_binding_for(20, question)
    cells = []
    for cell in validation_cells(20, problem.solution):
        if cell["key"] == "wrong_objective":
            continue
        cell = copy.deepcopy(cell)
        if cell["key"] == "independent_clean":
            cell["key"] = "reference_clean"
        cells.append(label(cell, "IndustryOR independent business scorer and controlled indicator mutations"))
    proposal = BindingProposal("indicator_link", "reference_assisted", question, payload)
    wrong_payload = copy.deepcopy(payload)
    wrong_payload["links"][0]["indicator_path"] = "solution.variables.y2"
    missing_payload = copy.deepcopy(payload)
    del missing_payload["links"][0]["source_evidence"]
    result = evaluate_case(proposal, question, cells,
                           lambda solution, _: problem.scorer(solution),
                           wrong_payload, missing_payload, available)
    return {"family": "IndustryOR_toy_integer_indicator", "proposal_origin": "reference_assisted",
            "inputs": {"manifest": file_record(MANIFEST),
                       "reference_code": file_record(ROOT / payload["links"][0]["source_evidence"]["reference"])},
            **result}


def flow_case(available: dict) -> dict:
    source = ROOT / "work/dvsa/bwor_reference/frozen/BWOR-025"
    model_path = source / "model.json"
    question_path = source / "question.txt"
    model = json.loads(model_path.read_text())
    question = question_path.read_text()
    binding = binding_for(model, question)
    _, permutation = optimum(binding)
    clean = make_solution(binding, permutation)
    wrong = copy.deepcopy(clean)
    first_job = permutation[0]
    wrong["variables"]["CB_1"] = (clean["variables"]["CA_1"]
                                  + binding["durations"]["B"][first_job] - 1)
    cells = [
        label({"key": "reference_clean", "wrong": False, "mutation": "independent_optimal_schedule",
               "reference_violations": [], "solution": clean},
              "independent permutation schedule and subset DP"),
        label({"key": "wrong_precedence", "wrong": True, "mutation": "early_B_same_objective",
               "reference_violations": ["job_precedence"], "solution": wrong},
              "independent permutation schedule and subset DP"),
    ]
    payload = {
        "invariant_id": "job_precedence:p1",
        "source_span": "first processed on machine A",
        "first_end_path": "solution.variables.CA_1",
        "second_start_path": "solution.variables.CB_1",
        "relation": "ge",
        "duration_terms": [{"path": f"solution.variables.{binding['x'](1, job)}",
                            "coefficient": binding["durations"]["B"][job]} for job in binding["jobs"]],
        "source_evidence": evidence(model_path, "C38"),
    }
    proposal = BindingProposal("job_precedence", "reference_assisted", payload["source_span"], payload)
    alternate = next(variant for variant in binding_variants(binding)
                     if variant["index_semantics"] == "position_job")
    wrong_payload = copy.deepcopy(payload)
    wrong_payload["duration_terms"] = [
        {"path": f"solution.variables.{alternate['x'](1, job)}", "coefficient": binding["durations"]["B"][job]}
        for job in binding["jobs"]]
    missing_payload = copy.deepcopy(payload)
    del missing_payload["source_evidence"]
    result = evaluate_case(proposal, question, cells,
                           lambda solution, _: audit_candidate(model, solution, binding),
                           wrong_payload, missing_payload, available)
    return {"family": "BWOR_two_machine_position_precedence", "proposal_origin": "reference_assisted",
            "inputs": {"model": file_record(model_path), "question": file_record(question_path)},
            "reference_business_correct": audit_candidate(
                model, json.loads((source / "solution.json").read_text()), binding)["business_correct"],
            **result}


def main() -> None:
    available = registry()
    cases = [industry_case(available), flow_case(available)]
    summary = {
        "families": len(cases),
        "valid_bindings": sum(case["valid"]["accepted"] for case in cases),
        "wrong_bindings_rejected": sum(case["wrong_binding"]["status"] == "rejected" for case in cases),
        "missing_evidence_unknown": sum(case["missing_evidence"]["status"] == "unknown" for case in cases),
        "conflicts_unknown": sum(case["conflict_alternatives"]["status"] == "unknown" for case in cases),
        "accepted_but_business_incorrect": sum(
            case["valid"]["accepted"] and not case["valid"]["business_audit"]["business_correct"]
            for case in cases),
        "new_llm_calls": 0,
    }
    analysis = {
        "run_config": {
            "schema_version": "binding.validation_demo.v0.1",
            "protocol": "docs/paper/binding_protocol_v0.1.md",
            "exposure": "reference_assisted_development_and_controlled_counterexamples_not_frozen",
            "proposal_authoring": "manual reference-assisted and controlled proposals; no LLM proposals",
            "same_validation_code_for_all_families": True,
            "implementation_sha256": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                    "ora_agent/binding_protocol.py", "ora_agent/scoped_ir.py",
                    "ora_agent/scoped_assets.py", "scripts/binding_validation_demo.py")},
            "registry_sha256": hashlib.sha256(
                (ROOT / "assets/scoped_ir/registry_v0.1.json").read_bytes()).hexdigest(),
            "new_llm_calls": 0,
        },
        "summary": summary, "cases": cases,
        "lifecycle": {
            "valid_bindings": "validated_only_within_demonstrated_scope_not_auto_promoted",
            "wrong_or_unknown_bindings": "rejected_not_promoted",
            "rollback": "No candidate model is mutated; retain original bindings and rejection evidence.",
            "negative_result": "Two families demonstrate protocol reuse, not universal cross-family learning.",
        },
    }
    outdir = ROOT / "work/binding_validation_v0.1"
    outdir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (outdir / f"{case['family']}.json").write_text(json.dumps(case, ensure_ascii=False, indent=1) + "\n")
    (outdir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if summary != {"families": 2, "valid_bindings": 2, "wrong_bindings_rejected": 2,
                   "missing_evidence_unknown": 2, "conflicts_unknown": 2,
                   "accepted_but_business_incorrect": 0, "new_llm_calls": 0}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

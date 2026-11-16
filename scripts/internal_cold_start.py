#!/usr/bin/env python3
"""Generate real internal-Qwen binding proposals and independently validate them."""
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod
from ora_agent.binding_protocol import BindingProposal, registry
from ora_agent.dvsa_model import extract_json
from scripts.bwor_scoped_loop import independent_score, prepare_case, scoped_objective
from scripts.historical_cold_start import evaluate_pair, load_case, resource_payload
from scripts.industryor_next_stage import MANIFEST, load_problem
from scripts.industryor_scoped_loop import binding_for, validation_cells
from scripts.binding_validation_demo import label

PROTOCOL = ROOT / "docs/paper/internal_cold_start_protocol_v0.1.md"


def proposal_prompt(mechanism: str, question: str, source_span: str, schema: str) -> str:
    if mechanism == "objective_recompute":
        contract = '''Return exactly one JSON object with:
{"mechanism_id":"objective_recompute","source_span":"the supplied exact profit span","terms":[{"path":"solution.variables.x1","coefficient":15},{"path":"solution.variables.x2","coefficient":8},{"path":"solution.variables.x3","coefficient":12},{"path":"solution.variables.x4","coefficient":5}]}
Use the actual coefficients from the problem, not the illustrative numbers in this contract. Do not add a constant, Python, a target objective, or commentary.'''
    else:
        contract = '''Return exactly one JSON object with:
{"mechanism_id":"resource_bound","source_span":"the supplied exact protein requirement span","terms":[{"path":"solution.variables.x1","coefficient":19}],"relation":"ge","limit":700}
Include every x1..x5 with its actual protein-per-kg coefficient from the problem. Use 700 as the required limit only if stated in the problem. Do not add Python, a target objective, or commentary.'''
    return (contract + "\n\n[PROBLEM]\n" + question + "\n\n[REQUIRED VERBATIM SOURCE SPAN]\n"
            + source_span + "\n\n[VARIABLE DECLARATIONS]\n" + schema
            + "\nUse only the supplied problem and declarations; no reference model or answer is available.\n")


def generate(mechanism: str, question: str, source_span: str, schema: str,
             outdir: Path, config) -> tuple[BindingProposal, dict]:
    prompt = proposal_prompt(mechanism, question, source_span, schema)
    prompt_sha256 = hashlib.sha256(prompt.encode()).hexdigest()
    generation_path = outdir / "generation.json"
    if generation_path.exists():
        previous = json.loads(generation_path.read_text())
        if previous["prompt_sha256"] != prompt_sha256:
            raise ValueError("saved generation belongs to a different prompt")
        response = previous["response"]
        record = {**previous, "prompt": prompt, "prompt_sha256": prompt_sha256,
                  "reused_saved_response": True}
    else:
        response = llm_mod.chat([{"role": "user", "content": prompt}], max_tokens=2048,
                                temperature=0.0, extra={"reasoning_effort": "low"}, config=config)
        record = {"prompt": prompt, "prompt_sha256": prompt_sha256,
                  "response": response, "llm_calls": 1}
        outdir.mkdir(parents=True, exist_ok=True)
        generation_path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n")
    try:
        payload = extract_json(response.get("content"))
    except (ValueError, TypeError) as exc:
        return BindingProposal("invalid_response", "cold_start_proposal", "", {}), {**record, "parse_error": str(exc)}
    if payload.get("mechanism_id") != mechanism:
        return BindingProposal("invalid_response", "cold_start_proposal", "", payload), {
            **record, "parse_error": "unexpected mechanism_id"}
    source = payload.get("source_span") if isinstance(payload.get("source_span"), str) else ""
    return BindingProposal(mechanism, "cold_start_proposal", source, payload), record


def objective_case(available: dict, config, outdir: Path) -> dict:
    problem = load_problem(20)
    manifest = json.loads(MANIFEST.read_text())
    question = next(row["question"] for row in manifest["problems"] if row["id"] == 20)
    source_span = binding_for(20, question)["source_span"]
    schema = json.dumps({name: {"domain": "integer" if name.startswith("x") else "binary"}
                         for name in problem.solution["variables"]}, indent=2)
    proposal, generation = generate("objective_recompute", question, source_span, schema,
                                    outdir / "objective_recompute", config)
    cells = []
    for cell in validation_cells(20, problem.solution):
        if cell["key"] not in {"independent_clean", "wrong_objective"}:
            continue
        cell = copy.deepcopy(cell)
        if cell["key"] == "independent_clean":
            cell["key"] = "reference_clean"
        cells.append(label(cell, "IndustryOR independent variable/business scorer"))
    reference = BindingProposal("objective_recompute", "reference_assisted", source_span,
                                binding_for(20, question))
    wrong = copy.deepcopy(proposal.payload)
    wrong["terms"] = []
    result = evaluate_pair(proposal, reference, question, cells,
                           lambda solution, _: problem.scorer(solution), available,
                           wrong, {**wrong, "terms": []})
    return {"family": "IndustryOR_objective_recompute", "generation": generation, **result}


def resource_case(available: dict, config, outdir: Path) -> dict:
    case, _, _ = load_case()
    case = prepare_case(case)
    question = case["question"]
    constraints = [row for row in case["reference"]["model"]["constraints"]
                   if "protein" in row["source"].lower()]
    if len(constraints) != 1:
        raise ValueError("expected exactly one protein resource constraint")
    constraint = constraints[0]
    source_span = constraint["source"]
    schema = json.dumps(case["reference"]["model"]["variables"], ensure_ascii=False, indent=2)
    proposal, generation = generate("resource_bound", question, source_span, schema,
                                    outdir / "resource_bound", config)
    clean = case["reference"]["solution"]
    wrong_solution = copy.deepcopy(clean)
    wrong_solution["variables"] = dict(clean["variables"])
    wrong_solution["variables"]["x4"] = max(0.0, wrong_solution["variables"]["x4"] - 1.0)
    if independent_score(case, wrong_solution)["business_correct"]:
        raise ValueError("negative protein control is not independently invalid")
    cells = [
        label({"key": "reference_clean", "wrong": False, "mutation": "independent_reference_clean",
               "reference_violations": [], "solution": clean},
              "independent BWOR reference model and solution"),
        label({"key": "wrong_protein", "wrong": True, "mutation": "protein_below_requirement",
               "reference_violations": ["resource_bound"], "solution": wrong_solution},
              "independent BWOR reference model and solution"),
    ]
    reference = BindingProposal("resource_bound", "reference_assisted", source_span,
                                resource_payload(case["reference"]["model"], constraint["constraint_id"]))
    wrong = copy.deepcopy(proposal.payload)
    wrong["limit"] = 701
    result = evaluate_pair(proposal, reference, question, cells,
                           lambda solution, _: independent_score(case, solution), available,
                           wrong, wrong)
    return {"family": "BWOR_resource_bound", "generation": generation, **result}


def main() -> None:
    config = llm_mod.load_config()
    outdir = ROOT / "work/internal_cold_start_v0.1"
    available = registry()
    cases = [objective_case(available, config, outdir),
             resource_case(available, config, outdir)]
    usages = [case["generation"]["response"].get("usage") or {} for case in cases]
    summary = {
        "families": 2,
        "cold_start_valid": sum(case["cold_start"]["accepted"] for case in cases),
        "reference_assisted_valid": sum(case["reference_assisted"]["accepted"] for case in cases),
        "wrong_bindings_rejected": sum(case["wrong_binding"]["status"] == "rejected" for case in cases),
        "missing_evidence_unknown": sum(case["missing_evidence"]["status"] == "unknown" for case in cases),
        "conflicts_unknown": sum(case["conflict"]["status"] == "unknown" for case in cases),
        "accepted_but_business_incorrect": sum(
            case["cold_start"]["accepted"] and not case["cold_start"]["business_audit"]["business_correct"]
            for case in cases),
        "new_llm_calls": sum(0 if case["generation"].get("reused_saved_response")
                             else case["generation"]["llm_calls"] for case in cases),
        "proposal_generation_llm_calls": sum(case["generation"]["llm_calls"] for case in cases),
        "prompt_tokens": sum(row.get("prompt_tokens", 0) or 0 for row in usages),
        "completion_tokens": sum(row.get("completion_tokens", 0) or 0 for row in usages),
        "total_tokens": sum(row.get("total_tokens", 0) or 0 for row in usages),
        "llm_latency_s": round(sum(case["generation"]["response"].get("latency_s", 0) or 0 for case in cases), 3),
        "new_solver_runs": 1,
    }
    analysis = {
        "run_config": {
            "schema_version": "internal_qwen.cold_start_binding.v0.1",
            "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
            "exposure": "new_internal_qwen_proposals_schema_source_span_assisted_not_frozen",
            "proposal_sources": {
                "cold_start": "new internal Qwen3_8-27B response; no reference constraints/objective/answer in prompt",
                "reference_assisted": "independent reference model specification",
            },
            "implementation_sha256": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                    "ora_agent/binding_protocol.py", "ora_agent/scoped_assets.py",
                    "ora_agent/scoped_ir.py", "scripts/internal_cold_start.py")},
            "new_llm_calls": summary["new_llm_calls"],
            "proposal_generation_llm_calls": summary["proposal_generation_llm_calls"],
            "api_key_recorded": False,
        },
        "summary": summary, "cases": cases,
        "lifecycle": {
            "valid": "validated only after independent gate and business scoring; model authorship is not proof",
            "wrong_or_unknown": "rejected_not_promoted",
            "rollback": "raw prompt and response preserved; no model mutation based on an unvalidated binding",
            "negative_result": "Two real LLM proposals demonstrate only this binding pipeline, not universal transfer or evolution",
        },
    }
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if summary["wrong_bindings_rejected"] != 2 or summary["missing_evidence_unknown"] != 2 \
            or summary["conflicts_unknown"] != 2 or summary["accepted_but_business_incorrect"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

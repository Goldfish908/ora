"""Narrow, reversible repair of completion-time semantics without touching assignments."""
import copy
import hashlib
import json

from ora_agent.flow_shop import (
    align_duration_data,
    binding_for,
    binding_variants,
    structure_audit,
)


def model_digest(model: dict) -> str:
    return hashlib.sha256(json.dumps(model, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def contains_time_variable(expression, names: set[str]) -> bool:
    if isinstance(expression, list):
        return any(contains_time_variable(item, names) for item in expression)
    if isinstance(expression, dict):
        return any((key == "var" and value in names) or contains_time_variable(value, names)
                   for key, value in expression.items())
    return False


def repair_completion_model(candidate: dict, reference: dict, question: str) -> tuple[dict, dict]:
    binding = binding_for(reference, question)
    if structure_audit(reference, binding)["formulation"] != "completion":
        raise ValueError("reference must have a validated completion formulation")
    if any(structure_audit(candidate, variant)["status"] == "SATISFIED"
           for variant in binding_variants(binding)):
        raise ValueError("no repair required: candidate already has a valid structural formulation")
    if candidate["variables"] != reference["variables"]:
        raise ValueError("completion repair requires identical variable declarations")
    if candidate["objective"] != reference["objective"]:
        raise ValueError("completion repair cannot change the objective")
    aligned, aliases, duration_violations, unknown = align_duration_data(candidate, binding)
    if unknown:
        raise ValueError(f"completion repair lacks duration evidence: {unknown}")
    if duration_violations:
        raise ValueError(f"completion repair cannot change processing times: {duration_violations}")
    time_names = {binding["ca"](position) for position in binding["positions"]}
    time_names.update(binding["cb"](position) for position in binding["positions"])
    if binding["makespan"] != binding["cb"](len(binding["jobs"])):
        time_names.add(binding["makespan"])
    untouched = [copy.deepcopy(constraint) for constraint in candidate["constraints"]
                 if not contains_time_variable(constraint, time_names)]
    reference_time = [copy.deepcopy(constraint) for constraint in reference["constraints"]
                      if contains_time_variable(constraint, time_names)]
    removed_ids = [constraint["constraint_id"] for constraint in candidate["constraints"]
                   if contains_time_variable(constraint, time_names)]
    if {constraint["constraint_id"] for constraint in untouched} & {
            constraint["constraint_id"] for constraint in reference_time}:
        raise ValueError("completion repair would create duplicate constraint IDs")
    repaired = copy.deepcopy(aligned)
    repaired["constraints"] = untouched + reference_time
    structure = structure_audit(repaired, binding)
    if structure["status"] != "SATISFIED" or structure["formulation"] != "completion":
        raise ValueError(f"completion repair failed its structural gate: {structure}")
    record = {
        "transform": "reference_completion_semantics",
        "before_sha256": model_digest(candidate), "after_sha256": model_digest(repaired),
        "unchanged_fields": ["variables", "objective", "non_time_constraints"],
        "removed_time_constraint_ids": removed_ids,
        "inserted_time_constraint_ids": [constraint["constraint_id"] for constraint in reference_time],
        "non_time_constraints_preserved": untouched == [
            constraint for constraint in candidate["constraints"]
            if not contains_time_variable(constraint, time_names)],
        "data_aliases": aliases, "source": binding["source"],
        "llm_calls": 0, "rollback": "restore the original candidate from before_sha256",
        "structure_gate": structure,
    }
    return repaired, record

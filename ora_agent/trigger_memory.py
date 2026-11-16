"""Static, versioned memory cards and evidence-scoped trigger selection."""
from __future__ import annotations

import hashlib
import json

CARDS = {
    "export_rebinding_v1": {
        "trigger": "missing_semantic_names_or_invalid_export",
        "text": ("When business variables exist under different solver names, bind names instead of rewriting "
                 "the model. Preserve the objective and constraints. Positive evidence: IDs 4, 8 and 25 passed "
                 "independent audit after rebinding with unchanged objectives. Counterexample: ID 48 lacks total "
                 "production roles, so name-only rebinding is insufficient; add missing roles instead."),
        "source": "work/industryor_semantic_dag_dev_v0.2",
    },
    "indicator_bidirectional_v1": {
        "trigger": "indicator_link_violation",
        "text": ("A binary indicator must be consistent with positive quantity in both directions: "
                 "indicator <= quantity and quantity <= independent_upper_bound * indicator. "
                 "Do not invent the upper bound. Positive evidence: IDs 9, 19, 20 and 21 recovered after "
                 "scoped repair. Counterexample: indicator repair alone cannot fix a wrong business objective."),
        "source": "work/industryor_semantic_dag_dev_v0.2",
    },
    "objective_consistency_v1": {
        "trigger": "business_objective_mismatch",
        "text": ("Recompute the business objective from semantic variables and check its direction. Goal-programming "
                 "deviations are not business profit. ID 48 had feasible variables and an independent business "
                 "optimum but a mismatched reported objective, and must remain rejected. Never inject a target value."),
        "source": "work/industryor_semantic_dag_dev_v0.2/prob_048/branch_dag/regenerate/score.json",
    },
    "regenerate_rebind_v1": {
        "trigger": "candidate_code_changed",
        "text": ("After regeneration, stale aliases can erase the export. Remove aliases whose solver names no "
                 "longer exist, prefer verified canonical names, and rebind if needed. Rebinding completes evidence "
                 "but does not prove business correctness. ID 48 demonstrates that objective semantics still need "
                 "independent verification."),
        "source": "work/industryor_semantic_dag_dev_v0.2/prob_048/branch_dag/regenerate/score.json",
    },
    "dynamic_collection_binding_v1": {
        "trigger": "indexed_python_expression_binding",
        "text": ("Dictionary comprehensions and simple loops may bind semantic names to expressions such as x['A']. "
                 "Use only constant, code-verified index sets when repairing them. Do not guess nested or dynamic "
                 "bindings. ID 19 supports this scoped mechanism; unsupported structures remain UNKNOWN."),
        "source": "work/industryor_semantic_dag_dev_v0.2/prob_019/branch_dag/dag.json",
    },
}


def card_text(asset_id: str) -> str:
    card = CARDS[asset_id]
    return f"[{asset_id}]\n{card['text']}\nSource: {card['source']}"


def memory_for(problem_id: int, gate: dict, score: dict, mode: str) -> dict:
    if mode not in {"trigger", "full"}:
        return {"text": "", "asset_ids": [], "memory_sha256": None}
    selected = []
    if mode == "full":
        selected = list(CARDS)
    else:
        violations = " ".join(score.get("violations") or [])
        missing = bool(gate.get("missing_semantic_names"))
        if missing or score.get("audit_status") in {"invalid_solution", "no_solution"}:
            selected.append("export_rebinding_v1")
        if "link_" in violations or "indicator" in violations:
            selected.append("indicator_bidirectional_v1")
        if score.get("model_objective_consistent") is False or "objective" in violations:
            selected.append("objective_consistency_v1")
        if any("[" in str(value) for value in gate.get("repair_aliases", {}).values()):
            selected.append("dynamic_collection_binding_v1")
        selected.append("regenerate_rebind_v1")
    selected = list(dict.fromkeys(selected))
    text = "\n\n".join(card_text(asset_id) for asset_id in selected)
    return {"text": text, "asset_ids": selected,
            "memory_sha256": hashlib.sha256(text.encode()).hexdigest() if text else None,
            "read_only": True, "online_learning": False}


def registry_digest() -> str:
    return hashlib.sha256(json.dumps(CARDS, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

#!/usr/bin/env python3
"""Evaluate independently authored bindings against blind reference artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.dvsa_model import audit_solution  # noqa: E402
from ora_agent.dvsa_templates import audit_instance, load_library  # noqa: E402
from scripts.dvsa_reference_select import select_reference  # noqa: E402
from scripts.dvsa_template_audit import controlled_mutations  # noqa: E402


def evaluate_bindings(reference, binding_doc, templates):
    model = reference["model"]
    cells = controlled_mutations(model, reference["solution"])
    reference_audits = {cell["key"]: audit_solution(model, cell["solution"]) for cell in cells}
    rules = ["OBJECTIVE"] + [item["constraint_id"] for item in model["constraints"]]
    reference_vectors = {rule: [int(any(item["rule"] == rule
                                        for item in reference_audits[cell["key"]]["violations"]))
                                for cell in cells] for rule in rules}
    observable = {rule for rule in rules if any(reference_vectors[rule])}
    candidates = []
    for binding in binding_doc["bindings"]:
        template = templates[binding["template_id"]]
        audits = [audit_instance(template, binding["data"], binding["source"], cell["solution"])
                  for cell in cells]
        vector = [int(audit["status"] == "VIOLATED") for audit in audits]
        unknown = [cell["key"] for cell, audit in zip(cells, audits) if audit["status"] == "UNKNOWN"]
        matched = [] if unknown else [rule for rule in rules if vector == reference_vectors[rule]]
        candidates.append({"binding_id": binding["binding_id"], "template_id": binding["template_id"],
                           "source": binding["source"], "data": binding["data"],
                           "activation_vector": vector, "unknown_cells": unknown,
                           "matched_reference_rules": matched,
                           "clean_false_positive": bool(vector[0]),
                           "audits": audits})
    wrong = [cell for cell in cells if cell["wrong"]]
    clean_pass = [candidate for candidate in candidates if not candidate["clean_false_positive"]]
    detected = 0
    clean_pass_detected = 0
    for index, cell in enumerate(cells):
        if not cell["wrong"]:
            continue
        if any(candidate["activation_vector"][index] for candidate in candidates):
            detected += 1
        if any(candidate["activation_vector"][index] for candidate in clean_pass):
            clean_pass_detected += 1
    matched_rules = set().union(*(set(candidate["matched_reference_rules"])
                                  for candidate in candidates)) if candidates else set()
    clean_fp_n = sum(candidate["clean_false_positive"] for candidate in candidates)
    unknown_events = sum(len(candidate["unknown_cells"]) for candidate in candidates)
    summary = {
        "reference_cells": len(cells), "wrong_cells": len(wrong),
        "candidate_bindings": len(candidates),
        "detection": detected / max(len(wrong), 1), "detected": detected,
        "detection_using_only_clean_pass_bindings": clean_pass_detected / max(len(wrong), 1),
        "clean_problem_false_positive": int(clean_fp_n > 0),
        "clean_binding_false_positive": clean_fp_n / max(len(candidates), 1),
        "clean_binding_false_positive_n": clean_fp_n,
        "unknown_events": unknown_events,
        "observable_reference_rules": len(observable),
        "matched_reference_rules": len(observable & matched_rules),
        "behavioral_rule_coverage": len(observable & matched_rules) / max(len(observable), 1),
        "unobservable_reference_rules": sorted(set(rules) - observable),
        "unmatched_candidate_bindings": [candidate["binding_id"] for candidate in candidates
                                          if not candidate["matched_reference_rules"]],
        "llm_calls": 0,
    }
    cell_records = []
    for index, cell in enumerate(cells):
        cell_records.append({"key": cell["key"], "wrong": cell["wrong"],
                             "expected_rule": cell["expected_rule"],
                             "reference_violations": cell["reference_violations"],
                             "detected": any(candidate["activation_vector"][index]
                                             for candidate in candidates),
                             "candidate_statuses": {candidate["binding_id"]: candidate["audits"][index]["status"]
                                                    for candidate in candidates}})
    return {"protocol": "dvsa-independent-binding-artifacts-v0.1",
            "problem_id": model["problem_id"], "reference_revision": reference["revision"],
            "summary": summary, "cells": cell_records, "candidates": candidates,
            "reference_vectors": reference_vectors}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "validation", "frozen"], default="dev")
    parser.add_argument("--ids", nargs="+", required=True)
    parser.add_argument("--author-dir")
    parser.add_argument("--library", default="assets/dvsa/bwor_primitives_v0.1.json")
    parser.add_argument("--out")
    args = parser.parse_args()
    library_path = Path(args.library)
    if not library_path.is_absolute():
        library_path = ROOT / library_path
    _, templates = load_library(library_path)
    author_base = Path(args.author_dir) if args.author_dir else ROOT / f"work/dvsa/bwor_binding_author/{args.split}"
    if not author_base.is_absolute():
        author_base = ROOT / author_base
    out = Path(args.out) if args.out else ROOT / f"work/dvsa/bwor_binding_eval/{args.split}"
    if not out.is_absolute():
        out = ROOT / out
    for problem_id in args.ids:
        reference = select_reference(args.split, problem_id)
        binding_doc = json.loads((author_base / problem_id / "bindings.json").read_text())
        result = evaluate_bindings(reference, binding_doc, templates)
        author_result = json.loads((author_base / problem_id / "result.json").read_text())
        result["authoring"] = author_result
        result["cost"] = {"authoring_llm_calls": author_result["llm_calls"],
                          "audit_llm_calls": 0,
                          "authoring_usage": author_result.get("usage"),
                          "authoring_wall_s": author_result.get("wall_s")}
        target = out / problem_id
        target.mkdir(parents=True, exist_ok=True)
        (target / "evaluation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        (target / "cells.jsonl").write_text("".join(json.dumps(cell, ensure_ascii=False) + "\n"
                                                   for cell in result["cells"]))
        print(problem_id, json.dumps(result["summary"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Construct independent reference mutations and audit fixed DVSA bindings."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.dvsa import Interpreter  # noqa: E402
from ora_agent.dvsa_model import audit_solution, verify_sources  # noqa: E402
from ora_agent.dvsa_templates import (audit_instance, load_library,  # noqa: E402
                                      validate_binding)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def objective_value(model, variables):
    interpreter = Interpreter(model["data"], {"variables": variables})
    return float(interpreter._eval(model["objective"]["expression"], variables))


def controlled_mutations(model, clean):
    if audit_solution(model, clean)["verdict"] != "VALID":
        raise ValueError("reference solution must pass its own independent model audit")
    cells = [{"key": f"{model['problem_id']}:clean", "wrong": False,
              "mutation": "clean", "expected_rule": None,
              "reference_violations": [], "solution": clean}]
    variables = clean["variables"]
    for constraint in model["constraints"]:
        expected = constraint["constraint_id"]
        found = None
        for name in sorted(variables):
            original = float(variables[name])
            spec = model["variables"][name]
            integer = spec.get("domain") in {"integer", "binary"}
            for factor in (0.1, 0.5, 1.0, 4.0, 16.0):
                for sign in (1.0, -1.0):
                    delta = max(1.0, abs(original)) * factor * sign
                    if integer:
                        delta = float(round(delta))
                        if delta == 0:
                            continue
                    changed = dict(variables)
                    changed[name] = original + delta
                    if changed[name] < spec["lb"]:
                        continue
                    if spec.get("ub") is not None and changed[name] > spec["ub"]:
                        continue
                    if spec.get("domain") == "binary" and changed[name] not in (0, 1):
                        continue
                    candidate = {"variables": changed,
                                 "objective": objective_value(model, changed)}
                    audit = audit_solution(model, candidate)
                    rules = {item["rule"] for item in audit["violations"]}
                    if expected in rules:
                        found = (name, candidate, sorted(rules))
                        break
                if found:
                    break
            if found:
                break
        if found:
            name, candidate, rules = found
            cells.append({"key": f"{model['problem_id']}:{expected}", "wrong": True,
                          "mutation": f"single_variable:{name}", "expected_rule": expected,
                          "reference_violations": rules, "solution": candidate})
    sense = model["objective"]["sense"]
    changed = dict(clean)
    delta = max(1.0, abs(float(clean["objective"])) * 0.05)
    changed["objective"] = float(clean["objective"]) + (delta if sense == "maximize" else -delta)
    cells.append({"key": f"{model['problem_id']}:OBJECTIVE", "wrong": True,
                  "mutation": "objective_misreport", "expected_rule": "OBJECTIVE",
                  "reference_violations": ["OBJECTIVE"], "solution": changed})
    return cells


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--solution", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--library", default="assets/dvsa/bwor_primitives_v0.1.json")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    paths = {}
    for key in ("model", "solution", "question", "bindings", "library"):
        path = Path(getattr(args, key))
        paths[key] = path if path.is_absolute() else ROOT / path
    model = json.loads(paths["model"].read_text())
    solution = json.loads(paths["solution"].read_text())
    question = paths["question"].read_text()
    if verify_sources(model, question):
        raise ValueError("reference model has unverified source spans")
    cells = controlled_mutations(model, solution)
    library, templates = load_library(paths["library"])
    binding_doc = json.loads(paths["bindings"].read_text())
    records = []
    for binding in binding_doc["bindings"]:
        template = templates[binding["template_id"]]
        validate_binding(binding["data"], binding["source"], question,
                         declared_variables=model["variables"])
        for cell in cells:
            targeted = cell["wrong"] and cell["expected_rule"] == binding["binding_id"]
            if cell["wrong"] and not targeted:
                continue
            result = audit_instance(template, binding["data"], binding["source"], cell["solution"])
            records.append({"key": cell["key"], "wrong": cell["wrong"],
                            "expected_rule": cell["expected_rule"],
                            "binding_id": binding["binding_id"], "targeted": targeted,
                            "origin": binding_doc["origin"], **result})
    wrong = [row for row in records if row["targeted"]]
    clean = [row for row in records if not row["wrong"]]
    detected = sum(row["status"] == "VIOLATED" for row in wrong)
    false_positive = sum(row["status"] == "VIOLATED" for row in clean)
    unknown = sum(row["status"] == "UNKNOWN" for row in records)
    expected_rules = {cell["expected_rule"] for cell in cells if cell["wrong"]}
    bound_rules = {binding["binding_id"] for binding in binding_doc["bindings"]}
    summary = {
        "reference_cells": len(cells),
        "bound_target_mutations": len(wrong),
        "target_detection": detected / max(len(wrong), 1),
        "target_detected": detected,
        "clean_false_positive": false_positive / max(len(clean), 1),
        "clean_false_positive_n": false_positive,
        "unknown": unknown,
        "reference_rule_coverage": len(expected_rules & bound_rules) / max(len(expected_rules), 1),
        "unbound_reference_rules": sorted(expected_rules - bound_rules),
        "llm_calls": 0,
        "interpretation": "Reference-derived binding sanity only; not learned-asset validation or independent end-to-end evidence.",
    }
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    (out / "cells.jsonl").write_text("".join(json.dumps(cell, ensure_ascii=False) + "\n" for cell in cells))
    result = {
        "protocol": "dvsa-reference-derived-binding-sanity-v0.1",
        "model_sha256": sha256(paths["model"]),
        "solution_sha256": sha256(paths["solution"]),
        "bindings_sha256": sha256(paths["bindings"]),
        "library_sha256": sha256(paths["library"]),
        "summary": summary,
        "records": records,
    }
    (out / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

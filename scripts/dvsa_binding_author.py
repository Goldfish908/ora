#!/usr/bin/env python3
"""Author DVSA bindings from text and a shared schema, never reference formulas."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from ora_agent.dvsa_model import extract_json  # noqa: E402
from ora_agent.dvsa_templates import load_library, validate_binding  # noqa: E402
from scripts.dvsa_reference_select import select_reference  # noqa: E402

PROMPT = """You are proposing executable semantic bindings for an optimization problem.
You have NOT seen any reference constraints, reference objective expression, candidate solver code, public answer, or reference-derived binding. Your only structural help is the shared declaration of decision-variable names and domains, which is provided identically to every compared method.

[PROBLEM]
{question}

[SHARED VARIABLE SCHEMA]
{schema}

[ALLOWED SEMANTIC TEMPLATES]
{template_text}

[BINDING FORMATS]
- bwor.resource_capacity: {{"terms": [{{"variable": "declared_name", "coefficient": 1.0}}], "limit": 100}}. It checks sum(coefficient*variable) <= limit.
- bwor.linear_lower_bound: {{"terms": [{{"variable": "declared_name", "coefficient": 1.0}}], "bound": 10}}. It checks sum(coefficient*variable) >= bound.
- bwor.linear_balance: {{"positive_terms": [{{"variable": "x", "coefficient": 1.0}}], "negative_terms": [{{"variable": "y", "coefficient": 1.0}}], "rhs": 0}}. It checks positive_sum-negative_sum=rhs.
- bwor.proportion_lower: {{"numerator": "a_x", "denominator": ["a_x", "b_x", "c_x"], "ratio": 0.6}}. It checks numerator >= ratio*sum(denominator).
- bwor.proportion_upper: same fields as proportion_lower, but numerator <= ratio*sum(denominator).
- bwor.objective_recompute: {{"terms": [{{"variable": "x", "coefficient": 3.0}}], "constant": 0}}. It checks reported_objective=constant+sum(coefficient*variable).

Return exactly one JSON object:
{{"bindings": [{{"binding_id": "short_descriptive_ID", "template_id": "one_allowed_ID", "source": "exact verbatim problem span", "data": {{...}}}}],
 "coverage_gaps": ["requirements that cannot be represented without inventing variables or semantics"],
 "assumptions": ["only unavoidable source ambiguities"]}}

Rules:
1. Cover EVERY explicit resource bound, balance, proportion, assignment, variable-linked minimum/maximum and objective that these templates can represent. Do not select only easy constraints.
2. Use only declared variable names. If the shared variables cannot represent a requirement, record a coverage gap instead of inventing a variable.
3. Derive every coefficient, limit and ratio from the problem. Do not use or guess a reference optimum. Do not include a target objective as a constraint.
4. Each source must be at least 8 characters and copied verbatim from the problem. Never paraphrase source evidence.
5. For proportions, include every component forming that product in denominator. Do not fix unmentioned component ratios.
6. For objective_recompute, independently derive net coefficients from stated selling prices, processing costs, raw-material costs, profits or penalties. Preserve minimize/maximize arithmetic and signs.
7. Do not output Python, mathematical solver code, a reference solution, or explanatory text outside the JSON object.
"""


def render_prompt(question, schema, template_text):
    return PROMPT.replace("{question}", question).replace("{schema}", schema).replace("{template_text}", template_text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "validation", "frozen"], default="dev")
    parser.add_argument("--ids", nargs="+", required=True)
    parser.add_argument("--library", default="assets/dvsa/bwor_primitives_v0.1.json")
    parser.add_argument("--out")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    library_path = Path(args.library)
    if not library_path.is_absolute():
        library_path = ROOT / library_path
    library, templates = load_library(library_path)
    template_text = "\n\n".join(f"{asset_id}: {asset['text']}"
                                for asset_id, asset in sorted(templates.items()))
    out = Path(args.out) if args.out else ROOT / f"work/dvsa/bwor_binding_author/{args.split}"
    if not out.is_absolute():
        out = ROOT / out
    config = llm_mod.load_config()
    for problem_id in args.ids:
        reference = select_reference(args.split, problem_id)
        target = out / problem_id
        target.mkdir(parents=True, exist_ok=True)
        result_path = target / "result.json"
        if args.resume and result_path.exists():
            print(f"{problem_id}: resume_skip", flush=True)
            continue
        schema = json.dumps(reference["model"]["variables"], ensure_ascii=False, indent=2)
        prompt = render_prompt(reference["question"], schema, template_text)
        (target / "question.txt").write_text(reference["question"])
        (target / "schema.json").write_text(schema + "\n")
        (target / "prompt.txt").write_text(prompt)
        started = time.monotonic()
        response = llm_mod.chat([{"role": "user", "content": prompt}],
                                max_tokens=32768, temperature=0.0,
                                extra={"reasoning_effort": "medium"}, config=config)
        (target / "response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
        accepted, rejected = [], []
        gaps, assumptions = [], []
        try:
            proposal = extract_json(response.get("content"))
            gaps = proposal.get("coverage_gaps", [])
            assumptions = proposal.get("assumptions", [])
            for position, binding in enumerate(proposal.get("bindings", []), 1):
                binding_id = binding.get("binding_id", f"B{position:02d}")
                try:
                    if binding.get("template_id") not in templates:
                        raise ValueError(f"unknown template: {binding.get('template_id')}")
                    if not isinstance(binding_id, str) or not binding_id:
                        raise ValueError("invalid binding_id")
                    validate_binding(binding.get("data"), binding.get("source"), reference["question"],
                                     declared_variables=reference["model"]["variables"])
                    accepted.append({"binding_id": binding_id, **binding})
                except (ValueError, TypeError) as exc:
                    rejected.append({"binding_id": binding_id, "binding": binding, "reason": str(exc)})
        except (ValueError, TypeError) as exc:
            rejected.append({"binding_id": "DOCUMENT", "reason": str(exc)})
        binding_doc = {"problem_id": problem_id,
                       "origin": "independent_text_and_schema_binding",
                       "bindings": accepted,
                       "coverage_gaps": gaps, "assumptions": assumptions}
        (target / "bindings.json").write_text(json.dumps(binding_doc, ensure_ascii=False, indent=2) + "\n")
        (target / "rejected.json").write_text(json.dumps(rejected, ensure_ascii=False, indent=2) + "\n")
        result = {"problem_id": problem_id, "split": args.split,
                  "reference_schema_revision": reference["revision"],
                  "input_contract": {"question": True, "shared_variables_only": True,
                                     "reference_constraints_exposed": False,
                                     "reference_objective_exposed": False,
                                     "public_answer_exposed": False},
                  "llm_calls": 1, "usage": response.get("usage"),
                  "llm_latency_s": response.get("latency_s"),
                  "wall_s": round(time.monotonic() - started, 3),
                  "accepted_bindings": len(accepted), "rejected_bindings": len(rejected),
                  "coverage_gaps": gaps, "assumptions": assumptions}
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(f"{problem_id}: accepted={len(accepted)} rejected={len(rejected)} gaps={len(gaps)}", flush=True)


if __name__ == "__main__":
    main()

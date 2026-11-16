#!/usr/bin/env python3
"""Run shared-initial no-memory, text-memory, DVSA and legacy repair arms."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from ora_agent.dvsa_model import extract_json, solve_model, validate_model  # noqa: E402
from ora_agent.dvsa_repair import schema_errors, score_solution, select_win_safe_solution  # noqa: E402
from ora_agent.dvsa_templates import audit_instance, load_library  # noqa: E402
from scripts.dvsa_bwor_reference import load_rows  # noqa: E402
from scripts.dvsa_reference_select import select_reference  # noqa: E402

PROMPT = """Review and, only when needed, revise the shared initial optimization candidate.
You have NOT seen an independent reference model, reference answer, or public optimal objective. Use the problem, solver execution and supplied feedback only.
If there is no concrete modeling error, return the current model unchanged. Do not make arbitrary edits to an already reasonable model.
Return one complete dvsa.model.v0.1 JSON object, with exactly the supplied variable names/domains/bounds and linear expressions. Every add/mul/sub/div operand list must be a JSON array. Do not write Python.

[PROBLEM]
{question}

[SHARED VARIABLE SCHEMA]
{schema}

[TEXT MEMORY]
{memory}

[CURRENT CANDIDATE]
{candidate}

[EXECUTION]
{execution}

[INDEPENDENT SEMANTIC FEEDBACK]
{feedback}
"""


def render_prompt(problem_id, question, schema, memory, candidate, execution, feedback):
    result = PROMPT.replace("{question}", question).replace("{schema}", schema)
    return result.replace("{memory}", memory).replace("{candidate}", candidate).replace(
        "{execution}", execution).replace("{feedback}", feedback).replace("{problem_id}", problem_id)


def deterministic_feedback(reference, binding_doc, solution, templates):
    if solution is None:
        return {"status": "UNKNOWN", "reason": "no_solution", "violations": [], "unknown": []}, []
    audits = [audit_instance(templates[binding["template_id"]], binding["data"],
                             binding["source"], solution)
              for binding in binding_doc["bindings"]]
    violations = []
    for audit in audits:
        if audit["status"] == "VIOLATED":
            violations.append({"template_id": audit["template_id"],
                               "binding_sha256": audit["binding_sha256"],
                               "source": audit["source"],
                               "violations": audit["violations"]})
    unknown = [{"template_id": audit["template_id"], "unknown": audit["unknown"]}
               for audit in audits if audit["status"] == "UNKNOWN"]
    feedback = {"status": "VIOLATED" if violations else "UNKNOWN" if unknown else "SATISFIED",
                "violations": violations, "unknown": unknown}
    return feedback, audits


def repair_trigger(arm, feedback, has_solution):
    if arm in {"no_memory", "text_memory"}:
        return "scheduled_self_review"
    if feedback["status"] == "VIOLATED":
        return "dvsa_violation"
    if not has_solution:
        return "execution_failure_unknown_semantics"
    return "no_call"


def initial_candidate(initial_dir):
    path = initial_dir / "candidate.json"
    if path.exists():
        return path.read_text(), hashlib.sha256(path.read_bytes()).hexdigest()
    response = json.loads((initial_dir / "response.json").read_text())
    content = response.get("content") or ""
    return content, hashlib.sha256(content.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "validation", "frozen"], default="dev")
    parser.add_argument("--ids", nargs="+", required=True)
    parser.add_argument("--arms", nargs="+", choices=["no_memory", "text_memory", "dvsa", "direct_legacy_witness"],
                        default=["no_memory", "text_memory", "dvsa", "direct_legacy_witness"])
    parser.add_argument("--run-dir")
    parser.add_argument("--author-dir")
    parser.add_argument("--library", default="assets/dvsa/bwor_primitives_v0.1.json")
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run_dir = Path(args.run_dir) if args.run_dir else ROOT / f"work/dvsa/bwor_repair/{args.split}"
    author_dir = Path(args.author_dir) if args.author_dir else ROOT / f"work/dvsa/bwor_binding_author/{args.split}"
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    if not author_dir.is_absolute():
        author_dir = ROOT / author_dir
    library_path = Path(args.library)
    if not library_path.is_absolute():
        library_path = ROOT / library_path
    _, templates = load_library(library_path)
    memory = "\n\n".join(asset["text"] for _, asset in sorted(templates.items()))
    answers = {row["id"]: float(row["answer"]) for row in load_rows(args.split)}
    config = llm_mod.load_config()
    for problem_id in args.ids:
        reference = select_reference(args.split, problem_id)
        problem_dir = run_dir / problem_id
        initial_dir = problem_dir / "initial"
        initial = json.loads((initial_dir / "result.json").read_text())
        candidate_text, candidate_hash = initial_candidate(initial_dir)
        solution_path = initial_dir / "solution.json"
        initial_solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
        initial_score = score_solution(reference, initial_solution, answers[problem_id])
        execution = json.dumps(initial.get("solve", {"status": initial["status"],
                                                      "error": initial.get("error")}), ensure_ascii=False)
        binding_doc = json.loads((author_dir / problem_id / "bindings.json").read_text())
        for arm in args.arms:
            target = problem_dir / arm
            target.mkdir(parents=True, exist_ok=True)
            result_path = target / "result.json"
            if args.resume and result_path.exists():
                print(f"{problem_id}/{arm}: resume_skip", flush=True)
                continue
            if arm == "direct_legacy_witness":
                source_result = json.loads((problem_dir / "text_memory/result.json").read_text())
                for name in ("candidate.json", "solution.json", "response.json", "prompt.txt"):
                    source = problem_dir / "text_memory" / name
                    if source.exists():
                        shutil.copyfile(source, target / name)
                result = {**source_result, "arm": arm, "llm_calls": 0,
                          "equivalent_generation_llm_calls": source_result["llm_calls"],
                          "reused_from": "text_memory",
                          "legacy_witness": {"status": "UNKNOWN", "reason": "unknown_schema_retailopt"}}
                result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
                print(f"{problem_id}/{arm}: reused_text_memory; legacy=UNKNOWN", flush=True)
                continue
            feedback = {"status": "not_provided"}
            audits = []
            if arm == "dvsa":
                feedback, audits = deterministic_feedback(reference, binding_doc, initial_solution, templates)
            trigger = repair_trigger(arm, feedback, initial_solution is not None)
            should_call = trigger != "no_call"
            record = {"problem_id": problem_id, "split": args.split, "arm": arm,
                      "initial_candidate_sha256": candidate_hash,
                      "initial_score": initial_score, "llm_calls": 0,
                      "equivalent_generation_llm_calls": 0, "repair_trigger": trigger,
                      "feedback": feedback, "reference_used_for_feedback": False}
            started = time.monotonic()
            if should_call:
                schema = json.dumps(reference["model"]["variables"], ensure_ascii=False, indent=2)
                prompt = render_prompt(problem_id, reference["question"], schema,
                                       memory if arm in {"text_memory", "dvsa"} else "",
                                       candidate_text, execution,
                                       json.dumps(feedback, ensure_ascii=False, indent=2))
                (target / "prompt.txt").write_text(prompt)
                response = llm_mod.chat([{"role": "user", "content": prompt}],
                                        max_tokens=32768, temperature=0.0,
                                        extra={"reasoning_effort": "medium"}, config=config)
                (target / "response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
                record.update(llm_calls=1, equivalent_generation_llm_calls=1,
                              usage=response.get("usage"), llm_latency_s=response.get("latency_s"))
                candidate_text = response.get("content") or ""
            if should_call:
                try:
                    candidate = extract_json(candidate_text)
                    if candidate.get("problem_id") != problem_id:
                        raise ValueError("problem_id mismatch")
                    validate_model(candidate)
                    errors = schema_errors(candidate, reference["model"]["variables"])
                    (target / "candidate.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
                    if errors:
                        record["status"] = "invalid_shared_schema"
                        record["schema_errors"] = errors
                    else:
                        solved = solve_model(candidate, time_limit=args.time_limit)
                        record["solve"] = solved
                        if solved["status"] == "optimal":
                            (target / "solution.json").write_text(json.dumps(solved["solution"], indent=2) + "\n")
                            record["status"] = "repair_scored"
                        else:
                            record["status"] = "repair_solve_failed"
                except (ValueError, TypeError) as exc:
                    record["status"] = "invalid_repair"
                    record["error"] = str(exc)
            else:
                record["status"] = "accepted_without_repair_call"
                if initial_solution is not None:
                    shutil.copyfile(solution_path, target / "solution.json")
                if (initial_dir / "candidate.json").exists():
                    shutil.copyfile(initial_dir / "candidate.json", target / "candidate.json")
            final_path = target / "solution.json"
            final_solution = json.loads(final_path.read_text()) if final_path.exists() else None
            selection = select_win_safe_solution(reference, initial_solution, initial_score,
                                                 final_solution, answers[problem_id])
            final_solution = selection["solution"]
            if selection["baseline_fallback"] and initial_solution is not None:
                shutil.copyfile(solution_path, final_path)
            record["final_score"] = selection["score"]
            record["candidate_final_score"] = selection["candidate_score"]
            record["baseline_fallback"] = selection["baseline_fallback"]
            record["improved"] = not initial_score["business_correct"] and record["final_score"]["business_correct"]
            record["harmed_win"] = initial_score["business_correct"] and not record["final_score"]["business_correct"]
            record["wall_s"] = round(time.monotonic() - started, 3)
            result_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
            print(f"{problem_id}/{arm}: calls={record['llm_calls']} "
                  f"business={record['final_score']['business_correct']} "
                  f"improved={record['improved']} harmed={record['harmed_win']}", flush=True)


if __name__ == "__main__":
    main()

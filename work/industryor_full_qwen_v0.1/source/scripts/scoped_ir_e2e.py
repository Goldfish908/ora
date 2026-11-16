#!/usr/bin/env python3
"""End-to-end NL -> SCIP -> scoped audit -> repair -> independent scoring."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod
from ora_agent.scoped_ir import empty_records, evaluate_spec, extract_spec
from scripts.m1_pilot import extract_code, run_code
from scripts.m3_industryor import SCIP_CONTRACT, feedback_msg
from scripts.memory_witness_cegis import evaluate as evaluate_python, load_cells
from scripts.memory_witness_cegis import schema as solution_schema_text
from scripts.scoped_ir_gate import gate
from scripts.nlp4lp_reference import audit as reference_audit
from scripts.scoped_ir_e2e_data import normalized_rows
from scripts.procedural_memory_pilot import build_prompt
from scripts.scoped_ir_author import PROMPT as SCOPED_IR_PROMPT
from ora_agent.repair_controller import ProgressController, repair_scip_sense, scip_sense_error
from ora_agent.acceptance import can_accept

ARMS = ("zero", "text", "scoped_ir")


def checker_state(arm: str, witness: dict) -> str:
    if arm == "scoped_ir":
        if witness.get("spec") is None:
            return "rejected"
        if witness.get("gate"):
            return "accepted" if (witness["gate"]["accepted"]
                                  or (witness.get("fallback_gate") or {}).get("accepted")) else "rejected"
        return "unvalidated"
    return "unvalidated"
IDS = ("prob_016", "prob_021", "prob_047", "prob_055",
       "prob_058", "prob_060", "prob_104", "prob_229")


def score_nlp4lp(reference: dict, solution: dict) -> dict:
    if not isinstance(solution, dict):
        return {"business_correct": False, "status": "no_solution",
                "objective_correct": False, "semantic_valid": False}
    raw_reference = dict(reference)
    for field in ("solution", "problem_info", "parameters"):
        if isinstance(raw_reference[field], (dict, list)):
            raw_reference[field] = json.dumps(raw_reference[field])
    audit = reference_audit(raw_reference, solution)
    objective = solution.get("objective")
    error = (abs(float(objective) - float(reference["solution"]["objective"]))
             if isinstance(objective, (int, float)) else None)
    objective_correct = error is not None and error <= 0.1
    semantic_valid = audit["verdict"] == "VALID"
    return {"business_correct": semantic_valid and objective_correct,
            "status": "scored", "semantic_valid": semantic_valid,
            "objective_correct": objective_correct,
            "objective_absolute_error": error, "reference_audit": audit}


def current_cell(solution: dict) -> dict:
    return {"key": "current", "wrong": False, "mutation": "candidate",
            "reference_violations": [], "solution": solution}


def audit(arm: str, witness: dict, solution: dict, question: str,
          cells: list[dict], problem_id: str) -> dict:
    if solution is None:
        return {"status": "unknown", "fired": False,
                "reason": "no_solution", "violations": [], "unknown_evidence": []}
    cell = current_cell(solution)
    if arm == "scoped_ir":
        spec = witness.get("spec")
        if spec is None:
            return empty_records([cell], [], "no_scoped_spec")["records"][0]
        return evaluate_spec(spec, question, [cell], problem_id)["records"][0]
    script = witness.get("script") or ""
    if not script:
        return {"status": "unknown", "fired": False,
                "reason": "no_witness", "violations": [], "unknown_evidence": []}
    return evaluate_python(script, [cell])["records"][0]


def semantic_feedback(audit_result: dict) -> str | None:
    if not audit_result.get("fired"):
        return None
    details = []
    for item in audit_result.get("violations", [])[:4]:
        if "detail" in item:
            details.append(f"{item.get('rule')}: {item['detail']}")
        else:
            details.append(
                f"{item.get('rule')}: lhs={item.get('lhs')}, rhs={item.get('rhs')}, "
                f"delta={item.get('delta')}, source={item.get('source')}")
    return ("Independent semantic checks found concrete violations:\n"
            + "\n".join(details)
            + "\nFix the actual modeling error while preserving the exact solution.json "
              "variable schema. Rewrite the COMPLETE executable Python script. "
              "Do not simply suppress the checker or delete the violated business requirement.")


def execution_guidance(feedback: str | None, record: dict) -> str | None:
    text = feedback or ""
    error = (record.get("stderr_tail") or "").lower()
    if "unrecognized optimization sense: max" in error:
        text += ('\nPySCIPOpt exact API fix: use "maximize" instead of "max" '
                 'for the optimization sense. Do not repeat "max".')
    if "unrecognized optimization sense: min" in error:
        text += ('\nPySCIPOpt exact API fix: use "minimize" instead of "min" '
                 'for the optimization sense. Do not repeat "min".')
    return text


def repair_prompt(question: str, schema: str) -> str:
    return SCIP_CONTRACT + question + ("\n\n[WITNESS OUTPUT SCHEMA]\n"
            "When writing solution.json, use these exact variable names in the `variables` "
            "object, even if your internal solver variables use different names: " + schema)


def validate_witness(witness: dict, question: str, gate_cells: list[dict],
                     problem_dir: Path, fallback_dir: Path | None) -> None:
    if witness.get("gate") is not None:
        return
    gate_result = gate(witness.get("spec"), question, gate_cells, problem_dir.parent.name)
    witness["gate"] = gate_result
    if gate_result["accepted"]:
        return
    fallback_path = (fallback_dir / problem_dir.parent.name / "spec.json"
                     if fallback_dir is not None else None)
    if fallback_path is not None and fallback_path.exists():
        fallback = json.loads(fallback_path.read_text())
        fallback_gate = gate(fallback, question, gate_cells, problem_dir.parent.name)
        witness["fallback_gate"] = fallback_gate
        if fallback_gate["accepted"]:
            witness["spec"] = fallback
            witness["gate_fallback"] = True
        else:
            witness["spec"] = None
    else:
        witness["spec"] = None


def author_witness(arm: str, question: str, cells: list[dict], problem_dir: Path,
                   temperature: float, cfg, gate_cells: list[dict] | None = None,
                   fallback_dir: Path | None = None) -> dict:
    path = problem_dir / "author.json"
    if path.exists():
        witness = json.loads(path.read_text())
        witness["current_run_llm_calls"] = 0
        if arm == "scoped_ir" and gate_cells is not None and witness.get("gate") is None:
            validate_witness(witness, question, gate_cells, problem_dir, fallback_dir)
            (problem_dir / "spec.json").write_text(
                json.dumps(witness["spec"], ensure_ascii=False, indent=1) + "\n")
            path.write_text(json.dumps(witness, ensure_ascii=False, indent=1) + "\n")
        return witness
    if arm == "scoped_ir":
        prompt = SCOPED_IR_PROMPT.format(question=question,
                                         solution_schema=solution_schema_text(cells))
    else:
        prompt = build_prompt(arm, question, solution_schema_text(cells))
    t0 = time.time()
    try:
        resp = llm_mod.chat([{"role": "user", "content": prompt}],
                            max_tokens=32768, temperature=temperature,
                            extra={"reasoning_effort": "medium"}, config=cfg)
        text = resp.get("content") or ""
        error = None
    except Exception as exc:
        resp = {"usage": {}}
        text = ""
        error = f"{type(exc).__name__}: {exc}"
    witness = {"prompt": prompt, "response_text": text, "error": error,
               "usage": resp.get("usage"), "latency_s": round(time.time() - t0, 1),
               "current_run_llm_calls": 1}
    if arm == "scoped_ir":
        try:
            witness["spec"] = extract_spec(text)
        except Exception as exc:
            witness["spec"] = None
            witness["parse_error"] = str(exc)
        if gate_cells is not None:
            validate_witness(witness, question, gate_cells, problem_dir, fallback_dir)
        (problem_dir / "spec.json").write_text(
            json.dumps(witness["spec"], ensure_ascii=False, indent=1) + "\n")
    else:
        witness["script"] = extract_code(text)
        (problem_dir / "witness.py").write_text(witness["script"])
    path.write_text(json.dumps(witness, ensure_ascii=False, indent=1) + "\n")
    return witness


def load_initial(problem_id: str, baseline_path: Path,
                 initial_dir: str | None = None) -> dict:
    records = [json.loads(line) for line in baseline_path.read_text().splitlines()
               if line.strip() and json.loads(line)["id"] == problem_id]
    if not records:
        raise FileNotFoundError(f"missing initial candidate: {problem_id}")
    record = max(records, key=lambda r: r["round"])
    sandbox = (ROOT / initial_dir if initial_dir else
               ROOT / "runs/industryor/sandbox"
               / f"z0_scoped_e2e__{problem_id}__r{record['round']}")
    code = (sandbox / "gen.py").read_text()
    solution_path = sandbox / "solution.json"
    solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
    return {"record": record, "code": code, "solution": solution,
            "sandbox": sandbox}


def run_arm(problem_id: str, arm: str, question: str, cells: list[dict],
            initial: dict, initial_score: dict, reference: dict,
            outdir: Path, max_repairs: int, temperature: float, cfg,
            gate_cells: list[dict] | None = None, fallback_dir: Path | None = None,
            progress_controller: bool = False) -> dict:
    problem_dir = outdir / problem_id / arm
    problem_dir.mkdir(parents=True, exist_ok=True)
    final_path = problem_dir / "final.json"
    if final_path.exists():
        return json.loads(final_path.read_text())
    witness = author_witness(arm, question, cells, problem_dir, temperature, cfg,
                             gate_cells, fallback_dir)
    current = {"code": initial["code"], "solution": initial["solution"],
               "record": initial["record"]}
    accepted = None
    accepted_round = None
    history = []
    repair_calls = 0
    controller_transforms = 0
    controller = ProgressController() if progress_controller else None
    stop_reason = None
    usage = {"prompt_tokens": (witness.get("usage") or {}).get("prompt_tokens", 0) or 0,
             "completion_tokens": (witness.get("usage") or {}).get("completion_tokens", 0) or 0,
             "total_tokens": 0}
    repair_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    latency = witness.get("latency_s") or 0.0
    for round_idx in range(max_repairs + 1):
        audit_result = audit(arm, witness, current["solution"], question, cells, problem_id)
        history.append({"round": round_idx, "audit": audit_result,
                        "code_sha256": hashlib.sha256(current["code"].encode()).hexdigest(),
                        "execution": current["record"]})
        checker_status = checker_state(arm, witness)
        history[-1]["checker_status"] = checker_status
        if can_accept(audit_result, checker_status):
            accepted = current
            accepted_round = round_idx
        decision = None
        action = "local_patch"
        if controller is not None:
            decision = controller.decide(current["code"], current["record"], audit_result,
                                         max_repairs - round_idx, checker_status)
            action = decision.action
            history[-1]["controller_decision"] = decision.__dict__
            if action == "stop":
                stop_reason = decision.reason
                break
            if action in {"repair_checker", "acquire_evidence"}:
                stop_reason = action + "_required"
                break
        if accepted is not None:
            stop_reason = "accepted"
            break
        if checker_status == "rejected":
            stop_reason = "repair_checker_required"
            break
        if checker_status != "accepted" and current["solution"] is not None:
            stop_reason = "checker_validation_required"
            break
        if round_idx >= max_repairs:
            stop_reason = "budget_exhausted"
            break
        sandbox = problem_dir / f"round_{round_idx + 1}"
        if action == "specialized_api_repair":
            sense = scip_sense_error(current["record"])
            try:
                code = repair_scip_sense(current["code"], sense)
            except (SyntaxError, ValueError) as exc:
                history[-1]["repair_error"] = str(exc)
                stop_reason = "specialized_api_repair_failed"
                break
            t0 = time.time()
            record = run_code(code, sandbox)
            latency += time.time() - t0
            record.update({"llm_error": None, "usage": {},
                           "finish_reason": "deterministic", "controller_action": action})
            controller_transforms += 1
        else:
            feedback = semantic_feedback(audit_result)
            if feedback is None:
                if current["solution"] is None:
                    feedback = ("The previous script did not produce a readable solution.json. "
                                "Follow the output contract exactly and write all required variables "
                                "and objective using the supplied schema. Rewrite the COMPLETE script.")
                else:
                    feedback = feedback_msg(current["record"])
            feedback = execution_guidance(feedback, current["record"])
            if feedback is None:
                stop_reason = "no_feedback"
                break
            if action == "regenerate":
                feedback = ("The previous local repair left the same failure signature. "
                            "Generate a different COMPLETE model instead of repeating that edit.\n"
                            + feedback)
            prompt = repair_prompt(question, ", ".join(sorted(reference["solution"]["variables"])))
            messages = [{"role": "user", "content": prompt},
                        {"role": "assistant", "content": current["code"]},
                        {"role": "user", "content": feedback}]
            (problem_dir / f"repair_{round_idx + 1}_prompt.txt").write_text(
                prompt + "\n\n[PREVIOUS CODE]\n" + current["code"]
                + "\n\n[FEEDBACK]\n" + feedback)
            t0 = time.time()
            try:
                resp = llm_mod.chat(messages, max_tokens=32768, temperature=temperature,
                                    extra={"reasoning_effort": "medium"}, config=cfg)
                text = resp.get("content") or ""
                error = None
            except Exception as exc:
                resp = {"usage": {}}
                text = ""
                error = f"{type(exc).__name__}: {exc}"
            repair_calls += 1
            latency += time.time() - t0
            for key in ("prompt_tokens", "completion_tokens"):
                tokens = (resp.get("usage") or {}).get(key, 0) or 0
                usage[key] += tokens
                repair_usage[key] += tokens
            code = extract_code(text)
            if controller is not None and code == current["code"]:
                sandbox.mkdir(parents=True, exist_ok=True)
                (sandbox / "gen.py").write_text(code)
                record = dict(current["record"])
                record["skipped_identical_code"] = True
            else:
                record = run_code(code, sandbox)
            record.update({"llm_error": error, "usage": resp.get("usage"),
                           "finish_reason": resp.get("finish_reason"),
                           "controller_action": action})
            (problem_dir / f"repair_{round_idx + 1}_response.txt").write_text(text)
            if controller is not None:
                controller_transforms += 1
        solution_path = sandbox / "solution.json"
        solution = (current["solution"] if record.get("skipped_identical_code")
                    else json.loads(solution_path.read_text()) if solution_path.exists() else None)
        if controller is not None:
            controller.record(decision, code)
        current = {"code": code, "solution": solution, "record": record}
    baseline_fallback = accepted is None and initial["solution"] is not None
    final = accepted or (initial if baseline_fallback else current)
    final_score = score_nlp4lp(reference, final["solution"])
    last_candidate_score = score_nlp4lp(reference, current["solution"])
    usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    repair_usage["total_tokens"] = repair_usage["prompt_tokens"] + repair_usage["completion_tokens"]
    result = {"id": problem_id, "arm": arm, "initial_score": initial_score,
              "final_score": final_score, "last_candidate_score": last_candidate_score,
              "accepted_round": accepted_round,
              "history": history, "repair_calls": repair_calls,
              "llm_calls_this_run": repair_calls + witness.get("current_run_llm_calls", 0),
              "authoring_usage": witness.get("usage"), "usage": usage,
              "repair_usage": repair_usage, "latency_s": round(latency, 1),
              "controller_enabled": controller is not None,
              "controller_transforms": controller_transforms,
              "controller_no_progress": controller.no_progress_count if controller else None,
              "controller_trace": controller.trace() if controller else [],
              "stop_reason": stop_reason, "baseline_fallback": baseline_fallback,
              "semantic_recovery": bool(history and history[0]["audit"].get("fired")
                                        and accepted_round not in (None, 0)
                                        and final_score["business_correct"]
                                        and not initial_score["business_correct"]),
              "accepted_but_business_incorrect": bool(accepted_round is not None
                                                       and not final_score["business_correct"]),
              "final_status": ("accepted" if accepted is not None else
                               "baseline_fallback" if baseline_fallback else "unverified"),
              "improved": (not initial_score["business_correct"]
                           and final_score["business_correct"]),
              "harmed_win": (initial_score["business_correct"]
                             and not final_score["business_correct"]),
              "initial_code": initial["code"], "final_code": final["code"]}
    final_path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    print(f"[{problem_id}][{arm}] final={final_score['business_correct']} "
          f"accepted_round={accepted_round} repairs={repair_calls} "
          f"improved={result['improved']} harmed={result['harmed_win']}", flush=True)
    return result


def analyze(outdir: Path) -> dict:
    results = []
    for path in sorted(outdir.glob("*/*/final.json")):
        results.append(json.loads(path.read_text()))
    arms = {}
    for arm in ARMS:
        rows = [r for r in results if r["arm"] == arm]
        arms[arm] = {
            "n": len(rows),
            "initial_business_correct": sum(r["initial_score"]["business_correct"] for r in rows),
            "final_business_correct": sum(r["final_score"]["business_correct"] for r in rows),
            "improved": sum(r["improved"] for r in rows),
            "harmed_win": sum(r["harmed_win"] for r in rows),
            "semantic_recoveries": sum(bool(
                r.get("history") and r["history"][0]["audit"].get("fired")
                and r.get("accepted_round") not in (None, 0)
                and r["final_score"]["business_correct"]
                and not r["initial_score"]["business_correct"]) for r in rows),
            "accepted_but_business_incorrect": sum(
                r.get("accepted_round") is not None
                and not r["final_score"]["business_correct"] for r in rows),
            "accepted": sum(r["final_status"] == "accepted" for r in rows),
            "repair_calls": sum(r["repair_calls"] for r in rows),
            "tokens": sum(r["usage"]["total_tokens"] for r in rows),
            "latency_s": round(sum(r["latency_s"] for r in rows), 1),
        }
    result = {"arms": arms, "results": results}
    (outdir / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="runs/industryor/m3_z0_scoped_e2e_s0.jsonl")
    ap.add_argument("--initial-dir")
    ap.add_argument("--gate-artifacts")
    ap.add_argument("--fallback-dir")
    ap.add_argument("--out", default="work/scoped_ir_e2e")
    ap.add_argument("--ids", nargs="*", default=list(IDS))
    ap.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    ap.add_argument("--max-repairs", type=int, default=2)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--progress-controller", action="store_true")
    ap.add_argument("--analyze", action="store_true")
    args = ap.parse_args()
    outdir = ROOT / args.out
    references = {row["id"]: row for row in normalized_rows() if row["id"] in args.ids}
    if args.analyze:
        print(json.dumps(analyze(outdir)["arms"], indent=1))
        return
    cfg = llm_mod.load_config()
    gate_artifacts = ROOT / args.gate_artifacts if args.gate_artifacts else None
    fallback_dir = (ROOT / args.fallback_dir if args.fallback_dir else
                    ROOT / "work/scoped_ir_e2e_demo_v0.4" if args.gate_artifacts else None)
    tasks = []
    for pid in args.ids:
        reference = references[pid]
        question = reference["description"]
        initial = load_initial(pid, ROOT / args.baseline, args.initial_dir)
        initial_score = score_nlp4lp(reference, initial["solution"])
        cells = [{"key": "schema", "wrong": False, "mutation": "schema",
                  "reference_violations": [],
                  "solution": {"variables": {name: 0.0 for name in
                                            reference["solution"]["variables"]},
                               "objective": 0.0}}]
        gate_cells = (load_cells(gate_artifacts / "cells.jsonl", [pid])[pid]
                      if gate_artifacts is not None else None)
        for arm in args.arms:
            tasks.append((pid, arm, question, cells, initial, initial_score, reference,
                          gate_cells, fallback_dir))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_arm, pid, arm, question, cells, initial,
                               initial_score, reference, outdir,
                               args.max_repairs, args.temperature, cfg,
                               gate_cells, fallback_dir, args.progress_controller)
                   for pid, arm, question, cells, initial, initial_score, reference,
                   gate_cells, fallback_dir in tasks]
        for future in futures:
            future.result()
    print(json.dumps(analyze(outdir)["arms"], indent=1))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Compare shared-first k=1 and k=3 formulation candidates without answer selection."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod
from ora_agent.semantic_binding import propose_binding, reconcile_binding
from scripts.industryor_next_stage import instrument_code, score_solution
from scripts.m1_pilot import extract_code, run_code
from scripts.m3_industryor import SCIP_CONTRACT, load_priors

DATA = ROOT / "data/industryor/IndustryOR.json"
AUDIT_IDS = (4, 8, 9, 19, 20, 21, 25, 48)
PROTOCOL = ROOT / "docs/paper/industryor_k3_protocol_v0.1.md"
CANDIDATE_IDS = ("A", "B", "C")
DIMENSIONS = ("variables", "parameters", "constraints", "objective")
IMPLEMENTATION = ("scripts/industryor_k3_pipeline.py", "ora_agent/semantic_binding.py",
                  "scripts/industryor_next_stage.py", "scripts/m1_pilot.py", "ora_agent/llm.py",
                  "scripts/m3_industryor.py")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def call_llm(messages: list[dict], path: Path, config, temperature: float, max_tokens: int) -> dict:
    if path.exists():
        record = json.loads(path.read_text())
        if record["messages"] != messages or record["request"] != {
                "temperature": temperature, "max_tokens": max_tokens, "reasoning_effort": "medium"}:
            raise ValueError("cached generation has a different request")
        record["new_llm_calls"] = 0
        record["reused"] = True
        return record
    request = {"temperature": temperature, "max_tokens": max_tokens, "reasoning_effort": "medium"}
    try:
        response = llm_mod.chat(messages, max_tokens=max_tokens, temperature=temperature,
                                extra={"reasoning_effort": "medium"}, config=config)
        if response.get("model") != config.model:
            raise ValueError(f"returned model differs from requested model: {response.get('model')}")
        record = {"messages": messages, "request": request, "response": response,
                  "new_llm_calls": 1, "reused": False}
    except Exception as exc:
        record = {"messages": messages, "request": request,
                  "response": {"request_attempts": getattr(exc, "request_attempts", [])},
                  "error": f"{type(exc).__name__}: {exc}", "new_llm_calls": 1, "reused": False}
    write_json(path, record)
    return record


def business_score(problem_id: int, solution: dict | None) -> dict | None:
    if problem_id not in AUDIT_IDS or not isinstance(solution, dict) or solution.get("solution_count", 0) < 1:
        return None
    return score_solution(problem_id, solution)


def execute_candidate(problem_id: int, code: str, case: Path, config) -> tuple[dict, dict]:
    gate = reconcile_binding(problem_id, code, {}) if problem_id in AUDIT_IDS else {
        "status": "ready", "aliases": {}, "repair_aliases": {}, "business_correct": False}
    binding_record = None
    if problem_id in AUDIT_IDS and gate["status"] != "ready":
        binding_record = propose_binding(problem_id, question_for(problem_id), code, None,
                                         case / "binding.json", config)
        gate = binding_record["gate"]
    write_json(case / "binding_gate.json", gate)
    aliases = gate.get("aliases") or {}
    execution_path = case / "execution.json"
    aliases_hash = digest(json.dumps(aliases, sort_keys=True))
    if execution_path.exists():
        record = json.loads(execution_path.read_text())
        if record.get("code_sha256") != digest(code) or record.get("aliases_sha256") != aliases_hash:
            raise ValueError("cached execution has different code or aliases")
        record["reused_execution"] = True
    else:
        try:
            instrumented = instrument_code(code, aliases)
            export_error = None
        except (ValueError, TypeError, SyntaxError) as exc:
            try:
                instrumented = instrument_code(code)
                export_error = f"alias export failed: {exc}; used identity export for diagnostics"
            except (ValueError, TypeError, SyntaxError) as inner:
                instrumented = code
                export_error = f"{type(inner).__name__}: {inner}"
        record = run_code(instrumented, case)
        record.update(code_sha256=digest(code), aliases_sha256=aliases_hash,
                      export_error=export_error, reused_execution=False)
        write_json(execution_path, record)
    solution_path = case / "solution.json"
    solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
    score = business_score(problem_id, solution)
    if score is not None:
        write_json(case / "score.json", score)
    return record, {"gate": gate, "solution": solution, "score": score,
                    "binding_record": binding_record}


def generate_candidate(problem_id: int, candidate_id: str, prompt: str, case: Path, config) -> dict:
    case.mkdir(parents=True, exist_ok=True)
    messages = [{"role": "user", "content": prompt}]
    generation = call_llm(messages, case / "generation.json", config, 0.6, 32768)
    if generation.get("error"):
        raise RuntimeError(generation["error"])
    code = extract_code(generation["response"].get("content") or "")
    (case / "code.py").write_text(code)
    record, audit = execute_candidate(problem_id, code, case, config)
    solution = audit["solution"]
    objective = solution.get("objective") if isinstance(solution, dict) else record.get("objective")
    score = audit["score"]
    accepted = bool(score and score.get("business_correct") and audit["gate"].get("status") == "ready")
    return {"candidate_id": candidate_id, "code": code, "record": record,
            "objective": objective if isinstance(objective, (int, float)) and math.isfinite(objective) else None,
            "solution": solution, "score": score, "gate": audit["gate"],
            "business_accepted": accepted, "generation_record": generation,
            "binding_record": audit["binding_record"]}


def selector_prompt(question: str, candidates: list[dict]) -> str:
    payload = []
    for candidate in candidates:
        score = candidate.get("score") or {}
        payload.append({"candidate_id": candidate["candidate_id"], "code": candidate["code"],
                        "execution": {key: candidate["record"].get(key) for key in
                                      ("exec_status", "solver_status", "export_error")},
                        "business_audit": None if score is None else {
                            "audit_status": score.get("audit_status"),
                            "violations": score.get("violations"),
                            "failed_constraints": [item for item in score.get("constraint_checks", [])
                                                   if not item.get("passed")]}})
    return ("Select one optimization formulation using max-min confidence. Do not use or guess a reference "
            "objective. Judge variables, parameters, constraints and objective semantics from the question, "
            "candidate code and execution evidence. Return ONLY JSON with selected (A/B/C), scores, and rationale. "
            "Each scores entry must contain variables, parameters, constraints and objective as numbers 0-100.\n\n"
            f"[QUESTION]\n{question}\n\n[CANDIDATES]\n{json.dumps(payload, ensure_ascii=False)}")


def choose_with_llm(problem_id: int, question: str, candidates: list[dict], case: Path, config) -> tuple[dict, dict]:
    prompt = selector_prompt(question, candidates)
    record = call_llm([{"role": "user", "content": prompt}], case / "selection.json", config, 0.2, 16384)
    if record.get("error"):
        return candidates[0], {"method": "fallback_A_after_llm_error", "record": record}
    try:
        text = record["response"].get("content") or ""
        value = json.loads(text[text.find("{"):text.rfind("}") + 1])
        scores = value["scores"]
        min_confidence = {}
        for candidate in candidates:
            candidate_scores = scores[candidate["candidate_id"]]
            values = []
            for dimension in DIMENSIONS:
                score = candidate_scores[dimension]
                if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) \
                        or not 0 <= score <= 100:
                    raise ValueError("invalid confidence value")
                values.append(float(score))
            min_confidence[candidate["candidate_id"]] = min(values)
        best = max(min_confidence.values())
        selected = next(candidate for candidate in candidates if min_confidence[candidate["candidate_id"]] == best)
        raw = value.get("selected")
        return selected, {"method": "llm_max_min", "selected_raw": raw,
                          "selector_choice_mismatch": raw != selected["candidate_id"],
                          "min_confidence": min_confidence, "record": record}
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return candidates[0], {"method": "fallback_A_invalid_selector", "error": f"{type(exc).__name__}: {exc}",
                               "record": record}


def costs(records: list[dict]) -> dict:
    records = [record for record in records if record]
    responses = [record.get("response") or {} for record in records]
    return {"logical_llm_calls": len(records), "new_llm_calls": sum(record["new_llm_calls"] for record in records),
            "api_attempts": sum(len(response.get("request_attempts") or [None]) for response in responses),
            "completion_tokens": sum((response.get("usage") or {}).get("completion_tokens", 0) or 0
                                     for response in responses),
            "total_tokens": sum((response.get("usage") or {}).get("total_tokens", 0) or 0 for response in responses),
            "llm_latency_s": round(sum((response.get("request_wall_s") or response.get("latency_s") or 0)
                                       for response in responses), 3),
            "new_llm_latency_s": round(sum((response.get("request_wall_s") or response.get("latency_s") or 0)
                                           for response, record in zip(responses, records) if record["new_llm_calls"]), 3)}


def candidate_costs(candidate: dict) -> list[dict]:
    return [candidate["generation_record"], candidate.get("binding_record")]


def run_problem(row: dict, outdir: Path, config: dict, resume: bool) -> dict:
    problem_id = row["id"]
    case = outdir / f"prob_{problem_id:03d}"
    case.mkdir(parents=True, exist_ok=True)
    result_path = case / "result.json"
    if resume and result_path.exists():
        previous = json.loads(result_path.read_text())
        if previous["run_config"] != config["public"]:
            raise ValueError("cached result has a different configuration")
        return previous
    prompt = load_priors() + "\n\n" + SCIP_CONTRACT + row["en_question"]
    (case / "prompt.txt").write_text(prompt)
    candidates = [generate_candidate(problem_id, candidate_id, prompt,
                                     case / f"candidate_{candidate_id}", config["llm_config"])
                  for candidate_id in CANDIDATE_IDS]
    first = candidates[0]
    accepted = [candidate for candidate in candidates if candidate["business_accepted"]]
    if accepted:
        selected = min(accepted, key=lambda candidate: (
            bool(candidate.get("binding_record")), candidate["candidate_id"]))
        selection = {"method": "independent_business", "record": None}
    else:
        selected, selection = choose_with_llm(problem_id, row["en_question"], candidates, case, config["llm_config"])
    reference = float(row["en_answer"])
    scored_candidates = [candidate for candidate in candidates if candidate["objective"] is not None]
    oracle = min(scored_candidates, key=lambda candidate: abs(candidate["objective"] - reference)) if scored_candidates else None
    selected_objective = selected["objective"]
    result = {"id": problem_id, "run_config": config["public"], "status": "completed",
              "reference": reference, "k1_candidate": first["candidate_id"],
              "k1_objective": first["objective"],
              "k1_match": first["objective"] is not None and abs(first["objective"] - reference) <= 0.1,
              "k1_business_correct": first["business_accepted"],
              "selected_candidate": selected["candidate_id"], "selected_objective": selected_objective,
              "selected_match": selected_objective is not None and abs(selected_objective - reference) <= 0.1,
              "selected_business_correct": selected["business_accepted"], "selection": selection,
              "oracle_candidate": oracle["candidate_id"] if oracle else None,
              "oracle_objective": oracle["objective"] if oracle else None,
              "oracle_match": bool(oracle and abs(oracle["objective"] - reference) <= 0.1),
              "pool_business_correct": any(candidate["business_accepted"] for candidate in candidates),
              "business_unverified": problem_id not in AUDIT_IDS,
              "candidates": [{key: value for key, value in candidate.items()
                              if key not in {"generation_record", "binding_record", "solution"}} for candidate in candidates],
              "cost_a": costs(candidate_costs(first)),
              "cost_all": costs([record for candidate in candidates for record in candidate_costs(candidate)]
                                + ([selection["record"]] if selection["record"] else [])),
              "public_answer_used_for_selection": False, "oracle_not_deployable": True}
    result["selection_missed_pool"] = bool(result["oracle_match"] and not result["selected_match"])
    write_json(result_path, result)
    (case / "error.json").unlink(missing_ok=True)
    return result


def safe_problem(row: dict, outdir: Path, config: dict, resume: bool) -> dict:
    try:
        return run_problem(row, outdir, config, resume)
    except Exception as exc:
        case = outdir / f"prob_{row['id']:03d}"
        records = []
        for path in sorted(case.glob("candidate_*/generation.json")) + sorted(case.glob("candidate_*/binding.json")):
            records.append(json.loads(path.read_text()))
        selection_path = case / "selection.json"
        if selection_path.exists():
            records.append(json.loads(selection_path.read_text()))
        result = {"id": row["id"], "run_config": config["public"], "status": "runner_error",
                  "error": f"{type(exc).__name__}: {exc}", "reference": float(row["en_answer"]),
                  "k1_match": False, "selected_match": False, "oracle_match": False,
                  "k1_business_correct": False, "selected_business_correct": False,
                  "pool_business_correct": False, "business_unverified": row["id"] not in AUDIT_IDS,
                  "cost_a": costs(records[:1]), "cost_all": costs(records),
                  "public_answer_used_for_selection": False, "oracle_not_deployable": True}
        write_json(case / "error.json", result)
        return result


def question_for(problem_id: int) -> str:
    return next(row["en_question"] for row in json.loads(DATA.read_text()) if row["id"] == problem_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", type=int, nargs="*")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", default="work/industryor_k3_dev_v0.1")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    rows = json.loads(DATA.read_text())
    if len(rows) != 100:
        raise ValueError("IndustryOR must contain 100 problems")
    if args.ids:
        rows = [row for row in rows if row["id"] in set(args.ids)]
    if not rows:
        raise ValueError("no problems selected")
    outdir = ROOT / args.out
    if outdir.exists() and any(outdir.iterdir()) and not args.resume:
        raise ValueError("nonempty output directory; use --resume or a new directory")
    outdir.mkdir(parents=True, exist_ok=True)
    llm_config = llm_mod.load_config()
    public = {"ids": [row["id"] for row in rows], "model": llm_config.model,
              "base_url": llm_config.base_url, "temperature": 0.6, "reasoning_effort": "medium",
              "max_tokens": 32768, "candidate_ids": list(CANDIDATE_IDS),
              "exposure": "development_new_samples_not_heldout", "repair": False, "memory": False,
              "dataset_sha256": hashlib.sha256(DATA.read_bytes()).hexdigest(),
              "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
              "implementation_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                        for name in IMPLEMENTATION}}
    config = {"llm_config": llm_config, "public": public}
    write_json(outdir / "run_config.json", public)
    for name in (*IMPLEMENTATION, "docs/paper/industryor_k3_protocol_v0.1.md"):
        destination = outdir / "source" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda row: safe_problem(row, outdir, config, args.resume), rows))
    results.sort(key=lambda row: row["id"])
    total_cost = {key: sum(row["cost_all"][key] for row in results)
                  for key in ("logical_llm_calls", "new_llm_calls", "api_attempts",
                              "completion_tokens", "total_tokens", "llm_latency_s", "new_llm_latency_s")}
    summary = {"n": len(results), "runner_errors": sum(row["status"] == "runner_error" for row in results),
               "k1_matches": sum(row["k1_match"] for row in results),
               "k3_selected_matches": sum(row["selected_match"] for row in results),
               "k3_oracle_matches_not_deployable": sum(row["oracle_match"] for row in results),
               "selection_missed_pool": sum(row.get("selection_missed_pool", False) for row in results),
               "k1_business_correct": sum(row["k1_business_correct"] for row in results),
               "k3_selected_business_correct": sum(row["selected_business_correct"] for row in results),
               "k3_pool_business_correct": sum(row["pool_business_correct"] for row in results),
               "business_unverified": sum(row["business_unverified"] for row in results),
               "selector_fallbacks": sum((row.get("selection") or {}).get("method", "").startswith("fallback")
                                          for row in results),
               "selector_choice_mismatches": sum((row.get("selection") or {}).get("selector_choice_mismatch", False)
                                                 for row in results),
               "cost_k1": {key: sum(row["cost_a"][key] for row in results) for key in total_cost},
               "cost_k3": total_cost, "wall_seconds": round(time.monotonic() - started, 3)}
    write_json(outdir / "analysis.json", {"run_config": public, "summary": summary, "results": results})
    manifest = {"schema_version": "industryor.k3.manifest.v0.1", "run_config": public,
                "registered_n": len(rows), "accounted_n": len(results),
                "candidate_generation_files": len(list(outdir.glob("prob_*/candidate_*/generation.json"))),
                "selector_files": len(list(outdir.glob("prob_*/selection.json"))),
                "public_answer_used_for_selection": False, "oracle_not_deployable": True,
                "results": [{"id": row["id"], "status": row["status"],
                             "path": f"prob_{row['id']:03d}/{'result.json' if row['status'] == 'completed' else 'error.json'}"}
                            for row in results]}
    write_json(outdir / "manifest.json", manifest)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

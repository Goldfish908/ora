#!/usr/bin/env python3
"""Replay fixed IndustryOR candidates through LLM-proposed semantic bindings."""
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
from ora_agent.semantic_binding import propose_binding
from scripts.industryor_next_stage import instrument_code, score_solution
from scripts.m1_pilot import run_code

SOURCE = ROOT / "work/industryor_full_qwen_v0.1"
DATA = ROOT / "data/industryor/IndustryOR.json"
PROTOCOL = ROOT / "docs/paper/industryor_semantic_inner_protocol_v0.1.md"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def business_score(problem_id: int, solution: dict | None) -> dict | None:
    if not isinstance(solution, dict) or solution.get("solution_count", 0) < 1:
        return None
    return score_solution(problem_id, solution)


def run_one(row: dict, outdir: Path, config: dict, resume: bool) -> dict:
    problem_id = row["id"]
    case = outdir / f"prob_{problem_id:03d}"
    case.mkdir(parents=True, exist_ok=True)
    result_path = case / "result.json"
    if resume and result_path.exists():
        previous = json.loads(result_path.read_text())
        if previous["run_config"] != config["public"]:
            raise ValueError("cached result has a different configuration")
        return previous
    source_result_path = SOURCE / f"prob_{problem_id:03d}/result.json"
    source_result = json.loads(source_result_path.read_text())
    code = source_result["initial_code"]
    (case / "initial.py").write_text(code)
    initial_solution_path = SOURCE / f"prob_{problem_id:03d}/round_0/solution.json"
    initial_solution = json.loads(initial_solution_path.read_text()) if initial_solution_path.exists() else None
    binding = propose_binding(problem_id, row["en_question"], code, initial_solution,
                              case / "binding.json", config["llm_config"])
    gate = binding["gate"]
    response = binding.get("response") or {}
    result = {
        "id": problem_id, "run_config": config["public"], "binding_status": gate["status"],
        "binding_gate": gate, "initial_score": business_score(problem_id, initial_solution),
        "rebound_score": None, "initial_objective": (initial_solution or {}).get("objective"),
        "rebound_objective": None, "reference": float(row["en_answer"]),
        "new_llm_calls": binding["new_llm_calls"], "binding_reused": binding["reused"],
        "api_attempts": binding.get("api_attempts", 0), "usage": response.get("usage") or {},
        "llm_latency_s": response.get("request_wall_s") or response.get("latency_s") or 0,
        "source_initial_code_sha256": hashlib.sha256(code.encode()).hexdigest(),
        "source_result_sha256": hashlib.sha256(source_result_path.read_bytes()).hexdigest(),
        "code_semantics_changed": False, "business_accepted": False,
    }
    if gate.get("accepted_for_execution"):
        record = run_code(instrument_code(code, gate["aliases"]), case / "rebound")
        solution_path = case / "rebound/solution.json"
        solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
        rebound_score = business_score(problem_id, solution)
        result.update(rebound_score=rebound_score, execution=record,
                      rebound_objective=(solution or {}).get("objective"),
                      business_accepted=bool(rebound_score and rebound_score["business_correct"]))
        if solution is not None:
            write_json(case / "rebound_solution.json", solution)
        if rebound_score is not None:
            write_json(case / "rebound_score.json", rebound_score)
    result["objective_unchanged"] = (
        result["rebound_objective"] is not None and result["initial_objective"] is not None
        and abs(result["rebound_objective"] - result["initial_objective"]) <= 1e-7)
    result["objective_match_abs_0_1"] = (
        result["rebound_objective"] is not None
        and abs(result["rebound_objective"] - result["reference"]) <= 0.1)
    result["status"] = "completed"
    write_json(result_path, result)
    (case / "error.json").unlink(missing_ok=True)
    return result


def safe_one(row: dict, outdir: Path, config: dict, resume: bool) -> dict:
    try:
        return run_one(row, outdir, config, resume)
    except Exception as exc:
        problem_id = row["id"]
        case = outdir / f"prob_{problem_id:03d}"
        binding_path = case / "binding.json"
        binding = json.loads(binding_path.read_text()) if binding_path.exists() else {}
        response = binding.get("response") or {}
        result = {"id": problem_id, "run_config": config["public"], "status": "runner_error",
                  "error": f"{type(exc).__name__}: {exc}", "business_accepted": False,
                  "objective_match_abs_0_1": False, "initial_score": None, "rebound_score": None,
                  "binding_gate": binding.get("gate"), "new_llm_calls": binding.get("new_llm_calls", 0),
                  "binding_reused": binding.get("reused", False),
                  "api_attempts": binding.get("api_attempts", 0), "usage": response.get("usage") or {},
                  "llm_latency_s": response.get("request_wall_s") or response.get("latency_s") or 0}
        write_json(case / "error.json", result)
        return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", type=int, nargs="+", default=[4, 8, 20])
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--out", default="work/industryor_semantic_inner_dev_v0.1")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    rows = [row for row in json.loads(DATA.read_text()) if row["id"] in set(args.ids)]
    if len(rows) != len(set(args.ids)):
        raise ValueError("not all requested IDs are registered")
    outdir = ROOT / args.out
    if outdir.exists() and any(outdir.iterdir()) and not args.resume:
        raise ValueError("nonempty output directory; use --resume or a new directory")
    outdir.mkdir(parents=True, exist_ok=True)
    llm_config = llm_mod.load_config()
    public = {"ids": [row["id"] for row in rows], "model": llm_config.model,
              "base_url": llm_config.base_url, "exposure": "development_replay_not_heldout",
              "binding_temperature": 0.2, "reasoning_effort": "medium", "max_tokens": 32768,
              "source_analysis_sha256": hashlib.sha256((SOURCE / "analysis.json").read_bytes()).hexdigest(),
              "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
              "implementation_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                        for name in ("scripts/industryor_binding_pilot.py",
                                                     "ora_agent/semantic_binding.py",
                                                     "scripts/industryor_next_stage.py",
                                                     "scripts/m1_pilot.py", "ora_agent/llm.py")}}
    config = {"llm_config": llm_config, "public": public}
    write_json(outdir / "run_config.json", public)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda row: safe_one(row, outdir, config, args.resume), rows))
    results.sort(key=lambda row: row["id"])
    summary = {
        "n": len(results), "runner_errors": sum(row["status"] == "runner_error" for row in results),
        "binding_ready": sum(row.get("binding_status") == "ready" for row in results),
        "initial_business_correct": sum((row.get("initial_score") or {}).get("business_correct", False)
                                        for row in results),
        "rebound_business_correct": sum(row["business_accepted"] for row in results),
        "objective_unchanged": sum(row.get("objective_unchanged", False) for row in results),
        "objective_matches_abs_0_1": sum(row["objective_match_abs_0_1"] for row in results),
        "new_llm_calls": sum(row["new_llm_calls"] for row in results),
        "api_attempts": sum(row["api_attempts"] for row in results),
        "completion_tokens": sum((row["usage"].get("completion_tokens") or 0) for row in results),
        "total_tokens": sum((row["usage"].get("total_tokens") or 0) for row in results),
        "llm_latency_s": round(sum(row["llm_latency_s"] for row in results), 3),
        "wall_seconds": round(time.monotonic() - started, 3),
        "scope": "development replay; binding coverage is not proof of model semantic repair",
    }
    write_json(outdir / "analysis.json", {"run_config": public, "summary": summary, "results": results})
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

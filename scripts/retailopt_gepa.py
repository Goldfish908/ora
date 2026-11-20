#!/usr/bin/env python3
"""Official GEPA on RetailOpt with proxy-only feedback and independent witness logging."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/home/hewj13/wm/ext/gepa/src")

import gepa
from gepa.core.adapter import EvaluationBatch

from ora_agent import llm as llm_mod
from ora_agent.verification_governance import CheckAsset, LayeredAcceptance, verbatim_source
from scripts.m1_pilot import SCHEMA_PRELUDE, SCIP_OUTPUT_FORMAT_SOL, adapt_prompt_schema, extract_code
from scripts.retailopt_governance import build_governor, demand_balance_eval, trusted_cases

RL_PYTHON = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"
GEPA_COMMIT = "ce5b0d6e3d6af6c6dbec6de2c54536bbb961d309"
PROTOCOL = ROOT / "docs/paper/verification_amplification_protocol_v0.1.md"
DEV = ROOT / "data/m1_retailopt/dev40_f1f4.jsonl"
GAP = ROOT / "data/m1_retailopt/gapcheck60_f1f4.jsonl"


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def summarize_records(records: list[dict], n_expected: int) -> dict:
    generation_errors = sum(record.get("generation_error") is not None for record in records)
    infrastructure_errors = sum(
        record.get("generation_error") is None
        and (record.get("exec_status") == "runner_error" or record.get("base_status") == "runner_error")
        for record in records)
    missing_records = n_expected - len(records)
    runner_errors = missing_records + generation_errors + infrastructure_errors
    truth_unknown = 0
    for record in records:
        if record.get("generation_error") is not None:
            truth_unknown += 1
            continue
        if "plus_status" in record:
            truth_unknown += record["plus_status"] in {"timeout", "runner_error"}
        elif "witness" in record:
            truth_unknown += record["witness"] not in {"feasible", "infeasible"}
    return {"n": n_expected, "records": len(records),
            "missing_records": missing_records,
            "generation_errors": generation_errors,
            "infrastructure_errors": infrastructure_errors,
            "runner_errors": runner_errors,
            "observed": n_expected - runner_errors,
            "evaluable": n_expected - runner_errors,
            "truth_unknown": truth_unknown + missing_records,
            "executable": sum(record["executable"] for record in records),
            "proxy_match": sum(record["proxy_match"] for record in records),
            "true_correct": sum(record["true_correct"] for record in records),
            "phantom": sum(record["phantom"] for record in records),
            "phantom_proxy": sum(record["phantom_proxy"] for record in records),
            "new_llm_calls": sum(record["new_llm_calls"] for record in records),
            "completion_tokens": sum(record["completion_tokens"] for record in records),
            "total_tokens": sum(record["total_tokens"] for record in records),
            "llm_latency_s": round(sum(record["llm_latency_s"] for record in records), 3)}


class RetailOptAdapter:
    propose_new_texts = None

    def __init__(self, outdir: Path, workers: int, run_seed: int,
                 governor=None, audit_manifest: dict | None = None, evolve_verification: bool = False):
        self.outdir = outdir
        self.workers = workers
        self.run_seed = run_seed
        self.governor = governor
        self.audit_manifest = audit_manifest
        self.evolve_verification = evolve_verification
        self.governance_lock = threading.Lock()
        self.config = llm_mod.load_config()

    def _maybe_evolve(self, row: dict, record: dict) -> None:
        if not self.evolve_verification or row.get("_split") != "dev":
            return
        with self.governance_lock:
            if "C-DEMAND" not in (record.get("witness_rules") or []) \
                    or "L2_demand_balance" in self.governor.checks:
                return
            source = verbatim_source("Demand fulfillment equation:", row["prompt_schema"])
            self.governor.register(CheckAsset("L2_demand_balance", 2, demand_balance_eval, source))
            self.governor.promote("L2_demand_balance", trusted_cases(self.audit_manifest, "demand"))
            write_json(self.outdir / "governor.json", self.governor.public_state())
            print("verification knowledge candidate evaluated: L2_demand_balance", flush=True)

    def _cached(self, path: Path, candidate_hash: str, scenario_id: str) -> dict | None:
        if not path.exists():
            return None
        record = json.loads(path.read_text())
        if record["candidate_sha256"] != candidate_hash or record["scenario_id"] != scenario_id:
            raise ValueError("rollout cache identity mismatch")
        if record.get("generation_error") is None:
            record["new_llm_calls"] = 0
            return record
        return None

    def _rollout(self, row: dict, candidate: dict[str, str]) -> dict:
        conventions = candidate["conventions"]
        candidate_hash = digest_text(conventions)
        scenario_id = row["scenario_id"]
        path = self.outdir / "rollouts" / candidate_hash / f"{scenario_id}.json"
        cached = self._cached(path, candidate_hash, scenario_id)
        if cached is not None:
            return cached
        prompt = conventions.strip() + "\n\n" + adapt_prompt_schema(row["prompt_schema"], SCIP_OUTPUT_FORMAT_SOL)
        messages = [{"role": "user", "content": prompt.strip()}]
        seed = self.run_seed ^ int(digest_text(prompt)[:8], 16)
        generation_path = path.parent / "generations" / f"{scenario_id}.json"
        started = time.monotonic()
        try:
            response = llm_mod.chat(messages, max_tokens=32768, temperature=0.6,
                                    extra={"reasoning_effort": "medium", "stream": True, "stream_options": {"include_usage": True}, "seed": seed}, config=self.config)
            if response.get("model") != self.config.model:
                raise ValueError("returned model differs from requested model")
            generation = {"messages": messages, "response": response,
                          "request": {"temperature": 0.6, "max_tokens": 32768,
                                      "reasoning_effort": "medium", "seed": seed,
                                      "stream": True, "stream_options": {"include_usage": True}},
                          "error": None}
        except Exception as exc:
            response = {"request_attempts": getattr(exc, "request_attempts", []), "usage": {}}
            generation = {"messages": messages, "response": response,
                          "error": f"{type(exc).__name__}: {exc}"}
        write_json(generation_path, generation)
        sandbox = path.parent / "sandbox" / scenario_id
        sandbox.mkdir(parents=True, exist_ok=True)
        code = extract_code(response.get("content") or "") if not generation["error"] else ""
        (sandbox / "gen.py").write_text(SCHEMA_PRELUDE + code)
        row_path = path.parent / "inputs" / f"{scenario_id}.json"
        write_json(row_path, row)
        worker = subprocess.run([RL_PYTHON, str(ROOT / "scripts/retailopt_rollout_worker.py"),
                                 "--row", str(row_path), "--sandbox", str(sandbox)],
                                cwd=ROOT, capture_output=True, text=True, timeout=700)
        rollout_path = sandbox / "rollout.json"
        if worker.returncode != 0 or not rollout_path.exists():
            record = {"scenario_id": scenario_id, "executable": False, "proxy_match": False,
                      "true_correct": False, "phantom": False, "phantom_proxy": False,
                      "exec_status": "runner_error", "solver_status": None, "objective": None,
                      "grade": "runner_error", "witness": "runner_error",
                      "check_verdicts": {"L1_execution": "fail", "L2_retail_witness": "unknown"},
                      "worker_stderr": worker.stderr[-1000:]}
        else:
            record = json.loads(rollout_path.read_text())
        usage = response.get("usage") or {}
        latency = response.get("request_wall_s") or response.get("latency_s") or 0
        record.update(candidate_sha256=candidate_hash, scenario_id=scenario_id, code=code,
                      problem=adapt_prompt_schema(row["prompt_schema"], SCIP_OUTPUT_FORMAT_SOL),
                      new_llm_calls=1, completion_tokens=usage.get("completion_tokens", 0) or 0,
                      total_tokens=usage.get("total_tokens", 0) or 0,
                      llm_latency_s=latency, wall_seconds=round(time.monotonic() - started, 3),
                      generation_error=generation["error"])
        record["proxy_score"] = float(record["proxy_match"])
        record["feedback"] = (f"Execution: {record.get('exec_status')}; solver: {record.get('solver_status')}; "
                              f"proxy objective match: {record['proxy_match']}. "
                              "Improve the formulation and code to increase the proxy objective-match score. "
                              "Do not assume that a printed objective alone proves semantic correctness.")
        write_json(path, record)
        self._maybe_evolve(row, record)
        print(f"[{scenario_id}][{candidate_hash[:8]}] exec={record.get('exec_status')} "
              f"proxy={record['proxy_match']} true={record['true_correct']} phantom={record['phantom']}", flush=True)
        return record

    def evaluate(self, batch: list[dict], candidate: dict[str, str], capture_traces: bool = False) -> EvaluationBatch:
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            records = list(pool.map(lambda row: self._rollout(row, candidate), batch))
        return EvaluationBatch(outputs=records, scores=[record["proxy_score"] for record in records],
                               trajectories=records if capture_traces else None)

    def make_reflective_dataset(self, candidate: dict[str, str], eval_batch: EvaluationBatch,
                                components_to_update: list[str]):
        component = components_to_update[0]
        rows = eval_batch.trajectories or []
        reflective = []
        for record in rows:
            reflective.append({"Inputs": {"scenario_id": record["scenario_id"],
                                          "problem": record["problem"]},
                               "Generated Outputs": record["code"],
                               "Feedback": record["feedback"]})
        return {component: reflective}


def analyze(result, valset: list[dict], outdir: Path) -> dict:
    candidates = result.candidates
    scenario_ids = [row["scenario_id"] for row in valset]
    curves = []
    for index, candidate in enumerate(candidates):
        candidate_hash = digest_text(candidate["conventions"])
        records = []
        for scenario_id in scenario_ids:
            path = outdir / "rollouts" / candidate_hash / f"{scenario_id.replace('/', '_')}.json"
            if path.exists():
                records.append(json.loads(path.read_text()))
        curves.append({"candidate_idx": index, "candidate_sha256": candidate_hash,
                       "parents": result.parents[index],
                       "discovery_eval_count": result.discovery_eval_counts[index],
                       "official_proxy_mean": result.val_aggregate_scores[index],
                       **summarize_records(records, len(scenario_ids))})
    return {"curves": curves, "n_candidates": len(candidates),
            "public_answer_used_for_reflection": False,
            "witness_used_for_reflection": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--train-limit", type=int, default=0)
    parser.add_argument("--val-limit", type=int, default=0)
    parser.add_argument("--max-metric-calls", type=int, default=240)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--llm-timeout", type=float, default=180)
    parser.add_argument("--rule-mode", choices=("none", "r1", "r2", "both"), default="none")
    parser.add_argument("--governance-cases", default="work/retailopt_governance_smoke_v0.2/cases.json")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    llm_mod.REQUEST_TIMEOUT_SEC = args.llm_timeout
    outdir = (ROOT / args.run_dir).resolve()
    if outdir.exists() and any(outdir.iterdir()) and not args.resume:
        raise ValueError("run directory is not empty; use --resume")
    outdir.mkdir(parents=True, exist_ok=True)
    trainset = read_jsonl(DEV)
    valset = read_jsonl(GAP)
    if args.train_limit:
        trainset = trainset[:args.train_limit]
    if args.val_limit:
        valset = valset[:args.val_limit]
    for row in trainset:
        row["_split"] = "dev"
    for row in valset:
        row["_split"] = "gapcheck"
    governor = None
    audit_manifest = None
    acceptance_criterion = "strict_improvement"
    if args.rule_mode != "none":
        audit_manifest = json.loads((ROOT / args.governance_cases).read_text())
        governor = build_governor(audit_manifest, include_demand=False)
        target_level = 1000000 if args.rule_mode == "r1" else 0
        acceptance_criterion = LayeredAcceptance(governor, target_level=target_level, require_final=True)
    adapter = RetailOptAdapter(outdir, args.workers, args.seed, governor=governor,
                               audit_manifest=audit_manifest,
                               evolve_verification=args.rule_mode in {"r1", "both"})
    reflection_dir = outdir / "reflection"
    reflection_count = 0

    def reflection_lm(prompt):
        nonlocal reflection_count
        reflection_count += 1
        response = llm_mod.chat([{"role": "user", "content": prompt}], max_tokens=8192,
                                temperature=0.6,
                                extra={"reasoning_effort": "medium", "stream": True, "stream_options": {"include_usage": True}, "seed": args.seed + 10000},
                                config=adapter.config)
        write_json(reflection_dir / f"call_{reflection_count:04d}.json",
                   {"messages": [{"role": "user", "content": prompt}], "response": response})
        return response.get("content") or ""

    started = time.monotonic()
    result = gepa.optimize(seed_candidate={"conventions": ""}, trainset=trainset, valset=valset,
                           adapter=adapter, reflection_lm=reflection_lm,
                           max_metric_calls=args.max_metric_calls, run_dir=str(outdir),
                           seed=args.seed, cache_evaluation=True, write_agent_state=True,
                           track_best_outputs=False, use_merge=False,
                           reflection_minibatch_size=3, skip_perfect_score=False,
                           acceptance_criterion=acceptance_criterion)
    write_json(outdir / "gepa_result.json", result.to_dict())
    if governor is not None:
        governor.freeze()
        write_json(outdir / "governor.json", governor.public_state())
    analysis = analyze(result, valset, outdir)
    analysis.update(model=adapter.config.model, official_gepa_commit=GEPA_COMMIT,
                    rule_mode=args.rule_mode,
                    protocol_sha256=digest_text(PROTOCOL.read_text()),
                    train_ids=[row["scenario_id"] for row in trainset],
                    val_ids=[row["scenario_id"] for row in valset],
                    wall_seconds=round(time.monotonic() - started, 3),
                    total_metric_calls=result.total_metric_calls)
    write_json(outdir / "analysis.json", analysis)
    write_json(outdir / "manifest.json", {"official_gepa_commit": GEPA_COMMIT,
                                          "protocol_sha256": digest_text(PROTOCOL.read_text()),
                                          "n_train": len(trainset), "n_val": len(valset),
                                          "rule_mode": args.rule_mode,
                                          "public_answer_used_for_reflection": False,
                                          "witness_used_for_reflection": False})
    print(json.dumps(analysis, ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    main()

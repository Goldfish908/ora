#!/usr/bin/env python3
"""Official GEPA on Text-to-SQL with original-DB proxy and official test-suite truth."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/home/hewj13/wm/ext/gepa/src")
sys.path.insert(0, "/home/hewj13/wm/ext/test-suite-sql-eval")

import gepa
from gepa.core.adapter import EvaluationBatch
import evaluate_classical
from evaluate_classical import judge
from exec_eval import exec_on_db, result_eq


def sync_exec_on_db(sqlite_path: str, query: str, timeout: int = 100):
    return asyncio.run(exec_on_db(sqlite_path, query, timeout=timeout))


evaluate_classical.exec_on_db = sync_exec_on_db

from ora_agent import llm as llm_mod
from scripts.m1_pilot import extract_code
from scripts.retailopt_gepa import analyze, digest_text, write_json

GEPA_COMMIT = "ce5b0d6e3d6af6c6dbec6de2c54536bbb961d309"
PROTOCOL = ROOT / "docs/paper/verification_amplification_protocol_v0.1.md"
SQL_ROOT = Path("/home/hewj13/wm/ext/test-suite-sql-eval")
SPLIT_SEED = "text2sql-gepa-v0.1"


def load_tasks() -> list[dict]:
    with (SQL_ROOT / "classical_test.pkl").open("rb") as handle:
        rows = pickle.load(handle)
    return [row for row in rows if row["db_id"] == "academic"]


def split_ids(rows: list[dict]) -> dict[str, list[int]]:
    ordered = sorted(range(len(rows)), key=lambda index: digest_text(f"{SPLIT_SEED}:{index}"))
    return {"dev": sorted(ordered[:40]), "gapcheck": sorted(ordered[40:100]), "test": sorted(ordered[100:200])}


class Text2SQLAdapter:
    propose_new_texts = None

    def __init__(self, outdir: Path, rows: list[dict], run_seed: int):
        self.outdir = outdir
        self.rows = rows
        self.run_seed = run_seed
        self.config = llm_mod.load_config()

    def _rollout(self, index: int, candidate: dict[str, str]) -> dict:
        row = self.rows[index]
        conventions = candidate["conventions"]
        candidate_hash = digest_text(conventions)
        task_id = f"academic_{index:04d}"
        path = self.outdir / "rollouts" / candidate_hash / f"{task_id}.json"
        if path.exists():
            record = json.loads(path.read_text())
            if record["candidate_sha256"] != candidate_hash or record["task_id"] != task_id:
                raise ValueError("cached SQL rollout identity mismatch")
            if record.get("generation_error") is None:
                record["new_llm_calls"] = 0
                return record
        prompt = (conventions.strip() + "\n\nYou are given a natural-language database question and its domain. "
                  "Return ONLY one valid SQLite query, without markdown or explanations.\n\n"
                  f"Domain: {row['db_id']}\nQuestion: {row['text']}")
        seed = self.run_seed ^ int(digest_text(prompt)[:8], 16)
        started = time.monotonic()
        try:
            response = llm_mod.chat([{"role": "user", "content": prompt}], max_tokens=4096,
                                    temperature=0.6, extra={"reasoning_effort": "medium", "seed": seed},
                                    config=self.config)
            error = None
        except Exception as exc:
            response = {"request_attempts": getattr(exc, "request_attempts", []), "usage": {}}
            error = f"{type(exc).__name__}: {exc}"
        prediction = extract_code(response.get("content") or "").strip().rstrip(";") if not error else ""
        gold_query = row["query"]
        db_path = str(SQL_ROOT / "database" / row["db_path"])
        if error:
            original_flag, original_result, proxy_match, true_correct = "runner_error", None, False, False
            gold_healthy = False
        else:
            original_flag, original_result = asyncio.run(exec_on_db(db_path, prediction))
            _, gold_result = asyncio.run(exec_on_db(db_path, gold_query))
            proxy_match = original_flag == "result" and result_eq(original_result, gold_result, False)
            gold_healthy = True
            for testcase_path in row["testsuite"]:
                gold_status, _ = asyncio.run(exec_on_db(str(SQL_ROOT / testcase_path), gold_query))
                if gold_status != "result":
                    gold_healthy = False
                    break
            true_correct = gold_healthy and judge((row, prediction, False))
        executable = original_flag == "result"
        phantom = executable and gold_healthy and not true_correct
        phantom_proxy = proxy_match and gold_healthy and not true_correct
        usage = response.get("usage") or {}
        plus_status = "pass" if true_correct else "unknown" if not gold_healthy else "fail"
        record = {"task_id": task_id, "scenario_id": task_id,
                  "candidate_sha256": candidate_hash, "code": prediction, "problem": row["text"],
                  "base_status": original_flag, "plus_status": plus_status,
                  "executable": executable, "proxy_match": proxy_match, "true_correct": true_correct,
                  "phantom": phantom, "phantom_proxy": phantom_proxy,
                  "check_verdicts": {"L1_execution": "pass" if executable else "fail",
                                     "L2_testsuite": plus_status},
                  "proxy_score": float(proxy_match), "generation_error": error,
                  "new_llm_calls": 1, "completion_tokens": usage.get("completion_tokens", 0) or 0,
                  "total_tokens": usage.get("total_tokens", 0) or 0,
                  "llm_latency_s": response.get("request_wall_s") or response.get("latency_s") or 0,
                  "wall_seconds": round(time.monotonic() - started, 3)}
        record["feedback"] = (f"Original database execution matches gold: {proxy_match}. "
                              "Improve the SQL query to match the original database result. "
                              "Do not assume one database result proves semantic equivalence.")
        write_json(path, record)
        print(f"[{task_id}][{candidate_hash[:8]}] original={original_flag} match={proxy_match} suite={true_correct}", flush=True)
        return record

    def evaluate(self, batch: list[int], candidate: dict[str, str], capture_traces: bool = False) -> EvaluationBatch:
        records = [self._rollout(index, candidate) for index in batch]
        return EvaluationBatch(outputs=records, scores=[record["proxy_score"] for record in records],
                               trajectories=records if capture_traces else None)

    def make_reflective_dataset(self, candidate: dict[str, str], eval_batch: EvaluationBatch,
                                components_to_update: list[str]):
        component = components_to_update[0]
        return {component: [{"Inputs": {"task_id": record["task_id"], "problem": record["problem"]},
                             "Generated Outputs": record["code"], "Feedback": record["feedback"]}
                            for record in eval_batch.trajectories or []]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--train-limit", type=int, default=0)
    parser.add_argument("--val-limit", type=int, default=0)
    parser.add_argument("--max-metric-calls", type=int, default=120)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--llm-timeout", type=float, default=180)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    llm_mod.REQUEST_TIMEOUT_SEC = args.llm_timeout
    outdir = (ROOT / args.run_dir).resolve()
    if outdir.exists() and any(outdir.iterdir()) and not args.resume:
        raise ValueError("run directory is not empty; use --resume")
    outdir.mkdir(parents=True, exist_ok=True)
    rows = load_tasks()
    splits = split_ids(rows)
    train_ids = splits["dev"][:args.train_limit] if args.train_limit else splits["dev"]
    val_ids = splits["gapcheck"][:args.val_limit] if args.val_limit else splits["gapcheck"]
    os.chdir(SQL_ROOT)
    adapter = Text2SQLAdapter(outdir, rows, args.seed)
    reflection_count = 0

    def reflection_lm(prompt):
        nonlocal reflection_count
        reflection_count += 1
        response = llm_mod.chat([{"role": "user", "content": prompt}], max_tokens=4096,
                                temperature=0.6,
                                extra={"reasoning_effort": "medium", "seed": args.seed + 30000},
                                config=adapter.config)
        write_json(outdir / "reflection" / f"call_{reflection_count:04d}.json",
                   {"messages": [{"role": "user", "content": prompt}], "response": response})
        return response.get("content") or ""

    started = time.monotonic()
    result = gepa.optimize(seed_candidate={"conventions": ""}, trainset=train_ids, valset=val_ids,
                           adapter=adapter, reflection_lm=reflection_lm,
                           max_metric_calls=args.max_metric_calls, run_dir=str(outdir),
                           seed=args.seed, cache_evaluation=True, write_agent_state=True,
                           track_best_outputs=False, use_merge=False,
                           reflection_minibatch_size=3, skip_perfect_score=False,
                           acceptance_criterion="strict_improvement")
    write_json(outdir / "gepa_result.json", result.to_dict())
    analysis = analyze(result, [{"scenario_id": f"academic_{index:04d}"} for index in val_ids], outdir)
    analysis.update(model=adapter.config.model, official_gepa_commit=GEPA_COMMIT,
                    dataset="Text-to-SQL classical academic", protocol_sha256=digest_text(PROTOCOL.read_text()),
                    train_ids=train_ids, val_ids=val_ids,
                    wall_seconds=round(time.monotonic() - started, 3),
                    total_metric_calls=result.total_metric_calls)
    write_json(outdir / "analysis.json", analysis)
    write_json(outdir / "manifest.json", {"official_gepa_commit": GEPA_COMMIT,
                                          "protocol_sha256": digest_text(PROTOCOL.read_text()),
                                          "n_train": len(train_ids), "n_val": len(val_ids),
                                          "public_answer_used_for_reflection": False,
                                          "witness_used_for_reflection": False})
    print(json.dumps(analysis, ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    main()

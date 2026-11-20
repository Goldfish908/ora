#!/usr/bin/env python3
"""Official GEPA optimizing original HumanEval tests while logging EvalPlus tests."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/home/hewj13/wm/ext/gepa/src")
sys.path.insert(0, "/home/hewj13/wm/ext/evalplus")

import gepa
from gepa.core.adapter import EvaluationBatch
from evalplus.data import get_human_eval_plus, get_human_eval_plus_hash
from evalplus.evaluate import check_correctness, get_groundtruth

from ora_agent import llm as llm_mod
from ora_agent.verification_governance import CheckAsset, LayeredAcceptance, convention_source
from scripts.m1_pilot import extract_code
from scripts.evalplus_governance import build_governor, evalplus_eval, trusted_cases
from scripts.retailopt_gepa import analyze, digest_text, write_json

GEPA_COMMIT = "ce5b0d6e3d6af6c6dbec6de2c54536bbb961d309"
PROTOCOL = ROOT / "docs/paper/verification_amplification_protocol_v0.1.md"
SPLIT_SEED = "evalplus-gepa-v0.1"


class EvalPlusAdapter:
    propose_new_texts = None

    def __init__(self, outdir: Path, problems: dict, expected: dict, run_seed: int,
                 task_splits: dict | None = None, governor=None,
                 audit_manifest: dict | None = None, evolve_verification: bool = False):
        self.outdir = outdir
        self.problems = problems
        self.expected = expected
        self.run_seed = run_seed
        self.task_splits = task_splits or {}
        self.governor = governor
        self.audit_manifest = audit_manifest
        self.evolve_verification = evolve_verification
        self.governance_lock = threading.Lock()
        self.config = llm_mod.load_config()

    def _maybe_evolve(self, task_id: str, record: dict) -> None:
        if not self.evolve_verification or self.task_splits.get(task_id) != "dev" \
                or not record.get("phantom_proxy") or self.governor.frozen:
            return
        with self.governance_lock:
            if "L2_evalplus" in self.governor.checks:
                return
            source = convention_source("evalplus_official_tests_v1",
                                       digest_text("evalplus-official-tests"), True)
            self.governor.register(CheckAsset("L2_evalplus", 2, evalplus_eval, source))
            self.governor.promote("L2_evalplus", trusted_cases(self.audit_manifest))
            write_json(self.outdir / "governor.json", self.governor.public_state())
            print("verification knowledge candidate evaluated: L2_evalplus", flush=True)

    def _rollout(self, task_id: str, candidate: dict[str, str]) -> dict:
        problem = self.problems[task_id]
        conventions = candidate["conventions"]
        candidate_hash = digest_text(conventions)
        path = self.outdir / "rollouts" / candidate_hash / f"{task_id.replace('/', '_')}.json"
        if path.exists():
            record = json.loads(path.read_text())
            if record["candidate_sha256"] != candidate_hash or record["task_id"] != task_id:
                raise ValueError("cached EvalPlus rollout identity mismatch")
            if record.get("generation_error") is None:
                record["new_llm_calls"] = 0
                return record
        prompt = (conventions.strip() + "\n\n" + problem["prompt"]
                  + "\n\nWrite the complete self-contained Python function. Return only executable Python code.")
        seed = self.run_seed ^ int(digest_text(prompt)[:8], 16)
        started = time.monotonic()
        try:
            response = llm_mod.chat([{"role": "user", "content": prompt}], max_tokens=8192,
                                    temperature=0.6,
                                    extra={"reasoning_effort": "medium", "seed": seed}, config=self.config)
            error = None
        except Exception as exc:
            response = {"request_attempts": getattr(exc, "request_attempts", []), "usage": {}}
            error = f"{type(exc).__name__}: {exc}"
        completion = extract_code(response.get("content") or "") if not error else ""
        solution = completion if f"def {problem['entry_point']}" in completion else problem["prompt"] + completion
        write_json(path.parent / "generation.json", {"task_id": task_id, "prompt": prompt,
                                                      "response": response, "error": error})
        if error:
            base_status, plus_status = "runner_error", "runner_error"
            base_details, plus_details = [], []
        else:
            result = check_correctness("humaneval", 0, problem, solution, self.expected[task_id],
                                       base_only=False, fast_check=True)
            base_status, base_details = result["base"]
            plus_status, plus_details = result["plus"]
        executable = base_status in {"pass", "fail"}
        proxy_match = base_status == "pass"
        true_correct = plus_status == "pass"
        phantom = executable and not true_correct
        phantom_proxy = proxy_match and not true_correct
        usage = response.get("usage") or {}
        record = {"task_id": task_id, "scenario_id": task_id,
                  "candidate_sha256": candidate_hash, "code": solution,
                  "problem": problem["prompt"], "base_status": base_status, "plus_status": plus_status,
                  "base_details": list(base_details), "plus_details": list(plus_details),
                  "executable": executable, "proxy_match": proxy_match, "true_correct": true_correct,
                  "phantom": phantom, "phantom_proxy": phantom_proxy,
                  "check_verdicts": {"L1_execution": "pass" if executable else "fail",
                                     "L2_evalplus": "pass" if true_correct else
                                     "unknown" if plus_status in {"timeout", "runner_error"} else "fail"},
                  "proxy_score": float(proxy_match), "generation_error": error,
                  "new_llm_calls": 1, "completion_tokens": usage.get("completion_tokens", 0) or 0,
                  "total_tokens": usage.get("total_tokens", 0) or 0,
                  "llm_latency_s": response.get("request_wall_s") or response.get("latency_s") or 0,
                  "wall_seconds": round(time.monotonic() - started, 3)}
        record["feedback"] = (f"Original HumanEval tests: {base_status}. "
                              "Improve the function to increase the original-test pass rate. "
                              "Do not assume the original tests cover all edge cases.")
        write_json(path, record)
        self._maybe_evolve(task_id, record)
        print(f"[{task_id}][{candidate_hash[:8]}] base={base_status} plus={plus_status}", flush=True)
        return record

    def evaluate(self, batch: list[str], candidate: dict[str, str], capture_traces: bool = False) -> EvaluationBatch:
        records = [self._rollout(task_id, candidate) for task_id in batch]
        return EvaluationBatch(outputs=records, scores=[record["proxy_score"] for record in records],
                               trajectories=records if capture_traces else None)

    def make_reflective_dataset(self, candidate: dict[str, str], eval_batch: EvaluationBatch,
                                components_to_update: list[str]):
        component = components_to_update[0]
        return {component: [{"Inputs": {"task_id": record["task_id"], "problem": record["problem"]},
                             "Generated Outputs": record["code"], "Feedback": record["feedback"]}
                            for record in eval_batch.trajectories or []]}


def split_ids(problems: dict) -> dict[str, list[str]]:
    ordered = sorted(problems, key=lambda task_id: digest_text(f"{SPLIT_SEED}:{task_id}"))
    return {"dev": sorted(ordered[:40]), "gapcheck": sorted(ordered[40:100]),
            "test": sorted(ordered[100:])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--train-limit", type=int, default=0)
    parser.add_argument("--val-limit", type=int, default=0)
    parser.add_argument("--max-metric-calls", type=int, default=160)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--llm-timeout", type=float, default=180)
    parser.add_argument("--rule-mode", choices=("none", "r1", "r2", "both"), default="none")
    parser.add_argument("--governance-cases", default="work/evalplus_governance_smoke_v0.1/cases.json")
    parser.add_argument("--mini", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    llm_mod.REQUEST_TIMEOUT_SEC = args.llm_timeout
    outdir = (ROOT / args.run_dir).resolve()
    if outdir.exists() and any(outdir.iterdir()) and not args.resume:
        raise ValueError("run directory is not empty; use --resume")
    outdir.mkdir(parents=True, exist_ok=True)
    problems = get_human_eval_plus(mini=args.mini)
    dataset_hash = get_human_eval_plus_hash(mini=args.mini)
    expected = get_groundtruth(problems, dataset_hash, [])
    splits = split_ids(problems)
    train_ids = splits["dev"][:args.train_limit] if args.train_limit else splits["dev"]
    val_ids = splits["gapcheck"][:args.val_limit] if args.val_limit else splits["gapcheck"]
    task_splits = {**{task_id: "dev" for task_id in train_ids},
                   **{task_id: "gapcheck" for task_id in val_ids}}
    governor = None
    audit_manifest = None
    acceptance_criterion = "strict_improvement"
    if args.rule_mode != "none":
        audit_manifest = json.loads((ROOT / args.governance_cases).read_text())
        governor_path = outdir / "governor.json"
        previous = json.loads(governor_path.read_text()) if governor_path.exists() else {}
        has_evalplus = any(check["check_id"] == "L2_evalplus" and check["status"] == "veto_enabled"
                           for check in previous.get("checks", []))
        governor = build_governor(audit_manifest, include_evalplus=has_evalplus)
        governor.frozen = previous.get("frozen", False)
        target_level = 1000000 if args.rule_mode == "r1" else 0
        acceptance_criterion = LayeredAcceptance(governor, target_level=target_level, require_final=True)
    adapter = EvalPlusAdapter(outdir, problems, expected, args.seed, task_splits=task_splits,
                              governor=governor, audit_manifest=audit_manifest,
                              evolve_verification=args.rule_mode in {"r1", "both"})
    reflection_count = 0

    def reflection_lm(prompt):
        nonlocal reflection_count
        reflection_count += 1
        response = llm_mod.chat([{"role": "user", "content": prompt}], max_tokens=8192,
                                temperature=0.6,
                                extra={"reasoning_effort": "medium", "seed": args.seed + 20000},
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
                           acceptance_criterion=acceptance_criterion)
    write_json(outdir / "gepa_result.json", result.to_dict())
    if governor is not None:
        governor.freeze()
        write_json(outdir / "governor.json", governor.public_state())
    analysis = analyze(result, [{"scenario_id": task_id} for task_id in val_ids], outdir)
    analysis.update(model=adapter.config.model, official_gepa_commit=GEPA_COMMIT,
                    dataset="HumanEval/HumanEval+", dataset_hash=dataset_hash,
                    rule_mode=args.rule_mode,
                    protocol_sha256=digest_text(PROTOCOL.read_text()),
                    train_ids=train_ids, val_ids=val_ids,
                    wall_seconds=round(time.monotonic() - started, 3),
                    total_metric_calls=result.total_metric_calls)
    write_json(outdir / "analysis.json", analysis)
    write_json(outdir / "manifest.json", {"official_gepa_commit": GEPA_COMMIT,
                                          "protocol_sha256": digest_text(PROTOCOL.read_text()),
                                          "n_train": len(train_ids), "n_val": len(val_ids),
                                          "rule_mode": args.rule_mode,
                                          "public_answer_used_for_reflection": False,
                                          "witness_used_for_reflection": False})
    print(json.dumps(analysis, ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    main()

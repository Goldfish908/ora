#!/usr/bin/env python3
"""Official GEPA and direct-generation baselines on clean ORAgentBench tasks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/home/hewj13/wm/ext/gepa/src")

from ora_agent import llm as llm_mod
from ora_agent.cleanroom import EvidenceMemory, SpecificationAsset, restore_specifications
from ora_agent.oragentbench import (
    TaskPacket,
    execute_solver,
    generate_artifacts,
    official_evaluate,
    official_metrics,
    prepare_workspace,
    probe_pyscipopt_api,
    proxy_match,
    read_json,
    run_oracle,
    write_json,
)

GEPA_COMMIT = "ce5b0d6e3d6af6c6dbec6de2c54536bbb961d309"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_tasks(config_path: Path) -> list[TaskPacket]:
    config = read_json(config_path)
    packets = []
    for item in config["tasks"]:
        root = ROOT / "ORAgentBench/harbor_tasks" / item["name"]
        packets.append(TaskPacket.load(root, item["domain"], item["split"]))
    return packets


def gepa_seed_candidate(args: argparse.Namespace) -> dict[str, str]:
    if not args.gepa_seed_result:
        return {"conventions": ""}
    result = read_json((ROOT / args.gepa_seed_result).resolve())
    return {"conventions": result["candidates"][args.gepa_seed_idx]["conventions"]}


def record_implementation(outdir: Path, args: argparse.Namespace, config: llm_mod.LLMConfig,
                          resume: bool) -> None:
    files = ["ora_agent/llm.py", "ora_agent/cleanroom.py", "ora_agent/oragentbench.py", "ora_agent/api_guard.py",
             "ora_agent/cleanroom_witness.py", "ora_agent/cleanroom_spec_audit.py",
             "scripts/cleanroom_experiment.py", "scripts/cleanroom_repair.py", "scripts/cleanroom_memory.py"]
    payload = {"files": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
               "tasks_sha256": hashlib.sha256((ROOT / args.tasks).read_bytes()).hexdigest(),
               "model": config.model, "gepa_commit": GEPA_COMMIT,
               "generation": {"max_tokens": int(os.environ.get("ORA_CLEANROOM_MAX_TOKENS", "32768")),
                              "reasoning_effort": os.environ.get("ORA_CLEANROOM_REASONING", "medium"),
                              "disable_thinking": os.environ.get("ORA_CLEANROOM_DISABLE_THINKING") == "1",
                              "model_reasoning_effort": os.environ.get("ORA_CLEANROOM_MODEL_REASONING",
                                                                        os.environ.get("ORA_CLEANROOM_REASONING", "medium")),
                              "solver_reasoning_effort": os.environ.get("ORA_CLEANROOM_SOLVER_REASONING",
                                                                         os.environ.get("ORA_CLEANROOM_REASONING", "medium")),
                              "model_disable_thinking": os.environ.get("ORA_CLEANROOM_MODEL_DISABLE_THINKING",
                                                                        os.environ.get("ORA_CLEANROOM_DISABLE_THINKING", "0")) == "1",
                              "solver_disable_thinking": os.environ.get("ORA_CLEANROOM_SOLVER_DISABLE_THINKING",
                                                                         os.environ.get("ORA_CLEANROOM_DISABLE_THINKING", "0")) == "1",
                              "model_max_tokens": int(os.environ.get("ORA_CLEANROOM_MODEL_TOKENS", "4096")),
                              "model_max_words": int(os.environ.get("ORA_CLEANROOM_MODEL_WORDS", "1800")),
                              "temperature": 0.6, "protocol": "two_phase_model_then_solver_v1",
                              "stream": False},
               "arguments": vars(args)}
    path = outdir / "implementation.json"
    if resume and path.exists():
        previous = read_json(path)
        for key in ("files", "tasks_sha256", "model", "generation"):
            if previous[key] != payload[key]:
                raise ValueError(f"implementation changed while resuming: {key}")
    write_json(path, payload)


class CleanroomAdapter:
    propose_new_texts = None

    def __init__(self, outdir: Path, workers: int, seed: int, config: llm_mod.LLMConfig,
                 api_assist: bool = False, api_guard: bool = False,
                 dev_official_feedback: bool = False):
        self.outdir = outdir
        self.workers = workers
        self.seed = seed
        self.config = config
        self.api_assist = api_assist
        self.api_guard = api_guard
        self.dev_official_feedback = dev_official_feedback
        self._api_contract = None

    def _rollout(self, packet: TaskPacket, candidate: dict[str, str]) -> dict:
        specification = candidate["conventions"]
        candidate_hash = digest(specification)
        base = self.outdir / "rollouts" / candidate_hash / packet.name / "attempt_0"
        record_path = base / "record.json"
        if record_path.exists():
            cached = read_json(record_path)
            if cached["candidate_sha256"] == candidate_hash and not cached.get("generation_error"):
                return cached
            retry_id = f"{time.time_ns()}_{uuid.uuid4().hex[:8]}"
            write_json(base / f"record_before_retry_{retry_id}.json", cached)
            base = base / "retries" / retry_id
        workspace = base / "app"
        artifacts = None
        generation_error = None
        try:
            artifacts = generate_artifacts(packet, specification, self.config, base / "generation",
                                           run_seed=self.seed)
            prepare_workspace(packet, workspace, artifacts, api_guard=self.api_guard)
            execution = execute_solver(workspace, base / "execution")
        except Exception as exc:
            execution = {"return_code": -1, "timed_out": False,
                         "error": f"{type(exc).__name__}: {exc}"}
            generation_error = execution["error"]
        if execution.get("stderr"):
            execution["stderr_tail"] = execution["stderr"][-4000:]
        if execution.get("stdout"):
            execution["stdout_tail"] = execution["stdout"][-2000:]
        official = official_evaluate(packet, workspace, base / "official") if workspace.exists() else {
            "evaluation": {"feasible": False, "errors": ["workspace was not created"]},
            "reward": {"feasibility": 0.0, "quality": 0.0}, "reward_details": {}}
        metrics = official_metrics(official)
        proxy = proxy_match(packet, official)
        true_correct = metrics["true_correct"]
        phantom_proxy = bool(proxy) and not true_correct
        unknown = metrics["evaluation_unknown"]
        feedback = (f"Execution return code: {execution.get('return_code')}; "
                    f"timed out: {execution.get('timed_out')}; proxy objective match: {proxy}. ")
        if execution.get("error"):
            feedback += f"Public artifact/validation diagnostic: {execution['error']}. "
        elif execution.get("return_code") != 0:
            if execution.get("stderr_tail"):
                feedback += f"Public execution stderr tail:\n{execution['stderr_tail']}\n"
            if execution.get("stdout_tail"):
                feedback += f"Public execution stdout tail:\n{execution['stdout_tail']}\n"
        if self.dev_official_feedback and packet.split == "dev":
            violations = (official.get("evaluation", {}).get("errors") or [])[:20]
            if violations:
                feedback += ("Development-only official violation coordinates; no reference solution or "
                             "reference objective is included:\n"
                             + json.dumps(violations, ensure_ascii=False) + "\n")
        feedback += ("Improve the formulation and solver to increase the proxy score. "
                     "Do not assume that a solution file alone proves business correctness.")
        record = {
            "task": packet.name, "domain": packet.domain, "split": packet.split,
            "candidate_sha256": candidate_hash, "attempt": 0,
            "problem": {"instruction": packet.instruction,
                        "problem_statement": packet.problem_statement,
                        "public_files": packet.public_files},
            "artifacts": artifacts, "execution": {key: value for key, value in execution.items()
                                                   if key not in {"stdout", "stderr"}},
            "official": official, **metrics, "proxy_match": proxy,
            "api_guard": read_json(workspace / "api_guard.json") if (workspace / "api_guard.json").exists() else None,
            "true_correct": true_correct, "phantom_proxy": phantom_proxy,
            "unknown": unknown, "generation_error": generation_error,
            "proxy_score": float(bool(proxy)), "feedback": feedback,
            "workspace": str(workspace),
        }
        write_json(record_path, record)
        print(f"[{packet.name}][{candidate_hash[:8]}] proxy={proxy} true={true_correct} "
              f"phantom={phantom_proxy} quality={metrics['quality']:.4f}", flush=True)
        return record

    def evaluate(self, batch: list[TaskPacket], candidate: dict[str, str],
                 capture_traces: bool = False) -> EvaluationBatch:
        from gepa.core.adapter import EvaluationBatch
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            records = list(pool.map(lambda packet: self._rollout(packet, candidate), batch))
        return EvaluationBatch(outputs=records, scores=[record["proxy_score"] for record in records],
                               trajectories=records if capture_traces else None)

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        component = components_to_update[0]
        rows = eval_batch.trajectories or []
        if self.api_assist and self._api_contract is None:
            self._api_contract = probe_pyscipopt_api(self.outdir / "api_contract")["stdout"]
        reflective = []
        for record in rows:
            inputs = {"task": record["task"], "problem": record["problem"]}
            if self.api_assist:
                inputs["environment_api_contract"] = self._api_contract
            reflective.append({"Inputs": inputs, "Generated Outputs": record["artifacts"],
                               "Feedback": record["feedback"]})
        return {component: reflective}


def summarize(records: list[dict]) -> dict:
    return {"n": len(records), "executable": sum(record["execution"].get("return_code") == 0 for record in records),
            "feasible": sum(record["feasible"] for record in records),
            "proxy_match": sum(bool(record["proxy_match"]) for record in records),
            "true_correct": sum(record["true_correct"] for record in records),
            "phantom_proxy": sum(record["phantom_proxy"] for record in records),
            "unknown": sum(record["unknown"] for record in records),
            "generation_errors": sum(record["generation_error"] is not None for record in records),
            "mean_quality": sum(record["quality"] for record in records) / len(records) if records else 0.0}


def analyze(result, valset: list[TaskPacket], outdir: Path) -> dict:
    curves = []
    for index, candidate in enumerate(result.candidates):
        candidate_hash = digest(candidate["conventions"])
        records = [read_json(outdir / "rollouts" / candidate_hash / packet.name / "attempt_0/record.json")
                   for packet in valset]
        curves.append({"candidate_idx": index, "candidate_sha256": candidate_hash,
                       "parents": result.parents[index],
                       "official_proxy_mean": result.val_aggregate_scores[index],
                       **summarize(records)})
    return {"curves": curves, "n_candidates": len(curves),
            "witness_errors_used_for_reflection": False,
            "official_reference_values_used_for_reflection": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--mode", choices=("direct", "gepa", "oracle"), default="gepa")
    parser.add_argument("--max-metric-calls", type=int, default=30)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--llm-timeout", type=float, default=180)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--task-name")
    parser.add_argument("--spec-source")
    parser.add_argument("--spec-id")
    parser.add_argument("--api-assist", action="store_true")
    parser.add_argument("--api-guard", action="store_true")
    parser.add_argument("--dev-official-feedback", action="store_true")
    parser.add_argument("--gepa-seed-result")
    parser.add_argument("--gepa-seed-idx", type=int, default=0)
    args = parser.parse_args()
    llm_mod.REQUEST_TIMEOUT_SEC = args.llm_timeout
    config = llm_mod.load_config()
    outdir = (ROOT / args.run_dir).resolve()
    if outdir.exists() and any(outdir.iterdir()) and not args.resume:
        raise ValueError("run directory is not empty; use --resume")
    outdir.mkdir(parents=True, exist_ok=True)
    record_implementation(outdir, args, config, args.resume)
    packets = load_tasks(ROOT / args.tasks)
    trainset = [packet for packet in packets if packet.split == "dev"]
    valset = [packet for packet in packets if packet.split == "transfer"]
    adapter = CleanroomAdapter(outdir, args.workers, args.seed, config,
                               api_assist=args.api_assist, api_guard=args.api_guard,
                               dev_official_feedback=args.dev_official_feedback)
    started = time.monotonic()

    if args.mode == "oracle":
        results = {}
        for packet in packets:
            results[packet.name] = run_oracle(packet, outdir / packet.name / "oracle/app")
        write_json(outdir / "oracle_results.json", results)
        print(json.dumps({name: result["metrics"] for name, result in results.items()}, indent=1))
        return

    if args.mode == "direct":
        packet = next((packet for packet in packets if packet.name == args.task_name), packets[0])
        specification = ""
        if args.spec_source:
            memory = restore_specifications(read_json((ROOT / args.spec_source).resolve()))
            asset = memory.generator_specification(packet.scope)
            if asset is None or (args.spec_id and asset.spec_id != args.spec_id):
                raise ValueError("no promoted specification is authorized for this task scope")
            specification = asset.text
        result = adapter._rollout(packet, {"conventions": specification})
        write_json(outdir / "direct_result.json", result)
        print(json.dumps(summarize([result]), indent=1))
        return

    import gepa
    reflection_dir = outdir / "reflection"

    def reflection_lm(prompt):
        response = llm_mod.chat([{"role": "user", "content": prompt}], max_tokens=8192,
                                temperature=0.6,
                                extra={"reasoning_effort": "medium", "stream": True,
                                       "stream_options": {"include_usage": True}, "seed": args.seed + 10000},
                                config=config)
        write_json(reflection_dir / f"{time.time_ns()}_{uuid.uuid4().hex[:8]}.json",
                   {"messages": [{"role": "user", "content": prompt}], "response": response})
        return response.get("content") or ""

    result = gepa.optimize(seed_candidate=gepa_seed_candidate(args), trainset=trainset, valset=valset,
                           adapter=adapter, reflection_lm=reflection_lm,
                           max_metric_calls=args.max_metric_calls, run_dir=str(outdir),
                           seed=args.seed, cache_evaluation=True, write_agent_state=True,
                           track_best_outputs=False, use_merge=False,
                           reflection_minibatch_size=min(3, len(trainset)), skip_perfect_score=False,
                           acceptance_criterion="strict_improvement")
    write_json(outdir / "gepa_result.json", result.to_dict())
    analysis = analyze(result, valset, outdir)
    analysis.update(model=config.model, official_gepa_commit=GEPA_COMMIT,
                    wall_seconds=round(time.monotonic() - started, 3),
                    total_metric_calls=result.total_metric_calls,
                    train_ids=[packet.name for packet in trainset],
                    val_ids=[packet.name for packet in valset])
    write_json(outdir / "analysis.json", analysis)

    memory = EvidenceMemory()
    for index, candidate in enumerate(result.candidates):
        parents = result.parents[index]
        parent_id = f"spec_{parents[0]}" if parents and parents[0] is not None else None
        memory.register_specification(SpecificationAsset(
            f"spec_{index}", candidate["conventions"], {"dataset": "oragentbench"},
            parent_id=parent_id, source_refs=["dev_public_problem_statements"]))
    write_json(outdir / "memory.json", memory.public_state())
    print(json.dumps(analysis, ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    main()

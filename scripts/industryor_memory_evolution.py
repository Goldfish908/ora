#!/usr/bin/env python3
"""Run development-only memory evolution and frozen IndustryOR repair tests."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod
from ora_agent.evolving_memory import (
    EvolvingMemoryRegistry,
    digest_file,
    digest_json,
    execution_signature,
    memory_view,
)
from ora_agent.memory_guards import GUARD_ADDVAR_NAME, GUARD_ADDVAR_V, validate_guard_contract
from scripts.industryor_k3_pipeline import costs
from scripts.industryor_semantic_dag import REGISTERED_AUDIT_IDS
from scripts.industryor_structured_pipeline import run_dag

DATA = ROOT / "data/industryor/IndustryOR.json"
SOURCE = ROOT / "work/industryor_k3_dev_v0.1"
PROTOCOL = ROOT / "docs/paper/industryor_memory_evolution_protocol_v0.1.md"
REGISTRY_NAME = "registry.json"
SPLIT_SEED = "industryor-memory-evolution-v0.1"
SEEDS = (101, 202, 303)
IMPLEMENTATION = (
    "ora_agent/evolving_memory.py",
    "ora_agent/memory_guards.py",
    "ora_agent/evidence_dag.py",
    "ora_agent/semantic_dag.py",
    "ora_agent/semantic_binding.py",
    "ora_agent/repair_controller.py",
    "ora_agent/llm.py",
    "scripts/industryor_structured_pipeline.py",
    "scripts/industryor_semantic_dag.py",
    "scripts/industryor_k3_pipeline.py",
    "scripts/industryor_next_stage.py",
    "scripts/industryor_memory_evolution.py",
    "scripts/m1_pilot.py",
    "scripts/m3_industryor.py",
)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def load_source() -> list[dict]:
    return json.loads((SOURCE / "analysis.json").read_text())["results"]


def question_rows() -> dict[int, dict]:
    return {row["id"]: row for row in json.loads(DATA.read_text())}


def allocate_ids() -> dict[str, list[int]]:
    ordered = sorted(question_rows(), key=lambda problem_id: hashlib.sha256(
        f"{SPLIT_SEED}:{problem_id}".encode()).hexdigest())
    return {"dev": sorted(ordered[:40]), "gapcheck": sorted(ordered[40:70]),
            "test": sorted(ordered[70:])}


def candidate_for(row: dict, candidate_id: str) -> dict:
    return next(candidate for candidate in row["candidates"]
                if candidate["candidate_id"] == candidate_id)


def build_task(row: dict, candidate: dict) -> dict:
    problem_id = row["id"]
    candidate_id = candidate["candidate_id"]
    solution_path = SOURCE / f"prob_{problem_id:03d}" / f"candidate_{candidate_id}" / "solution.json"
    solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
    question = question_rows()[problem_id]["en_question"]
    return {"task_id": f"prob_{problem_id:03d}_{candidate_id}", "problem_id": problem_id,
            "candidate_id": candidate_id, "question": question,
            "selected": {"code": candidate["code"], "record": candidate["record"],
                         "audit": {"gate": candidate["gate"], "solution": solution,
                                   "score": candidate["score"]},
                         "objective": candidate["objective"],
                         "business_accepted": candidate["business_accepted"]},
            "signature": execution_signature(candidate["record"]),
            "code_sha256": hashlib.sha256(candidate["code"].encode()).hexdigest()}


def one_per_problem(tasks: list[dict]) -> list[dict]:
    chosen = {}
    for task in sorted(tasks, key=lambda item: item["task_id"]):
        chosen.setdefault(task["problem_id"], task)
    return [chosen[problem_id] for problem_id in sorted(chosen)]


def split_tasks(split: str) -> list[dict]:
    splits = allocate_ids()
    allowed = set(splits[split])
    return [build_task(row, candidate) for row in load_source() if row["id"] in allowed
            for candidate in row["candidates"]]


def prepare(outdir: Path) -> None:
    if outdir.exists() and any(outdir.iterdir()):
        raise ValueError("experiment output directory is not empty")
    outdir.mkdir(parents=True, exist_ok=True)
    splits = allocate_ids()
    write_json(outdir / "splits.json", {"seed": SPLIT_SEED, "splits": splits,
                                        "source_analysis_sha256": digest_file(SOURCE / "analysis.json"),
                                        "protocol_sha256": digest_file(PROTOCOL)})
    clusters = defaultdict(list)
    for task in split_tasks("dev"):
        if task["signature"]:
            clusters[task["signature"]].append(task)
    eligible = {signature: one_per_problem(tasks) for signature, tasks in clusters.items()
                if len({task["problem_id"] for task in tasks}) >= 3}
    if not eligible:
        raise ValueError("no dev failure cluster has three independent problems")
    signature = max(eligible, key=lambda key: (len(eligible[key]), key))
    tasks = eligible[signature]
    public_tasks = [{key: value for key, value in task.items() if key not in {"question", "selected"}}
                    for task in tasks]
    write_json(outdir / "dev_cluster.json", {
        "signature": signature, "n_problems": len(tasks), "task_ids": [task["task_id"] for task in tasks],
        "eligible_cluster_counts": {key: len(value) for key, value in eligible.items()},
        "tasks": public_tasks,
        "trace_sha256": digest_json([{"code": task["selected"]["code"],
                                      "record": task["selected"]["record"]} for task in tasks])})
    write_json(outdir / "experiment_config.json", {
        "seeds": list(SEEDS), "validation_max_rounds": 2, "test_max_rounds": 3,
        "source": str(SOURCE.relative_to(ROOT)), "source_analysis_sha256": digest_file(SOURCE / "analysis.json"),
        "protocol_sha256": digest_file(PROTOCOL),
        "exposure": "retrospective_development_split_not_sealed",
        "reference_answer_used_for_proposal_or_promotion": False})
    print(json.dumps({"target_signature": signature, "dev_problems": len(tasks),
                      "split_sizes": {key: len(value) for key, value in splits.items()}}, indent=1))


def proposal_messages(outdir: Path) -> list[dict]:
    cluster = json.loads((outdir / "dev_cluster.json").read_text())
    task_ids = set(cluster["task_ids"])
    tasks = [task for task in split_tasks("dev") if task["task_id"] in task_ids]
    examples = []
    for task in tasks[:5]:
        examples.append({"problem_id": task["problem_id"],
                         "question": task["question"][:3000],
                         "code_excerpt": task["selected"]["code"][:5000],
                         "execution": {key: task["selected"]["record"].get(key) for key in
                                       ("exec_status", "solver_status", "export_error", "stderr_tail")}})
    prompt = ("You are the proposer in a self-evolving optimization-model repair system. "
              "Distill ONE reusable engineering lesson from the development failures below. "
              "Do not use or guess reference answers. Do not include problem IDs, instance-specific answers, "
              "business semantics, or numerical target values. The lesson must apply only to the named "
              "execution failure and must preserve existing business variables, constraints, and objective.\n\n"
              f"Failure signature: {cluster['signature']}\n"
              "Available guards: 'addvar_v_to_name' only when vtype already exists and v carries a name; "
              "'addvar_v_to_vtype' only when vtype is absent and v is a literal variable domain. "
              "Return guard=null when the role is ambiguous or no allowlisted guard applies.\n\n"
              "Return ONLY JSON: {\"text\": \"one conditional lesson, at most four sentences\", "
              "\"guard\": \"addvar_v_to_name\", \"addvar_v_to_vtype\" or null, "
              "\"rationale\": \"one sentence\"}.\n\n"
              f"[DEVELOPMENT FAILURES]\n{json.dumps(examples, ensure_ascii=False)}")
    return [{"role": "user", "content": prompt}]


def propose(outdir: Path) -> None:
    destination = outdir / "proposal.json"
    if destination.exists():
        print("proposal exists; skipping")
        return
    messages = proposal_messages(outdir)
    config = llm_mod.load_config()
    response = llm_mod.chat(messages, max_tokens=4096, temperature=0.2,
                            extra={"reasoning_effort": "medium", "seed": 11}, config=config)
    text = response.get("content") or ""
    value = json.loads(text[text.find("{"):text.rfind("}") + 1])
    cluster = json.loads((outdir / "dev_cluster.json").read_text())
    registry = EvolvingMemoryRegistry(outdir / REGISTRY_NAME)
    origin = {"dataset": "IndustryOR", "split": "dev", "source_ids": cluster["task_ids"],
              "trace_sha256": cluster["trace_sha256"], "proposer": "Qwen3.8-27B",
              "rationale": value.get("rationale", "")}
    common = {"kind": "execution", "signature": cluster["signature"], "text": value["text"]}
    prompt_asset = registry.propose({**common, "form": "prompt", "guard": None}, origin)
    assets = [prompt_asset]
    if value.get("guard"):
        assets.append(registry.propose({**common, "form": "guard", "guard": value["guard"]}, origin,
                                       parent_id=prompt_asset["asset_id"]))
    write_json(destination, {"messages": messages, "response": response,
                             "asset_ids": [asset["asset_id"] for asset in assets],
                             "public_answer_in_prompt": False})
    print(json.dumps({"proposed": [asset["asset_id"] for asset in assets]}, indent=1))


def infer_guard(tasks: list[dict], signature: str) -> str | None:
    observations = []
    for task in tasks:
        if task["signature"] != signature:
            continue
        tree = ast.parse(task["selected"]["code"])
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "addVar"):
                continue
            keywords = {keyword.arg: keyword for keyword in node.keywords if keyword.arg}
            if "v" not in keywords:
                continue
            value = keywords["v"].value
            has_type = "vtype" in keywords
            has_name = "name" in keywords
            if has_type and not has_name and isinstance(value, (ast.Constant, ast.JoinedStr)):
                observations.append("name")
            elif (not has_type and isinstance(value, ast.Constant)
                  and isinstance(value.value, str)
                  and value.value.upper() in {"B", "I", "C", "BINARY", "INTEGER", "CONTINUOUS"}):
                observations.append("vtype")
            else:
                return None
    if not observations:
        return None
    roles = set(observations)
    if roles == {"name"}:
        return GUARD_ADDVAR_NAME
    if roles == {"vtype"}:
        return GUARD_ADDVAR_V
    return None


def crystallize(outdir: Path) -> None:
    destination = outdir / "crystallization.json"
    attempts = []
    if destination.exists():
        previous = json.loads(destination.read_text())
        if previous.get("guard"):
            print("crystallization exists; skipping")
            return
        attempts = previous.get("attempts", []) + [{key: value for key, value in previous.items()
                                                   if key != "attempts"}]
    cluster = json.loads((outdir / "dev_cluster.json").read_text())
    registry = EvolvingMemoryRegistry(outdir / REGISTRY_NAME)
    parents = [asset for asset in registry.assets
               if asset["form"] == "prompt" and asset["signature"] == cluster["signature"]
               and asset["status"] == "candidate"]
    if len(parents) != 1:
        raise ValueError("crystallization requires one prompt candidate")
    parent = parents[0]
    guard = infer_guard(split_tasks("dev"), cluster["signature"])
    record = {"parent_id": parent["asset_id"], "guard": guard,
              "source_ids": cluster["task_ids"], "attempts": attempts}
    if guard:
        existing = [asset for asset in registry.assets if asset["form"] == "guard"
                    and asset["signature"] == cluster["signature"] and asset["guard"] == guard
                    and asset["status"] == "candidate"]
        if existing:
            asset = existing[0]
            record["reused_existing_asset"] = True
        else:
            origin = {**parent["origin"], "proposer": "deterministic_ast_crystallizer",
                      "rationale": "All dev addVar(v=...) occurrences have one consistent, independently inspectable role."}
            asset = registry.propose({"kind": parent["kind"], "form": "guard",
                                      "signature": parent["signature"], "text": parent["text"], "guard": guard},
                                     origin, parent_id=parent["asset_id"])
        record.update(asset_id=asset["asset_id"], contract=validate_guard_contract(guard))
    write_json(destination, record)
    print(json.dumps(record, indent=1))


def empty_provider(record, score, gate):
    return memory_view([])


empty_provider.cache_sha256 = "no_memory"


def asset_provider(asset: dict):
    def provider(record, score, gate):
        selected = [asset] if execution_signature(record) == asset["signature"] else []
        return memory_view(selected, include_guards=asset["form"] == "guard")
    provider.cache_sha256 = digest_json(asset)
    return provider


def registry_provider(registry: EvolvingMemoryRegistry):
    def provider(record, score, gate):
        return memory_view(registry.select(record, score))
    provider.cache_sha256 = digest_file(registry.path)
    return provider


def result_execution_success(result: dict) -> bool:
    record = result["record"]
    solution = result.get("solution")
    objective = result.get("objective")
    solver_status = record.get("solver_status") or (solution or {}).get("solver_status")
    return bool(record.get("exec_status") == "ok" and solver_status == "optimal"
                and isinstance(solution, dict) and solution.get("solution_count", 0) >= 1
                and (solution.get("export") or {}).get("complete") is True
                and isinstance(objective, (int, float)) and math.isfinite(objective))


def execution_fingerprint(task: dict, arm: str, provider, seed: int, max_rounds: int) -> str:
    return digest_json({"initial_code_sha256": task["code_sha256"], "arm": arm,
                        "provider_sha256": getattr(provider, "cache_sha256", None),
                        "seed": seed, "max_rounds": max_rounds,
                        "implementation": {name: digest_file(ROOT / name) for name in IMPLEMENTATION}})


def execute_task(task: dict, arm: str, provider, case: Path, shared: Path,
                 seed: int, max_rounds: int) -> dict:
    path = case / "result.json"
    fingerprint = execution_fingerprint(task, arm, provider, seed, max_rounds)
    if path.exists():
        previous = json.loads(path.read_text())
        if previous.get("execution_fingerprint") != fingerprint:
            raise ValueError("cached execution has a different implementation, input, seed, or memory")
        if previous.get("status") == "completed":
            return previous
    started = time.monotonic()
    try:
        final = run_dag(task["problem_id"], task["question"], task["selected"], case, shared,
                        llm_mod.load_config(), memory_provider=provider,
                        max_rounds=max_rounds, generation_seed=seed)
        repair_records = final.pop("repair_records")
        result = {"task_id": task["task_id"], "problem_id": task["problem_id"],
                  "candidate_id": task["candidate_id"], "arm": arm, "seed": seed,
                  "status": "completed", "signature": task["signature"],
                  "initial_code_sha256": task["code_sha256"], "execution_fingerprint": fingerprint,
                  "final": final, "execution_success": result_execution_success(final),
                  "repair_cost": costs(repair_records), "wall_seconds": round(time.monotonic() - started, 3)}
    except Exception as exc:
        result = {"task_id": task["task_id"], "problem_id": task["problem_id"],
                  "candidate_id": task["candidate_id"], "arm": arm, "seed": seed,
                  "status": "runner_error", "signature": task["signature"],
                  "error": f"{type(exc).__name__}: {exc}", "execution_fingerprint": fingerprint,
                  "execution_success": False, "repair_cost": costs([]),
                  "wall_seconds": round(time.monotonic() - started, 3)}
    write_json(path, result)
    print(f"[{task['task_id']}][{arm}][seed={seed}] {result['status']} "
          f"execution={result['execution_success']} "
          f"llm={result['repair_cost']['logical_llm_calls']}", flush=True)
    return result


def run_arm(tasks: list[dict], arm: str, provider, outdir: Path,
            max_rounds: int, workers: int) -> list[dict]:
    def run(task: dict) -> dict:
        results = []
        for seed in SEEDS:
            case = outdir / task["task_id"] / f"seed_{seed}" / arm
            results.append(execute_task(task, arm, provider, case, case / "shared", seed, max_rounds))
        return results
    with ThreadPoolExecutor(max_workers=workers) as pool:
        nested = list(pool.map(run, tasks))
    return [result for group in nested for result in group]


def paired_metrics(control: list[dict], treatment: list[dict], asset: dict) -> dict:
    control_by_key = {(row["task_id"], row["seed"]): row for row in control}
    treatment_by_key = {(row["task_id"], row["seed"]): row for row in treatment}
    if set(control_by_key) != set(treatment_by_key) or not control_by_key:
        raise ValueError("unpaired or empty validation results")
    deltas = defaultdict(list)
    execution_harm = 0
    runner_errors = 0
    for key, baseline in control_by_key.items():
        candidate = treatment_by_key[key]
        runner_errors += baseline["status"] != "completed" or candidate["status"] != "completed"
        baseline_success = baseline["execution_success"]
        candidate_success = candidate["execution_success"]
        deltas[key[0]].append(float(candidate_success) - float(baseline_success))
        execution_harm += baseline_success and not candidate_success
    control_calls = sum(row["repair_cost"]["logical_llm_calls"] for row in control)
    treatment_calls = sum(row["repair_cost"]["logical_llm_calls"] for row in treatment)
    false_accepts = 0
    for row in treatment:
        final = row.get("final") or {}
        if final.get("accepted") and (row["problem_id"] not in REGISTERED_AUDIT_IDS
                                      or not (final.get("score") or {}).get("business_correct")):
            false_accepts += 1
    return {"n_problems": len(deltas), "n_pairs": len(control_by_key),
            "execution_gain": sum(sum(values) / len(values) for values in deltas.values()) / len(deltas),
            "execution_harm": int(execution_harm), "runner_errors": int(runner_errors),
            "false_business_accepts": int(false_accepts),
            "control_execution_successes": sum(row["execution_success"] for row in control),
            "treatment_execution_successes": sum(row["execution_success"] for row in treatment),
            "control_logical_llm_calls": control_calls, "treatment_logical_llm_calls": treatment_calls,
            "llm_call_reduction": (control_calls - treatment_calls) / max(control_calls, 1),
            **{f"{side}_{field}": sum(row["repair_cost"].get(field, 0) for row in rows)
               for side, rows in (("control", control), ("treatment", treatment))
               for field in ("new_llm_calls", "completion_tokens", "total_tokens", "llm_latency_s")},
            "guard_contract_passed": (validate_guard_contract(asset["guard"])["passed"]
                                      if asset["form"] == "guard" else None),
            "business_labels_complete": asset["kind"] == "execution"}


def write_validation_summary(registry: EvolvingMemoryRegistry, validation_dir: Path,
                             tier: str, tasks: list[dict], signature: str) -> None:
    summaries = {asset["asset_id"]: {"status": asset["status"],
                                     "metrics": asset["validations"][tier]["metrics"]}
                 for asset in registry.assets
                 if asset["signature"] == signature and tier in asset["validations"]}
    write_json(validation_dir / f"{tier}_summary.json",
               {"tier": tier, "tasks": [task["task_id"] for task in tasks], "assets": summaries})


def validate(outdir: Path, tier: str, workers: int) -> None:
    if tier not in {"dev", "gapcheck"}:
        raise ValueError("tier must be dev or gapcheck")
    registry = EvolvingMemoryRegistry(outdir / REGISTRY_NAME)
    expected = "candidate" if tier == "dev" else "dev_passed"
    signature = json.loads((outdir / "dev_cluster.json").read_text())["signature"]
    tasks = one_per_problem([task for task in split_tasks(tier) if task["signature"] == signature])
    validation_dir = outdir / f"validation_{tier}"
    assets = [asset for asset in registry.assets
              if asset["signature"] == signature and asset["status"] == expected]
    if not assets:
        write_validation_summary(registry, validation_dir, tier, tasks, signature)
        print(f"no assets require {tier} validation")
        return
    control = run_arm(tasks, "control", empty_provider, validation_dir, 2, workers)
    write_json(validation_dir / "control_results.json", control)
    for asset in assets:
        treatment = run_arm(tasks, asset["asset_id"], asset_provider(asset), validation_dir, 2, workers)
        write_json(validation_dir / f"{asset['asset_id']}_results.json", treatment)
        metrics = paired_metrics(control, treatment, asset)
        updated = registry.validate(asset["asset_id"], tier, metrics)
        print(asset["asset_id"], updated["status"], json.dumps(metrics), flush=True)
    write_validation_summary(registry, validation_dir, tier, tasks, signature)


def freeze(outdir: Path) -> None:
    registry = EvolvingMemoryRegistry(outdir / REGISTRY_NAME)
    manifest = registry.freeze(PROTOCOL, [ROOT / name for name in IMPLEMENTATION])
    write_json(outdir / "frozen_manifest.json", manifest)
    print(json.dumps({"promoted": manifest["promoted_asset_ids"],
                      "registry_sha256": manifest["registry_sha256"]}, indent=1))


def test_tasks(scope: str, signature: str) -> list[dict]:
    tasks = split_tasks("test")
    if scope == "targeted":
        return one_per_problem([task for task in tasks if task["signature"] == signature])
    if scope == "raw_selected":
        rows = {row["id"]: row for row in load_source()}
        return [build_task(rows[task["problem_id"]],
                           candidate_for(rows[task["problem_id"]],
                                         rows[task["problem_id"]]["selected_candidate"]))
                for task in one_per_problem(tasks)]
    raise ValueError("unknown test scope")


def summarize_test(control: list[dict], treatment: list[dict]) -> dict:
    references = question_rows()
    for row in control + treatment:
        final = row.get("final") or {}
        objective = final.get("objective")
        row["objective_match"] = bool(row["status"] == "completed" and isinstance(objective, (int, float))
                                      and abs(objective - float(references[row["problem_id"]]["en_answer"])) <= 0.1)
    dummy = {"kind": "execution", "form": "prompt", "guard": None}
    metrics = paired_metrics(control, treatment, dummy)
    control_by_key = {(row["task_id"], row["seed"]): row for row in control}
    objective_deltas = defaultdict(list)
    objective_harm = 0
    for row in treatment:
        baseline = control_by_key[(row["task_id"], row["seed"])]
        objective_deltas[row["task_id"]].append(float(row["objective_match"]) - float(baseline["objective_match"]))
        objective_harm += baseline["objective_match"] and not row["objective_match"]
    metrics.update({
        "control_objective_matches": sum(row["objective_match"] for row in control),
        "treatment_objective_matches": sum(row["objective_match"] for row in treatment),
        "objective_gain": sum(sum(values) / len(values) for values in objective_deltas.values())
        / len(objective_deltas),
        "objective_harm": int(objective_harm),
        "objective_gained_ids": sorted({row["problem_id"] for row in treatment if row["objective_match"]
                                        and not control_by_key[(row["task_id"], row["seed"])]["objective_match"]}),
        "objective_harmed_ids": sorted({row["problem_id"] for row in treatment if not row["objective_match"]
                                        and control_by_key[(row["task_id"], row["seed"])]["objective_match"]}),
        "control_new_llm_calls": sum(row["repair_cost"]["new_llm_calls"] for row in control),
        "treatment_new_llm_calls": sum(row["repair_cost"]["new_llm_calls"] for row in treatment),
        "control_completion_tokens": sum(row["repair_cost"]["completion_tokens"] for row in control),
        "treatment_completion_tokens": sum(row["repair_cost"]["completion_tokens"] for row in treatment),
    })
    return metrics


def test(outdir: Path, scope: str, workers: int) -> None:
    registry = EvolvingMemoryRegistry(outdir / REGISTRY_NAME)
    if not registry.frozen:
        raise RuntimeError("test requires a frozen registry")
    registry.verify_frozen_implementation()
    promoted = [asset for asset in registry.assets if asset["status"] == "promoted"]
    if not promoted:
        raise RuntimeError("no promoted assets; report the negative development result without deployment")
    signature = promoted[0]["signature"]
    tasks = test_tasks(scope, signature)
    out = outdir / f"test_{scope}"
    control = run_arm(tasks, "control", empty_provider, out, 3, workers)
    treatment = run_arm(tasks, "evolved", registry_provider(registry), out, 3, workers)
    write_json(out / "control_results.json", control)
    write_json(out / "evolved_results.json", treatment)
    summary = summarize_test(control, treatment)
    analysis = {"scope": scope, "n_tasks": len(tasks), "seeds": list(SEEDS),
                "task_ids": [task["task_id"] for task in tasks],
                "promoted_asset_ids": [asset["asset_id"] for asset in promoted],
                "summary": summary, "public_answer_used_for_selection": False,
                "exposure": "retrospective_frozen_repair_test_not_sealed"}
    write_json(out / "analysis.json", analysis)
    print(json.dumps(analysis, indent=1), flush=True)


def report(outdir: Path) -> None:
    dev = json.loads((outdir / "validation_dev" / "dev_summary.json").read_text())
    gap_path = outdir / "validation_gapcheck" / "gapcheck_summary.json"
    gap = json.loads(gap_path.read_text()) if gap_path.exists() else {"assets": {}}
    registry = json.loads((outdir / REGISTRY_NAME).read_text())
    test_analyses = {}
    for scope in ("targeted", "raw_selected"):
        path = outdir / f"test_{scope}" / "analysis.json"
        if path.exists():
            test_analyses[scope] = json.loads(path.read_text())
    status_counts = {}
    for asset in registry["assets"]:
        status_counts[asset["status"]] = status_counts.get(asset["status"], 0) + 1
    lines = ["# IndustryOR 工程 Memory 在线进化与冻结测试 v0.1", "",
             "**范围：回溯开发划分，不是 sealed test；冻结初始代码的 repair-only 对照，不是完整生成复现或 SOTA。**",
             "本报告只统计当前实验目录；任何早期中止的 pilot 都不进入指标。", "",
             f"资产状态：`{status_counts}`。dev={len(dev['tasks'])} 个目标任务，"
             f"gapcheck={len(gap.get('tasks', []))} 个目标任务；每个任务三个显式种子。", "",
             "## 资产生命周期与来源", "",
             "| asset | 形式 | parent | dev | gapcheck | 最终状态 |", "|---|---|---|---|---|---|"]
    for asset in registry["assets"]:
        validations = asset["validations"]
        dev_status = "通过" if validations.get("dev", {}).get("passed") else "拒绝"
        gap_status = ("通过" if validations.get("gapcheck", {}).get("passed")
                      else "拒绝" if "gapcheck" in validations else "未进入")
        lines.append(f"| {asset['asset_id']} | {asset['form']} | {asset['parent_id']} | "
                     f"{dev_status} | {gap_status} | {asset['status']} |")
        lines += ["", f"**{asset['asset_id']} 原文：** {asset['text']}", "",
                  f"来源：{asset['origin']['proposer']}；split={asset['origin']['split']}；"
                  f"trace_sha256=`{asset['origin']['trace_sha256']}`。"]
        for tier, validation in asset["validations"].items():
            if validation["reasons"]:
                lines.append(f"{tier} 拒绝原因：`{validation['reasons']}`。")
    lines += ["", "## dev / gapcheck 配对指标", "",
              "| tier | asset | 执行增益 | 执行误伤 | runner errors | 逻辑LLM调用下降 | 新调用 control→asset |",
              "|---|---|---:|---:|---:|---:|---:|"]
    for tier, payload in (("dev", dev), ("gapcheck", gap)):
        for asset_id, value in payload["assets"].items():
            metrics = value["metrics"]
            lines.append(f"| {tier} | {asset_id} | {metrics['execution_gain']:+.1%} | "
                         f"{metrics['execution_harm']} | {metrics['runner_errors']} | "
                         f"{metrics['llm_call_reduction']:.1%} | "
                         f"{metrics['control_new_llm_calls']}→{metrics['treatment_new_llm_calls']} |")
    for scope, analysis in test_analyses.items():
        metrics = analysis["summary"]
        lines += ["", f"## 冻结 test：{scope}", "",
                  f"任务数={analysis['n_tasks']}；每个任务三个种子，因此每组最多 {analysis['n_tasks'] * 3} 个输出。",
                  f"执行成功：control={metrics['control_execution_successes']}，evolved={metrics['treatment_execution_successes']}；"
                  f"宏增益={metrics['execution_gain']:+.1%}，paired execution harm={metrics['execution_harm']}。",
                  f"公开目标匹配：control={metrics['control_objective_matches']}，evolved={metrics['treatment_objective_matches']}；"
                  f"宏增益={metrics['objective_gain']:+.1%}，paired objective harm={metrics['objective_harm']}。",
                  f"改善 IDs={metrics['objective_gained_ids']}；损害 IDs={metrics['objective_harmed_ids']}。",
                  f"runner errors={metrics['runner_errors']}；独立业务误接受={metrics['false_business_accepts']}。",
                  f"逻辑修复 LLM 调用：{metrics['control_logical_llm_calls']}→{metrics['treatment_logical_llm_calls']}；"
                  f"新增调用：{metrics['control_new_llm_calls']}→{metrics['treatment_new_llm_calls']}；"
                  f"completion tokens：{metrics['control_completion_tokens']}→{metrics['treatment_completion_tokens']}。"]
    if not test_analyses:
        lines += ["", "## 冻结 test", "", "没有 promoted 资产或尚未执行部署测试，因此不报告部署收益。"]
    lines += ["", "## 解释边界", "",
              "只有 promoted 资产进入冻结测试；业务语义未经独立 Witness 的题仍未验证。",
              "执行恢复不等于业务正确，目标匹配只在测试结束后计算，不参与候选、晋升或节点选择。",
              "单机制结果不能外推为通用自进化有效；负结果不通过移动晋升阈值挽救。", "",
              f"机器制品：`{outdir}`；协议：`docs/paper/industryor_memory_evolution_protocol_v0.1.md`。", ""]
    (outdir / "report.md").write_text("\n".join(lines))
    destination = ROOT / "docs/paper/industryor_memory_evolution_results_v0.1.md"
    destination.write_text("\n".join(lines))
    write_json(ROOT / "docs/paper/figures/industryor_memory_evolution_v0.1.json",
               {"status_counts": status_counts, "dev": dev, "gapcheck": gap, "test": test_analyses})
    if test_analyses:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        scopes = list(test_analyses)
        fig, axes = plt.subplots(1, 2, figsize=(10, 4.3))
        for axis, metric, title in ((axes[0], "execution", "Execution successes"),
                                    (axes[1], "objective", "Objective matches (post-hoc)")):
            control_values = [test_analyses[scope]["summary"][f"control_{metric}_successes" if metric == "execution"
                                                             else "control_objective_matches"] for scope in scopes]
            evolved_values = [test_analyses[scope]["summary"][f"treatment_{metric}_successes" if metric == "execution"
                                                             else "treatment_objective_matches"] for scope in scopes]
            x = list(range(len(scopes)))
            bars1 = axis.bar([value - 0.18 for value in x], control_values, width=0.36, label="no memory")
            bars2 = axis.bar([value + 0.18 for value in x], evolved_values, width=0.36, label="evolved")
            axis.bar_label(bars1)
            axis.bar_label(bars2)
            axis.set_xticks(x, scopes)
            axis.set_title(title)
            axis.set_ylabel("Count across tasks × 3 seeds")
            axis.set_ylim(bottom=0)
        axes[0].legend()
        fig.tight_layout()
        figure = ROOT / "docs/paper/figures/industryor_memory_evolution_v0.1.png"
        figure.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(figure, dpi=170, bbox_inches="tight")
        plt.close(fig)
    print("report written")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "propose", "crystallize", "validate", "freeze", "test", "report"))
    parser.add_argument("--out", default="work/industryor_memory_evolution_v0.1")
    parser.add_argument("--tier", choices=("dev", "gapcheck"))
    parser.add_argument("--scope", choices=("targeted", "raw_selected"))
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    outdir = (ROOT / args.out).resolve()
    if args.command == "prepare":
        prepare(outdir)
    elif args.command == "propose":
        propose(outdir)
    elif args.command == "crystallize":
        crystallize(outdir)
    elif args.command == "validate":
        if not args.tier:
            parser.error("validate requires --tier")
        validate(outdir, args.tier, args.workers)
    elif args.command == "freeze":
        freeze(outdir)
    elif args.command == "test":
        if not args.scope:
            parser.error("test requires --scope")
        test(outdir, args.scope, args.workers)
    else:
        report(outdir)


if __name__ == "__main__":
    main()

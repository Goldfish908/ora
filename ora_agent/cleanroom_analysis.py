"""Per-task diagnostics and cost accounting for frozen clean-room evaluation."""
from __future__ import annotations

from pathlib import Path

from .oragentbench import evaluation_unknown, read_json

USAGE_KEYS = ("prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens")


def generation_cost(record: dict) -> dict:
    generation = Path(record["workspace"]).parent / "generation"
    responses = []
    for phase in ("model", "solver", "runtime_patch"):
        path = generation / f"{phase}_generation.json"
        if path.exists():
            responses.append(read_json(path).get("response") or {})
    cost = {"llm_calls": len(responses), "missing_usage_calls": 0,
            "llm_latency_seconds": 0.0, **{key: 0 for key in USAGE_KEYS}}
    for response in responses:
        usage = response.get("usage")
        if not usage:
            cost["missing_usage_calls"] += 1
            continue
        for key in USAGE_KEYS:
            if key == "reasoning_tokens":
                value = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
            else:
                value = usage.get(key) or 0
            cost[key] += int(value)
        cost["llm_latency_seconds"] += float(
            response.get("request_wall_s", response.get("latency_s", 0.0)) or 0.0)
    cost["llm_latency_seconds"] = round(cost["llm_latency_seconds"], 6)
    return cost


def failure_class(record: dict) -> str:
    if record.get("true_correct"):
        return "true_correct"
    if record.get("phantom_proxy"):
        return "phantom_proxy"
    official = record.get("official") or {}
    if evaluation_unknown(official):
        return "evaluation_unknown"
    if record.get("generation_error"):
        return "incomplete_artifact" if "incomplete_artifact" in record["generation_error"] \
            else "generation_failure"
    if (record.get("execution") or {}).get("return_code") != 0:
        return "execution_timeout" if (record.get("execution") or {}).get("timed_out") else "execution_error"
    reward_details = official.get("reward_details") or {}
    if reward_details.get("quality_status") == "missing_solution":
        return "missing_solution"
    if record.get("feasible"):
        return "quality_shortfall"
    if (official.get("evaluation") or {}).get("errors"):
        return "business_infeasible"
    return "evaluation_unknown"


def diagnose_record(record: dict, include_official_errors: bool = False) -> dict:
    keys = ("task", "split", "candidate_sha256", "attempt", "feasible", "quality",
            "true_correct", "objective", "proxy_match", "phantom_proxy")
    result = {key: record.get(key) for key in keys}
    result["failure_class"] = failure_class(record)
    result["execution_return_code"] = (record.get("execution") or {}).get("return_code")
    result["generation_error"] = record.get("generation_error")
    result["cost"] = generation_cost(record)
    result["execution_wall_seconds"] = (record.get("execution") or {}).get("wall_seconds")
    result["evaluation_wall_seconds"] = ((record.get("official") or {}).get("runner") or {}).get("wall_seconds")
    result["api_guard_repairs"] = len((record.get("api_guard") or {}).get("repairs") or [])
    result["public_contract_repairs"] = len((record.get("api_guard") or {}).get("public_contract_repairs") or [])
    stderr_path = Path(record["workspace"]).parent / "execution/stderr.txt"
    stderr = stderr_path.read_text(errors="replace") if stderr_path.exists() else ""
    result["stderr_tail"] = stderr.strip().splitlines()[-1][:1000] if stderr.strip() else None
    if include_official_errors:
        result["official_errors"] = ((record.get("official") or {}).get("evaluation") or {}).get("errors") or []
    return result


def summarize_records(records: list[dict], expected_tasks: int | None = None) -> dict:
    diagnostics = [diagnose_record(record) for record in records]
    n = len(records)
    expected = n if expected_tasks is None else expected_tasks
    cost = {"llm_calls": sum(row["cost"]["llm_calls"] for row in diagnostics),
            "missing_usage_calls": sum(row["cost"]["missing_usage_calls"] for row in diagnostics),
            "llm_latency_seconds": round(sum(row["cost"]["llm_latency_seconds"] for row in diagnostics), 6)}
    cost.update({key: sum(row["cost"][key] for row in diagnostics) for key in USAGE_KEYS})
    for key, label in (("execution_wall_seconds", "solver_execution_time"),
                       ("evaluation_wall_seconds", "official_evaluation_time")):
        timings = [float(row[key]) for row in diagnostics if row[key] is not None]
        cost[label] = {"recorded_calls": len(timings), "missing_calls": n - len(timings),
                       "seconds": round(sum(timings), 6) if timings else None}
    return {"n": n, "expected_tasks": expected, "coverage": n / expected if expected else 0.0,
            "feasible": sum(bool(row["feasible"]) for row in diagnostics),
            "proxy_match": sum(bool(row["proxy_match"]) for row in diagnostics),
            "true_correct": sum(bool(row["true_correct"]) for row in diagnostics),
            "phantom_proxy": sum(row["failure_class"] == "phantom_proxy" for row in diagnostics),
            "unknown": sum(row["failure_class"] == "evaluation_unknown" for row in diagnostics),
            "unresolved_non_phantom": sum(row["failure_class"] not in {"true_correct", "phantom_proxy"}
                                           for row in diagnostics),
            "mean_quality": sum(float(row["quality"] or 0) for row in diagnostics) / n if n else 0.0,
            "failure_counts": {kind: sum(row["failure_class"] == kind for row in diagnostics)
                               for kind in sorted({row["failure_class"] for row in diagnostics})},
            "api_guard_modified": sum(row["api_guard_repairs"] > 0 for row in diagnostics),
            "cost": cost, "tasks": diagnostics}


def pair_win_safe(before: list[dict], after: list[dict]) -> dict:
    before_by_task = {record["task"]: record for record in before}
    after_by_task = {record["task"]: record for record in after}
    if len(before_by_task) != len(before) or len(after_by_task) != len(after):
        raise ValueError("task ids must be unique within each arm")
    common = sorted(before_by_task.keys() & after_by_task.keys())
    gained, lost, phantom_gained, phantom_removed = [], [], [], []
    for task in common:
        old, new = before_by_task[task], after_by_task[task]
        if not old["true_correct"] and new["true_correct"]:
            gained.append(task)
        if old["true_correct"] and not new["true_correct"]:
            lost.append(task)
        if not old["phantom_proxy"] and new["phantom_proxy"]:
            phantom_gained.append(task)
        if old["phantom_proxy"] and not new["phantom_proxy"]:
            phantom_removed.append(task)
    missing = sorted(before_by_task.keys() ^ after_by_task.keys())
    return {"paired_tasks": len(common), "missing_tasks": missing,
            "gained_true_correct": gained, "lost_true_correct": lost,
            "gained_phantom": phantom_gained, "removed_phantom": phantom_removed,
            "win_safe": not lost and not missing}

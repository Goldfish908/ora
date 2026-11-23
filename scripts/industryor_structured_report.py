#!/usr/bin/env python3
"""Validate and report structured iterative, DAG and trigger-memory controls."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts.industryor_k3_pipeline import costs
from scripts.industryor_next_stage import score_solution
from ora_agent.structured_models import select_max_min

RUN = ROOT / "work/industryor_structured_dev_v0.2"
COST_KEYS = ("logical_llm_calls", "new_llm_calls", "api_attempts", "completion_tokens",
             "total_tokens", "llm_latency_s", "new_llm_latency_s")


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def shared_cost_audit(records: list[dict], saved: dict) -> dict:
    artifact = costs(records)
    for key in ("logical_llm_calls", "api_attempts", "completion_tokens", "total_tokens", "llm_latency_s"):
        assert artifact[key] == saved[key]
    for key in ("new_llm_calls", "new_llm_latency_s"):
        assert 0 <= saved[key] <= artifact[key]
    return {"artifact_cost": artifact,
            "reused_new_llm_calls": artifact["new_llm_calls"] - saved["new_llm_calls"],
            "reused_new_llm_latency_s": round(artifact["new_llm_latency_s"] - saved["new_llm_latency_s"], 3)}


def configured_protocol_sha256(config: dict, name: str) -> str:
    hashes = config["protocol_sha256"]
    return hashes[name] if isinstance(hashes, dict) else hashes


def validate(run: Path, require_complete: bool = True) -> dict:
    analysis = json.loads((run / "analysis.json").read_text())
    config = analysis["run_config"]
    assert config == json.loads((run / "run_config.json").read_text())
    assert "api_key" not in json.dumps(config)
    results = analysis["results"]
    assert len(results) == len(config["ids"]) * len(config["arms"])
    if require_complete:
        assert len(config["ids"]) == 100
        assert all(row["status"] == "completed" for row in results)
    snapshots = 0
    for name, expected in config["implementation_sha256"].items():
        path = run / "source" / name
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        snapshots += 1
    protocol_name = "docs/paper/industryor_full_chain_protocol_v0.1.md"
    protocol = run / "source" / protocol_name
    assert hashlib.sha256(protocol.read_bytes()).hexdigest() == configured_protocol_sha256(config, protocol_name)
    memory_records = []
    for path in (run / "shared_generations").rglob("*.json"):
        record = json.loads(path.read_text())
        memory_records.append(record)
        assert "en_answer" not in json.dumps(record["messages"])
    checked_scores = 0
    shared_reuse = {"problem_ids": [], "reused_llm_calls": 0, "reused_llm_latency_s": 0.0,
                    "artifact_unique_new_llm_calls": 0, "result_reported_new_llm_calls": 0}
    for row in results:
        case = run / f"prob_{row['id']:03d}"
        if row["status"] == "runner_error":
            continue
        candidates = row["candidates"]
        assert len(candidates) == 3
        selected, minima, _ = select_max_min(candidates)
        assert selected == row["selected_index"]
        assert minima == row["min_confidence"]
        assert row["public_answer_used_for_selection"] is False
        if row["final_solution"] is not None and row["id"] in (4, 8, 9, 19, 20, 21, 25, 48):
            assert row["final_score"] == score_solution(row["id"], row["final_solution"])
            checked_scores += 1
        records = []
        for index in range(3):
            model_record = json.loads((case / f"model_{index}.json").read_text())
            evaluation_record = json.loads((case / f"evaluation_{index}.json").read_text())
            assert model_record["request"] == {"temperature": 0.6, "max_tokens": 32768,
                                               "reasoning_effort": "medium"}
            assert evaluation_record["request"] == {"temperature": 0.2, "max_tokens": 16384,
                                                    "reasoning_effort": "medium"}
            model_prompt_text = model_record["messages"][0]["content"]
            evaluation_prompt_text = evaluation_record["messages"][0]["content"]
            assert "en_answer" not in json.dumps(model_record["messages"])
            assert "en_answer" not in json.dumps(evaluation_record["messages"])
            assert json.dumps(candidates[index]["model"], ensure_ascii=False, indent=1) in evaluation_prompt_text
            if index == 0:
                assert "Generate the first formulation." in model_prompt_text
            else:
                history = [{"model": candidates[previous]["model"],
                            "evaluation": candidates[previous]["evaluation"]} for previous in range(index)]
                assert "Generate a revised formulation" in model_prompt_text
                assert json.dumps(history, ensure_ascii=False, indent=1) in model_prompt_text
            records.extend([model_record, evaluation_record])
        first_code = candidates[0]["candidate_id"]
        first_code_record = json.loads((case / f"code_{first_code}.json").read_text())
        assert first_code_record["request"] == {"temperature": 0.6, "max_tokens": 32768,
                                                "reasoning_effort": "medium"}
        assert "en_answer" not in json.dumps(first_code_record["messages"])
        assert json.dumps(candidates[0]["model"], ensure_ascii=False, indent=1) in first_code_record["messages"][0]["content"]
        records.append(first_code_record)
        binding = case / f"execution_{first_code}/binding.json"
        if binding.exists():
            records.append(json.loads(binding.read_text()))
        if row["selected_index"] != 0:
            selected_id = candidates[row["selected_index"]]["candidate_id"]
            selected_code_record = json.loads((case / f"code_{selected_id}.json").read_text())
            assert selected_code_record["request"] == {"temperature": 0.6, "max_tokens": 32768,
                                                       "reasoning_effort": "medium"}
            assert "en_answer" not in json.dumps(selected_code_record["messages"])
            assert json.dumps(candidates[row["selected_index"]]["model"], ensure_ascii=False, indent=1) \
                in selected_code_record["messages"][0]["content"]
            records.append(selected_code_record)
            binding = case / f"execution_{selected_id}/binding.json"
            if binding.exists():
                records.append(json.loads(binding.read_text()))
        shared_audit = shared_cost_audit(records, row["shared_cost"])
        if row["arm"] == "structured":
            shared_reuse["artifact_unique_new_llm_calls"] += shared_audit["artifact_cost"]["new_llm_calls"]
            shared_reuse["result_reported_new_llm_calls"] += row["shared_cost"]["new_llm_calls"]
            if shared_audit["reused_new_llm_calls"]:
                shared_reuse["problem_ids"].append(row["id"])
                shared_reuse["reused_llm_calls"] += shared_audit["reused_new_llm_calls"]
                shared_reuse["reused_llm_latency_s"] += shared_audit["reused_new_llm_latency_s"]
        for key in COST_KEYS:
            expected = row["shared_cost"][key] + row["repair_cost"][key]
            if key.endswith("_latency_s"):
                assert math.isclose(row["cost"][key], expected, rel_tol=0.0, abs_tol=0.001001)
            else:
                assert row["cost"][key] == expected
        max_candidate_rounds = config.get("max_candidate_rounds", 3)
        if row.get("memory_applied", False):
            assert row["dag"] and row["dag"]["nodes"]
            candidate_snapshots = [node["snapshot"] for node in row["dag"]["nodes"] if node.get("snapshot")]
            assert any(row["memory"]["text"] in message["content"]
                       and any(snapshot in message["content"] for snapshot in candidate_snapshots)
                       for record in memory_records for message in record["messages"])
        if row["dag"]:
            nodes = row["dag"]["nodes"]
            assert len(nodes) <= 6
            assert max(node["depth"] for node in nodes) <= max_candidate_rounds - 1
            assert row.get("candidate_rounds", 1) <= max_candidate_rounds
            assert row["dag"]["total_solver_runs"] <= 4
            assert row["dag"]["total_llm_calls"] <= 2 * (max_candidate_rounds - 1)
            for accepted_id in row["dag"]["accepted_node_ids"]:
                accepted = next(node for node in nodes if node["node_id"] == accepted_id)
                assert accepted["business_audit"]["business_correct"] is True
                assert accepted["binding_status"] == "validated"
            if row["selection_method"] == "execution_recovered_business_unverified":
                assert row["business_unverified"] is True
                selected_id = row.get("selected_node_id")
                selected_nodes = [node for node in nodes
                                  if node["node_id"] == selected_id] if selected_id else [
                                      node for node in nodes if node.get("snapshot") == row["selected_code"]]
                assert selected_nodes
                assert any(node["execution"].get("exec_status") == "ok"
                           and node["execution"].get("solver_status") == "optimal"
                           and (node["execution"].get("solution") or {}).get("solution_count", 0) >= 1
                           and ((node["execution"].get("solution") or {}).get("export") or {}).get("complete") is True
                           and math.isfinite((node["execution"].get("solution") or {})["objective"])
                           for node in selected_nodes)
    shared_reuse["reused_llm_latency_s"] = round(shared_reuse["reused_llm_latency_s"], 3)
    return {"results": len(results), "source_snapshots_verified": snapshots,
            "business_scores_recomputed": checked_scores, "shared_cache_reuse": shared_reuse,
            "iterative_prompt_pairs_verified": 2 * len({row["id"] for row in results
                                                         if row["status"] == "completed"}),
            "request_budget": {"formulation_candidates": 3, "model_max_tokens": 32768,
                               "evaluation_max_tokens": 16384, "code_max_tokens": 32768,
                               "reasoning_effort": "medium", "max_candidate_rounds": max_candidate_rounds,
                               "max_repair_generations": max_candidate_rounds - 1,
                               "dag_max_nodes": 6, "dag_max_depth": max_candidate_rounds - 1,
                               "dag_max_solver_runs": 4,
                               "dag_max_llm_calls_including_rebinding": 2 * (max_candidate_rounds - 1)},
            "analysis_sha256": hashlib.sha256((run / "analysis.json").read_bytes()).hexdigest()}


def paired_metrics(results: list[dict], arms: list[str]) -> dict:
    by_arm = {arm: {row["id"]: row for row in results if row["arm"] == arm} for arm in arms}
    metrics = {}
    for arm, rows_by_id in by_arm.items():
        rows = list(rows_by_id.values())
        completed = [row for row in rows if row["status"] == "completed"]
        schema_error_taxonomy = {}
        for row in completed:
            for candidate in row["candidates"]:
                for error in candidate["schema_errors"]:
                    if error.startswith("JSONDecodeError:"):
                        kind = "JSONDecodeError"
                    elif error.startswith("ValueError:"):
                        kind = "ValueError"
                    elif "source is not verbatim problem text" in error:
                        kind = "source_not_verbatim"
                    elif error == "no valid confidence scores":
                        kind = "no_valid_confidence_scores"
                    elif "missing" in error:
                        kind = "missing_required_field"
                    else:
                        kind = "other"
                    schema_error_taxonomy[kind] = schema_error_taxonomy.get(kind, 0) + 1
        pairs = [(by_arm["structured"][problem_id], row)
                 for problem_id, row in rows_by_id.items()
                 if problem_id in by_arm.get("structured", {})
                 and row["status"] == "completed" and by_arm["structured"][problem_id]["status"] == "completed"]
        baseline_wins = sum(base["match"] for base, _ in pairs)
        baseline_business_wins = sum(base["business_correct"] for base, _ in pairs)
        metrics[arm] = {
            "runner_errors": sum(row["status"] == "runner_error" for row in rows),
            "invalid_formulation_candidates": sum(bool(candidate["schema_errors"]) for row in completed
                                                   for candidate in row["candidates"]),
            "formulation_schema_errors": sum(len(candidate["schema_errors"]) for row in completed
                                              for candidate in row["candidates"]),
            "formulation_schema_error_taxonomy": schema_error_taxonomy,
            "no_valid_candidate_fallback_ids": [row["id"] for row in completed
                                                 if row["selection_method"] == "no_valid_candidate_fallback_first"],
            "selected_with_schema_errors_ids": [row["id"] for row in completed
                                                 if row["candidates"][row["selected_index"]]["schema_errors"]],
            "revision_steps": 2 * len(completed),
            "changed_revision_steps": sum(row["candidates"][index]["model"] != row["candidates"][index - 1]["model"]
                                           for row in completed for index in (1, 2)),
            "duplicate_revision_ids": [f"{row['id']}:M{index + 1}" for row in completed for index in (1, 2)
                                       if row["candidates"][index]["model"] == row["candidates"][index - 1]["model"]],
            "selector_improved": sum(row["match"] and not row["first_match"] for row in completed),
            "selector_harmed": sum(row["first_match"] and not row["match"] for row in completed),
            "selector_business_improved": sum(row["business_correct"] and not row["first_business_correct"]
                                               for row in completed),
            "selector_business_harmed": sum(row["first_business_correct"] and not row["business_correct"]
                                             for row in completed),
            "paired_n": len(pairs),
            "structured_baseline_wins": baseline_wins,
            "objective_wins_preserved": sum(base["match"] and row["match"] for base, row in pairs),
            "objective_wins_gained": sum(not base["match"] and row["match"] for base, row in pairs),
            "objective_wins_lost": sum(base["match"] and not row["match"] for base, row in pairs),
            "structured_baseline_business_wins": baseline_business_wins,
            "business_wins_preserved": sum(base["business_correct"] and row["business_correct"]
                                            for base, row in pairs),
            "business_wins_gained": sum(not base["business_correct"] and row["business_correct"]
                                         for base, row in pairs),
            "business_wins_lost": sum(base["business_correct"] and not row["business_correct"]
                                       for base, row in pairs),
            "false_business_accepts": sum(bool(row["business_correct"]) and
                                          (row["business_unverified"] or not (row.get("final_score") or {}).get(
                                              "business_correct", False)) for row in completed),
            "business_objective_disagreements": sum(not row["business_unverified"] and
                                                    bool(row["business_correct"]) != bool(row["match"])
                                                    for row in completed),
            "memory_applied": sum(bool(row.get("memory_applied")) for row in completed),
            "logical_scip_runs": sum(1 + int(row["selected_index"] != 0)
                                     + ((row.get("dag") or {}).get("total_solver_runs", 0))
                                     for row in completed),
            "execution_recovery_ids": [row["id"] for row in completed
                                       if row["selection_method"] == "execution_recovered_business_unverified"],
            "max_candidate_rounds_used": max((row.get("candidate_rounds", 1) for row in completed), default=0),
            "repair_generation_calls": sum(row["repair_cost"]["logical_llm_calls"] for row in completed),
            "stop_reasons": {reason: sum(row.get("stop_reason") == reason for row in completed)
                             for reason in sorted({row.get("stop_reason") for row in completed
                                                   if row.get("stop_reason")})},
        }
    return metrics


def compare_arms(results: list[dict], baseline_arm: str, current_arm: str) -> dict:
    baseline = {row["id"]: row for row in results if row["arm"] == baseline_arm}
    current = {row["id"]: row for row in results if row["arm"] == current_arm}
    pairs = [(baseline[problem_id], row) for problem_id, row in current.items()
             if problem_id in baseline and row["status"] == "completed"
             and baseline[problem_id]["status"] == "completed"]
    baseline_wins = sum(base["match"] for base, _ in pairs)
    baseline_business_wins = sum(base["business_correct"] for base, _ in pairs)
    return {
        "paired_n": len(pairs),
        "baseline_objective_wins": baseline_wins,
        "objective_wins_preserved": sum(base["match"] and row["match"] for base, row in pairs),
        "objective_gained_ids": [base["id"] for base, row in pairs if not base["match"] and row["match"]],
        "objective_lost_ids": [base["id"] for base, row in pairs if base["match"] and not row["match"]],
        "changed_objective_ids": [base["id"] for base, row in pairs if base.get("objective") != row.get("objective")],
        "baseline_business_wins": baseline_business_wins,
        "business_wins_preserved": sum(base["business_correct"] and row["business_correct"] for base, row in pairs),
        "business_gained_ids": [base["id"] for base, row in pairs
                                if not base["business_correct"] and row["business_correct"]],
        "business_lost_ids": [base["id"] for base, row in pairs
                              if base["business_correct"] and not row["business_correct"]],
    }


def failure_attribution(results: list[dict], arms: list[str]) -> dict:
    attribution = {}
    for arm in arms:
        rows = [row for row in results if row["arm"] == arm]
        attribution[arm] = {
            "runner_error_ids": [row["id"] for row in rows if row["status"] == "runner_error"],
            "no_objective_ids": [row["id"] for row in rows
                                 if row["status"] == "completed" and row.get("objective") is None],
            "registered_business_rejected_ids": [row["id"] for row in rows if row["status"] == "completed"
                                                  and not row["business_unverified"] and not row["business_correct"]],
            "public_mismatch_with_objective_ids": [row["id"] for row in rows if row["status"] == "completed"
                                                    and row.get("objective") is not None and not row["match"]],
        }
    return attribution


def build_report(run: Path = RUN, report_path: Path = ROOT / "docs/paper/industryor_structured_results_v0.1.md",
                 figure_dir: Path = ROOT / "docs/paper/figures", require_complete: bool = True):
    run = run.resolve()
    analysis = json.loads((run / "analysis.json").read_text())
    summary = analysis["summary"]
    validation = validate(run, require_complete)
    arms = analysis["run_config"]["arms"]
    n = analysis["summary"]["n_problems"]
    paired = paired_metrics(analysis["results"], arms)
    memory_deltas = {arm: compare_arms(analysis["results"], "structured_dag", arm)
                     for arm in arms if arm not in {"structured", "structured_dag"}}
    failures = failure_attribution(analysis["results"], arms)
    audit_n = sum(row["status"] == "completed" and not row["business_unverified"]
                  for row in analysis["results"] if row["arm"] == "structured")
    raw = json.loads((ROOT / "work/industryor_k3_dev_v0.1/analysis.json").read_text())["summary"]
    lines = ["# IndustryOR 全链路结构化迭代、DAG 与 Memory", "",
             f"**范围：{n} 题，开发性新采样，不是 held-out。** COOPA-inspired，不是官方 COOPA runner。", "",
             "**预算：** 每题顺序生成 3 个 formulation 和 3 份置信评估；model/code/repair 的 temperature=0.6，evaluation=0.2，reasoning_effort=medium；model/code/repair max_tokens=32768，evaluation=16384。代码只生成 M1 与 max-min 选中候选；每个 DAG 臂最多 6 nodes、3 个候选轮次（首轮 + 最多两次修复）、4 次 SCIP、2 次修复生成，另允许 2 次重新绑定（DAG 总 LLM 调用不超过 4）。控制器逐轮决策，报告核验真实节点、输出连接和预算。",
             "", "## 全链路结果", "",
             "| 臂 | M1 匹配 | 最终匹配 | M1 业务正确（注册题） | 最终业务正确（注册题） | runner errors |",
             "|---|---:|---:|---:|---:|---:|"]
    for arm in arms:
        arm_summary = summary["arms"][arm]
        lines.append(f"| {arm} | {arm_summary['first_matches']} | {arm_summary['selected_matches']} | {arm_summary['first_business_correct']} | {arm_summary['business_correct']} | {paired[arm]['runner_errors']} |")
    lines.extend(["", f"独立业务审计分母为 {audit_n} 个已完成注册题；其余题仍是 `business_unverified`，不计入业务正确率分母。", "",
                  "## 配对增量、win 保留与验收纪律", "",
                  "| 臂 | 配对 n | 目标 win 保留 | 目标新增/丢失 | 业务 win 保留 | 业务新增/丢失 | 误接受 | memory 实际应用 | 逻辑 SCIP runs |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for arm in arms:
        metric = paired[arm]
        lines.append(f"| {arm} | {metric['paired_n']} | {metric['objective_wins_preserved']}/{metric['structured_baseline_wins']} | {metric['objective_wins_gained']}/{metric['objective_wins_lost']} | {metric['business_wins_preserved']}/{metric['structured_baseline_business_wins']} | {metric['business_wins_gained']}/{metric['business_wins_lost']} | {metric['false_business_accepts']} | {metric['memory_applied']} | {metric['logical_scip_runs']} |")
    selector = paired["structured"]
    lines.extend(["",
                  f"max-min 相对 M1：公开目标改善 {selector['selector_improved']}、损害 {selector['selector_harmed']}；独立业务改善 {selector['selector_business_improved']}、损害 {selector['selector_business_harmed']}。净变化不能只看 oracle 候选池。",
                  f"结构化候选中有 {selector['invalid_formulation_candidates']} 个带 schema/source 错误（共 {selector['formulation_schema_errors']} 条，类型={selector['formulation_schema_error_taxonomy']}）；无有效候选回退 IDs={selector['no_valid_candidate_fallback_ids']}，选中候选仍带错误 IDs={selector['selected_with_schema_errors_ids']}。目标匹配不能抵消这些生成失败。",
                  f"M2/M3 共 {selector['revision_steps']} 个修订步骤，其中 {selector['changed_revision_steps']} 个改变了 formulation；重复修订={selector['duplicate_revision_ids']}。validator 已逐份核验前序模型与评估确实进入下一轮 prompt。",
                  "误接受指最终声称业务正确、但题目未注册独立审计或独立评分未通过；业务正确与公开目标不一致另记为 disagreement，不擅自判定哪一方错误。"])
    for arm in arms:
        if arm == "structured":
            continue
        metric = paired[arm]
        lines.append(f"{arm}：执行恢复输出 IDs={metric['execution_recovery_ids']}；最大候选轮次={metric['max_candidate_rounds_used']}；repair 生成/绑定调用={metric['repair_generation_calls']}；停止原因={metric['stop_reasons']}。执行恢复只表示完整 optimal 输出进入最终结果，不表示独立业务正确。")
    if memory_deltas:
        lines.extend(["", "## Memory 相对纯 DAG 的配对增量", "",
                      "| 臂 | 配对 n | 目标 win 保留 | 目标新增/丢失 | 业务 win 保留 | 业务新增/丢失 | 目标值改变 IDs |",
                      "|---|---:|---:|---:|---:|---:|---|"])
        for arm, delta in memory_deltas.items():
            lines.append(f"| {arm} | {delta['paired_n']} | {delta['objective_wins_preserved']}/{delta['baseline_objective_wins']} | {len(delta['objective_gained_ids'])}/{len(delta['objective_lost_ids'])} | {delta['business_wins_preserved']}/{delta['baseline_business_wins']} | {len(delta['business_gained_ids'])}/{len(delta['business_lost_ids'])} | {delta['changed_objective_ids']} |")
        lines.append("只有相对 structured_dag 的新增才算 memory 的独立贡献；纯 DAG 已修复的题不重复归因给 memory。")
    lines.extend(["", "## 成本", "",
                  "| 臂 | 逻辑 LLM 调用 | 结果记录新增调用 | API attempts | completion tokens | 总 tokens | LLM 延迟(s) | 结果记录新增延迟(s) |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"])
    for arm in arms:
        cost = summary["arms"][arm]["cost"]
        lines.append(f"| {arm} | {cost['logical_llm_calls']} | {cost['new_llm_calls']} | {cost['api_attempts']} | {cost['completion_tokens']} | {cost['total_tokens']} | {cost['llm_latency_s']} | {cost['new_llm_latency_s']} |")
    cache = validation["shared_cache_reuse"]
    lines.extend(["",
                  f"共享候选断点缓存：原始唯一新增调用={cache['artifact_unique_new_llm_calls']}，各结果复用后记录新增={cache['result_reported_new_llm_calls']}，复用={cache['reused_llm_calls']} 次、复用延迟={cache['reused_llm_latency_s']}s，IDs={cache['problem_ids']}。新增调用是各次结果生成时的口径，不冒充整个断点实验的唯一请求总量。",
                  "", "## 基线与解释", "",
                  f"raw k=1={raw['k1_matches']}/100，raw k=3 selected={raw['k3_selected_matches']}/100，raw oracle={raw['k3_oracle_matches_not_deployable']}/100。历史 z2=74，上一轮完整管线=70，COOPA 公开参考=76。",
                  "这些结果的模型、采样和机制不同，不能仅凭一次超过某条线就声称 SOTA。结构化臂比较 M1 与 max-min；DAG 与 memory 的增量另列，不以 oracle 代替最终输出。",
                  "", "## 失败归因（ID 清单）", "", "```json",
                  json.dumps(failures, ensure_ascii=False, indent=1), "```",
                  "", "## 逐题结构化迭代与修复", "",
                  "| ID | 选择 index | M1 objective | " + " | ".join(f"{arm} objective" for arm in arms)
                  + " | full 业务正确 | full memory 应用 |",
                  "|---:|---:|---:|" + "---:|" * len(arms) + "---|---|"])
    for problem_id in analysis["run_config"]["ids"]:
        rows = [row for row in analysis["results"] if row["id"] == problem_id]
        by_arm = {row["arm"]: row for row in rows}
        structured = by_arm["structured"]
        final = by_arm[arms[-1]]
        objectives = " | ".join(str(by_arm[arm].get("objective", "ERROR")) for arm in arms)
        lines.append(f"| {problem_id} | {structured.get('selected_index', 'ERROR')} | {structured.get('first_objective', 'ERROR')} | {objectives} | {final.get('business_correct', 'ERROR')} | {final.get('memory_applied', False)} |")
    lines.extend(["", "## 可追溯性与限制", "",
                  f"- 核验 {validation['results']} 条臂结果、{validation['business_scores_recomputed']} 份独立业务评分和 {validation['source_snapshots_verified']} 份执行源码快照。",
                  "- M2/M3 必须读取此前低置信维度；M1 与选中 formulation 的代码生成共享，不重复采样。",
                  "- 92 个未注册题保持 `business_unverified`。无接受分支时不使用参考答案或裸目标值挽救。",
                  "- memory 是只读静态资产；只有实际进入重生成时才计作应用，full 与 trigger 的调用、token 和失败均保留。",
                  "- 逻辑 SCIP runs 包含首候选、不同的选中候选及 DAG 执行节点；共享 LLM 缓存按逻辑调用与实际新增调用分别报告。",
                  "", f"机器结果：`{run.relative_to(ROOT)}/analysis.json`；manifest：`{run.relative_to(ROOT)}/manifest.json`。", ""])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines))
    labels = [arm.replace("structured_", "") for arm in arms]
    values = [summary["arms"][arm]["selected_matches"] for arm in arms]
    business = [summary["arms"][arm]["business_correct"] for arm in arms]
    calls = [summary["arms"][arm]["cost"]["logical_llm_calls"] for arm in arms]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    bars = axes[0].bar(labels, values, color="#2563eb")
    for bar, value in zip(bars, values):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + n * 0.015, str(value), ha="center", fontsize=8)
    axes[0].set_ylim(0, n * 1.15)
    axes[0].set_ylabel("Objective matches")
    axes[0].set_title(f"Full-chain selected outputs (n={n})")
    bars = axes[1].bar(labels, business, color="#059669")
    for bar, value in zip(bars, business):
        axes[1].text(bar.get_x() + bar.get_width() / 2, value + 0.1, str(value), ha="center", fontsize=8)
    axes[1].set_ylabel("Independently business-correct")
    axes[1].set_title(f"Registered business audit (n={audit_n})")
    bars = axes[2].bar(labels, calls, color="#f59e0b")
    for bar, value in zip(bars, calls):
        axes[2].text(bar.get_x() + bar.get_width() / 2, value + 0.5, str(value), ha="center", fontsize=8)
    axes[2].set_ylabel("Logical LLM calls")
    axes[2].set_title("Cost is reported, not hidden")
    fig.text(0.5, 0.025,
             "COOPA-inspired development replay; shared structured candidates. "
             "No reference-answer selection, online memory evolution or held-out claim.",
             ha="center", fontsize=9, color="#444444")
    fig.tight_layout(rect=(0, 0.10, 1, 0.95))
    figure_dir.mkdir(parents=True, exist_ok=True)
    image = figure_dir / "industryor_structured_v0.1.png"
    fig.savefig(image, dpi=170, bbox_inches="tight")
    plt.close(fig)
    data = {"scope": "development_not_heldout", "arms": summary["arms"], "paired_metrics": paired,
            "memory_vs_structured_dag": memory_deltas, "failure_attribution": failures, "validation": validation,
            "claims": {"sota": False, "official_coopa_runner": False, "online_memory_evolution": False},
            "sources": [f"{run.relative_to(ROOT)}/analysis.json", f"{run.relative_to(ROOT)}/manifest.json"]}
    data_path = figure_dir / "industryor_structured_v0.1.json"
    write_json(data_path, data)
    return report_path, image, data_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=RUN)
    parser.add_argument("--report", type=Path, default=ROOT / "docs/paper/industryor_structured_results_v0.1.md")
    parser.add_argument("--figure-dir", type=Path, default=ROOT / "docs/paper/figures")
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    paths = build_report(args.run, args.report, args.figure_dir, not args.allow_partial)
    print(json.dumps({"report": str(paths[0]), "figure": str(paths[1]), "data": str(paths[2])}, indent=1))


if __name__ == "__main__":
    main()

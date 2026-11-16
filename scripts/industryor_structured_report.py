#!/usr/bin/env python3
"""Validate and report structured iterative, DAG and trigger-memory controls."""
from __future__ import annotations

import argparse
import hashlib
import json
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
    protocol = run / "source/docs/paper/industryor_full_chain_protocol_v0.1.md"
    assert hashlib.sha256(protocol.read_bytes()).hexdigest() == config["protocol_sha256"]
    memory_records = []
    for path in (run / "shared_generations").rglob("*.json"):
        record = json.loads(path.read_text())
        memory_records.append(record)
        assert "en_answer" not in json.dumps(record["messages"])
    checked_scores = 0
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
            records.extend([json.loads((case / f"model_{index}.json").read_text()),
                            json.loads((case / f"evaluation_{index}.json").read_text())])
        first_code = candidates[0]["candidate_id"]
        records.append(json.loads((case / f"code_{first_code}.json").read_text()))
        binding = case / f"execution_{first_code}/binding.json"
        if binding.exists():
            records.append(json.loads(binding.read_text()))
        if row["selected_index"] != 0:
            selected_id = candidates[row["selected_index"]]["candidate_id"]
            records.append(json.loads((case / f"code_{selected_id}.json").read_text()))
            binding = case / f"execution_{selected_id}/binding.json"
            if binding.exists():
                records.append(json.loads(binding.read_text()))
        assert costs(records) == row["shared_cost"]
        for key in COST_KEYS:
            assert row["cost"][key] == row["shared_cost"][key] + row["repair_cost"][key]
        if row.get("memory_applied", False):
            assert any(row["memory"]["text"] in message["content"]
                       for record in memory_records for message in record["messages"])
        if row["dag"]:
            for accepted_id in row["dag"]["accepted_node_ids"]:
                accepted = next(node for node in row["dag"]["nodes"] if node["node_id"] == accepted_id)
                assert accepted["business_audit"]["business_correct"] is True
                assert accepted["binding_status"] == "validated"
    return {"results": len(results), "source_snapshots_verified": snapshots,
            "business_scores_recomputed": checked_scores,
            "analysis_sha256": hashlib.sha256((run / "analysis.json").read_bytes()).hexdigest()}


def build_report(run: Path = RUN, report_path: Path = ROOT / "docs/paper/industryor_structured_results_v0.1.md",
                 figure_dir: Path = ROOT / "docs/paper/figures", require_complete: bool = True):
    run = run.resolve()
    analysis = json.loads((run / "analysis.json").read_text())
    summary = analysis["summary"]
    validation = validate(run, require_complete)
    arms = analysis["run_config"]["arms"]
    n = analysis["summary"]["n_problems"]
    raw = json.loads((ROOT / "work/industryor_k3_dev_v0.1/analysis.json").read_text())["summary"]
    lines = ["# IndustryOR 全链路结构化迭代、DAG 与 Memory", "",
             f"**范围：{n} 题，开发性新采样，不是 held-out。** COOPA-inspired，不是官方 COOPA runner。", "",
             "## 全链路结果", "",
             "| 臂 | M1 匹配 | 最终匹配 | M1 业务正确 | 最终业务正确 | 逻辑 LLM 调用 | 总 tokens |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for arm in arms:
        arm_summary = summary["arms"][arm]
        lines.append(f"| {arm} | {arm_summary['first_matches']} | {arm_summary['selected_matches']} | {arm_summary['first_business_correct']} | {arm_summary['business_correct']} | {arm_summary['cost']['logical_llm_calls']} | {arm_summary['cost']['total_tokens']} |")
    lines.extend(["", "## 基线与解释", "",
                  f"raw k=1={raw['k1_matches']}/100，raw k=3 selected={raw['k3_selected_matches']}/100，raw oracle={raw['k3_oracle_matches_not_deployable']}/100。历史 z2=74，上一轮完整管线=70，COOPA 公开参考=76。",
                  "这些结果的模型、采样和机制不同，不能仅凭一次超过某条线就声称 SOTA。结构化臂比较 M1 与 max-min；DAG 与 memory 的增量另列，不以 oracle 代替最终输出。",
                  "", "## 逐题结构化迭代与修复", "",
                  "| ID | 选择 index | M1 objective | structured objective | DAG/trigger/full objective | 最终业务正确 | memory 应用 |",
                  "|---:|---|---:|---:|---:|---|---|"])
    for problem_id in analysis["run_config"]["ids"]:
        rows = [row for row in analysis["results"] if row["id"] == problem_id]
        structured = next(row for row in rows if row["arm"] == "structured")
        final = rows[-1]
        selected_index = structured.get("selected_index", "ERROR")
        first_objective = structured.get("first_objective", "ERROR")
        selected_objective = structured.get("objective", "ERROR")
        final_objective = final.get("objective", "ERROR")
        final_business = final.get("business_correct", "ERROR")
        memory_applied = final.get("memory_applied", False)
        lines.append(f"| {problem_id} | {selected_index} | {first_objective} | {selected_objective} | {final_objective} | {final_business} | {memory_applied} |")
    lines.extend(["", "## 可追溯性与限制", "",
                  f"- 核验 {validation['results']} 条臂结果、{validation['business_scores_recomputed']} 份独立业务评分和 {validation['source_snapshots_verified']} 份执行源码快照。",
                  "- M2/M3 必须读取此前低置信维度；M1 与选中 formulation 的代码生成共享，不重复采样。",
                  "- 92 个未注册题保持 `business_unverified`。无接受分支时不使用参考答案或裸目标值挽救。",
                  "- memory 是只读静态资产；只有实际进入重生成时才计作应用，full 与 trigger 的调用、token 和失败均保留。",
                  "", f"机器结果：`{run.relative_to(ROOT)}/analysis.json`；manifest：`{run.relative_to(ROOT)}/manifest.json`。", ""])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines))
    labels = ["M1" if arm == "structured" else arm.replace("structured_", "") for arm in arms]
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
    data = {"scope": "development_not_heldout", "arms": summary["arms"], "validation": validation,
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

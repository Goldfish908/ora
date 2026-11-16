#!/usr/bin/env python3
"""Validate and report the fixed-initial semantic-binding and DAG controls."""
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

from scripts.industryor_next_stage import score_solution

RUN = ROOT / "work/industryor_semantic_dag_dev_v0.1"
BINDINGS = ROOT / "work/industryor_semantic_inner8_dev_v0.1"
SOURCE = ROOT / "work/industryor_full_qwen_v0.1"
ARMS = ("bind_only", "single_line", "branch_dag")


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def validate(run: Path = RUN) -> dict:
    analysis = json.loads((run / "analysis.json").read_text())
    config = analysis["run_config"]
    assert config == json.loads((run / "run_config.json").read_text())
    assert "api_key" not in json.dumps(config)
    results = analysis["results"]
    assert len(results) == len(config["ids"]) * len(ARMS)
    assert {(row["id"], row["arm"]) for row in results} == {
        (problem_id, arm) for problem_id in config["ids"] for arm in ARMS}
    snapshots = 0
    for name, expected in config["implementation_sha256"].items():
        path = run / "source" / name
        assert path.is_file(), name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        snapshots += 1
    protocol = run / "source/docs/paper/industryor_semantic_inner_protocol_v0.1.md"
    assert hashlib.sha256(protocol.read_bytes()).hexdigest() == config["protocol_sha256"]
    checked_scores = 0
    for problem_id in config["ids"]:
        source_result = json.loads((SOURCE / f"prob_{problem_id:03d}/result.json").read_text())
        shared = json.loads((run / f"shared/prob_{problem_id:03d}/root.json").read_text())
        if shared["solution"] is not None:
            assert shared["score"] == score_solution(problem_id, shared["solution"])
            checked_scores += 1
        rows = [row for row in results if row["id"] == problem_id]
        for row in rows:
            if row["status"] == "runner_error":
                continue
            assert row["initial_code"] == source_result["initial_code"]
            assert row["pre_solve"]["business_correct"] is False
            assert row["reference_answer_used_for_selection"] is False
            assert row["dag"]["score_based_pruning"] is False
            nodes = {node["node_id"]: node for node in row["dag"]["nodes"]}
            selected = nodes[row["selected_node_id"]]
            if selected["execution"].get("solution") is not None:
                assert selected["business_audit"] == score_solution(
                    problem_id, selected["execution"]["solution"])
                checked_scores += 1
            if row["accepted"]:
                assert selected["business_audit"]["business_correct"] is True
                assert selected["binding_status"] == "validated"
                assert selected["execution"].get("status", selected["execution"].get("solver_status")) == "optimal"
                assert row["selected_node_id"] in row["accepted_node_ids"]
            if row["arm"] == "bind_only":
                assert row["logical_repair_llm_calls"] == 0
            if row["arm"] == "branch_dag" and len(nodes["root"]["children"]) > 1:
                assert {nodes[child]["parent_id"] for child in nodes["root"]["children"]} == {"root"}
    generation_files = sorted((run / "shared_generations").rglob("*.json"))
    for path in generation_files:
        record = json.loads(path.read_text())
        assert "en_answer" not in json.dumps(record["messages"])
        if record.get("response", {}).get("content"):
            assert record["response"]["model"] == config["model"]
            assert record["response"].get("request_attempts")
    return {"results": len(results), "business_scores_recomputed": checked_scores,
            "source_snapshots_verified": snapshots, "generation_records_verified": len(generation_files),
            "analysis_sha256": hashlib.sha256((run / "analysis.json").read_bytes()).hexdigest()}


def build_report(run: Path = RUN, report_path: Path = ROOT / "docs/paper/industryor_semantic_dag_results_v0.1.md",
                 figure_dir: Path = ROOT / "docs/paper/figures", tag: str = "v0.1"):
    run = run.resolve()
    analysis = json.loads((run / "analysis.json").read_text())
    validation = validate(run)
    summary = analysis["summary"]
    results = analysis["results"]
    binding = json.loads((BINDINGS / "analysis.json").read_text())["summary"]
    audit_complete_ids = {
        arm: sorted({row["id"] for row in results if row["arm"] == arm
                     and any(node["business_audit"].get("audit_status") == "complete"
                             for node in row["dag"]["nodes"])})
        for arm in ARMS}
    manifest = {"schema_version": "industryor.semantic_dag.manifest.v0.1",
                "run_config": analysis["run_config"], "validation": validation,
                "exposure": "development replay, not held-out or cross-family evidence",
                "audit_complete_problem_ids": audit_complete_ids,
                "binding_source": str(BINDINGS.relative_to(ROOT)),
                "results": [{"id": row["id"], "arm": row["arm"], "status": row["status"],
                             "accepted": row["accepted"], "selected_node_id": row["selected_node_id"],
                             "result_path": f"prob_{row['id']:03d}/{row['arm']}/"
                             f"{'result.json' if row['status'] == 'completed' else 'error.json'}"}
                            for row in results],
                "shared_generation_sha256": {
                    str(path.relative_to(run / "shared_generations")): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted((run / "shared_generations").rglob("*.json"))}}
    write_json(run / "manifest.json", manifest)
    lines = ["# IndustryOR 语义内环：绑定、单线修复与同父 DAG", "",
             "**范围：8 个已注册独立审计题的开发回放，不是 held-out 或跨族结论。** 所有臂共享相同初始代码、语义绑定和根执行；不运行跨题 memory/RSI。", "",
             "## 核心结果", "",
             "| 臂 | 可完整审计 | 根业务正确 | 最终业务正确 | 明确语义恢复 | 目标匹配 | 实际新增修复调用 | 逻辑修复调用 | 多分支题数 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for arm in ARMS:
        arm_summary = summary["arms"][arm]
        lines.append(f"| {arm} | {len(audit_complete_ids[arm])} | {arm_summary['root_business_correct']} | {arm_summary['final_business_correct']} | {arm_summary['business_recoveries']} | {arm_summary['objective_matches_abs_0_1']}/8 | {arm_summary['new_llm_calls']} | {arm_summary['logical_repair_llm_calls']} | {arm_summary['multi_branch_cases']} |")
    single = summary["arms"]["single_line"]
    dag = summary["arms"]["branch_dag"]
    lines.extend(["", f"单线与 DAG 的最终业务正确数差为 **{dag['final_business_correct'] - single['final_business_correct']:+d}**，实际新增修复调用差为 **{dag['new_llm_calls'] - single['new_llm_calls']:+d}**，逻辑修复调用差为 **{dag['logical_repair_llm_calls'] - single['logical_repair_llm_calls']:+d}**。因此不能把分支数量本身当成效果。", "",
                  "重绑定只改变导出名称，不改变模型内部语义；它带来的审计覆盖提升不计作模型修复。明确语义恢复只统计根候选 `complete + business_correct=false` 到最终 `business_correct=true` 的候选。可完整审计与业务接受是两个不同指标。", "",
                  "## 逐题证据", "",
                  "| ID | 绑定后审计/正确 | 单线最终/正确 | DAG 最终/正确 | 单线逻辑/新增 | DAG 逻辑/新增 | DAG 其他候选审计 | DAG 接受动作 |",
                  "|---:|---|---|---|---:|---:|---|---|"])
    for problem_id in analysis["run_config"]["ids"]:
        rows = {row["arm"]: row for row in results if row["id"] == problem_id}
        root = rows["bind_only"]["root_score"]
        single_row = rows["single_line"]
        dag_row = rows["branch_dag"]
        actions = sorted({node["action"] for node in dag_row["dag"]["nodes"]
                          if node["node_id"] in dag_row["accepted_node_ids"]})
        alternatives = [f"{node['action']}:{node['business_audit'].get('audit_status')}/{node['business_audit'].get('business_correct')}"
                        for node in dag_row["dag"]["nodes"] if node["node_id"] != "root"]
        lines.append(f"| {problem_id} | {root.get('audit_status')}/{root.get('business_correct')} | {single_row['final_score'].get('audit_status')}/{single_row['final_score'].get('business_correct')} | {dag_row['final_score'].get('audit_status')}/{dag_row['final_score'].get('business_correct')} | {single_row['logical_repair_llm_calls']}/{single_row['new_llm_calls']} | {dag_row['logical_repair_llm_calls']}/{dag_row['new_llm_calls']} | {alternatives or '无'} | {actions or '无'} |")
    lines.extend(["", "## 成本", "",
                  f"- 共享绑定阶段已发生 {binding['new_llm_calls']} 次调用、{binding['total_tokens']} tokens、{binding['llm_latency_s']:.3f}s；三臂均复用，不重复计新调用。",
                  f"- `single_line`：实际新增修复调用 {single['new_llm_calls']}，逻辑调用 {single['logical_repair_llm_calls']}，逻辑 tokens {single['total_tokens']}，SCIP {single['solver_runs']}。",
                  f"- `branch_dag`：实际新增修复调用 {dag['new_llm_calls']}，逻辑调用 {dag['logical_repair_llm_calls']}，逻辑 tokens {dag['total_tokens']}，SCIP {dag['solver_runs']}。",
                  "- DAG 开发模式故意评估同父的替代分支，即使一个分支已经通过；额外成本用于检验搜索机制，不应隐藏。",
                  *([f"- 重生成响应回放自 `{analysis['run_config']['regeneration_replay']['source']}`；逻辑成本保留，实际新增调用单独计为 0。"]
                    if analysis["run_config"].get("regeneration_replay") else []),
                  "", "## 可追溯性与限制", "",
                  f"- 核验 {validation['results']} 条臂结果、{validation['business_scores_recomputed']} 份业务评分、{validation['generation_records_verified']} 份重生成记录和 {validation['source_snapshots_verified']} 份执行源码快照。",
                  "- 只使用 ID 9/19/20/21 的独立局部修复证据。ID 48 若业务目标不一致，即使变量可完整审计且约束可行，也不能接受。",
                  "- 这里的 DAG 选择顺序是业务接受、LLM/SCIP 成本、深度和节点 ID，不使用参考答案排序。",
                  "- 这些结果不证明 IndustryOR-100 全集、跨族迁移或外环自进化有效。全集历史 70/100 的结果仍单独保留，不与此开发回放混写。",
                  "", f"机器可读结果：`{run.relative_to(ROOT)}/analysis.json`；manifest：`{run.relative_to(ROOT)}/manifest.json`。", ""])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines))
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6))
    labels = ["Bind only", "Single-line", "Sibling DAG"]
    correct = [summary["arms"][arm]["final_business_correct"] for arm in ARMS]
    bars = axes[0].bar(labels, correct, color=["#64748b", "#2563eb", "#059669"])
    for bar, value in zip(bars, correct):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + 0.1, str(value), ha="center")
    axes[0].set_ylim(0, 8.8)
    axes[0].set_ylabel("Independently business-correct")
    axes[0].set_title("Same initial candidates (n=8)")
    x = range(3)
    logical_calls = [summary["arms"][arm]["logical_repair_llm_calls"] for arm in ARMS]
    solver = [summary["arms"][arm]["solver_runs"] for arm in ARMS]
    bars1 = axes[1].bar([value - 0.18 for value in x], logical_calls, width=0.36,
                        label="Logical repair LLM calls", color="#f59e0b")
    bars2 = axes[1].bar([value + 0.18 for value in x], solver, width=0.36,
                        label="Actual SCIP runs", color="#2563eb")
    for bars in (bars1, bars2):
        for bar in bars:
            axes[1].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.15,
                         str(int(bar.get_height())), ha="center", fontsize=9)
    axes[1].set_xticks(list(x), labels)
    axes[1].set_title("Search overhead is reported, not hidden")
    axes[1].legend(frameon=False, fontsize=9)
    fig.text(0.5, 0.025,
             "Development replay only; shared initial code, binding and root execution. "
             "No reference-answer branch selection, outer-loop evolution or held-out claim.",
             ha="center", fontsize=9, color="#444444")
    fig.tight_layout(rect=(0, 0.10, 1, 0.95))
    figure_dir.mkdir(parents=True, exist_ok=True)
    image = figure_dir / f"industryor_semantic_dag_{tag}.png"
    fig.savefig(image, dpi=170, bbox_inches="tight")
    plt.close(fig)
    data = {"scope": "development_replay_not_heldout", "arms": summary["arms"],
            "audit_complete_problem_ids": audit_complete_ids,
            "dag_minus_single_business_correct": dag["final_business_correct"] - single["final_business_correct"],
            "dag_minus_single_new_llm_calls": dag["new_llm_calls"] - single["new_llm_calls"],
            "dag_minus_single_logical_llm_calls": dag["logical_repair_llm_calls"] - single["logical_repair_llm_calls"],
            "binding_cost": binding, "validation": validation,
            "regeneration_replay": analysis["run_config"].get("regeneration_replay"),
            "claims": {"full_industryor_improvement": False, "cross_family_transfer": False,
                       "outer_loop_evolution": False, "heldout": False},
            "sources": [f"{run.relative_to(ROOT)}/analysis.json", f"{run.relative_to(ROOT)}/manifest.json"]}
    data_path = figure_dir / f"industryor_semantic_dag_{tag}.json"
    write_json(data_path, data)
    return report_path, image, data_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=RUN)
    parser.add_argument("--tag", default="v0.1")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--figure-dir", type=Path, default=ROOT / "docs/paper/figures")
    args = parser.parse_args()
    report = args.report or ROOT / f"docs/paper/industryor_semantic_dag_results_{args.tag}.md"
    paths = build_report(args.run, report, args.figure_dir, args.tag)
    print(json.dumps({"report": str(paths[0]), "figure": str(paths[1]), "data": str(paths[2])},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

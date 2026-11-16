#!/usr/bin/env python3
"""Validate k=1/k=3 artifacts and report candidate-pool versus selector outcomes."""
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

from scripts.industryor_k3_pipeline import AUDIT_IDS, costs, question_for
from scripts.industryor_full_pipeline import baseline
from scripts.industryor_next_stage import score_solution
from scripts.m3_industryor import SCIP_CONTRACT, load_priors

RUN = ROOT / "work/industryor_k3_dev_v0.1"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def validate(run: Path, require_complete: bool = True) -> dict:
    analysis = json.loads((run / "analysis.json").read_text())
    config = analysis["run_config"]
    assert config == json.loads((run / "run_config.json").read_text())
    assert "api_key" not in json.dumps(config)
    results = analysis["results"]
    assert len(results) == len(config["ids"])
    assert {row["id"] for row in results} == set(config["ids"])
    if require_complete:
        assert len(results) == 100
        assert analysis["summary"]["runner_errors"] == 0
    snapshots = 0
    for name, expected in config["implementation_sha256"].items():
        path = run / "source" / name
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        snapshots += 1
    protocol = run / "source/docs/paper/industryor_k3_protocol_v0.1.md"
    assert hashlib.sha256(protocol.read_bytes()).hexdigest() == config["protocol_sha256"]
    generation_count = selector_count = score_count = 0
    for result in results:
        case = run / f"prob_{result['id']:03d}"
        if result["status"] == "runner_error":
            continue
        prompt = load_priors() + "\n\n" + SCIP_CONTRACT + question_for(result["id"])
        assert (case / "prompt.txt").read_text() == prompt
        candidates = result["candidates"]
        assert len(candidates) == 3
        all_records = []
        for candidate in candidates:
            candidate_case = case / f"candidate_{candidate['candidate_id']}"
            generation_path = candidate_case / "generation.json"
            generation = json.loads(generation_path.read_text())
            generation_count += 1
            assert generation["messages"] == [{"role": "user", "content": prompt}]
            assert generation["response"]["model"] == config["model"]
            assert generation["response"].get("request_attempts")
            records = [generation]
            binding_path = candidate_case / "binding.json"
            if binding_path.exists():
                records.append(json.loads(binding_path.read_text()))
            all_records.extend(records)
            solution_path = candidate_case / "solution.json"
            solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
            if result["id"] in AUDIT_IDS and solution is not None:
                assert candidate["score"] == score_solution(result["id"], solution)
                score_count += 1
            if candidate["business_accepted"]:
                assert candidate["score"]["business_correct"] is True
                assert candidate["gate"]["status"] == "ready"
            if candidate["candidate_id"] == "A":
                cost_a = costs(records)
                assert cost_a == result["cost_a"]
        selection_path = case / "selection.json"
        if selection_path.exists():
            all_records.append(json.loads(selection_path.read_text()))
            selector_count += 1
            assert "en_answer" not in selection_path.read_text()
        assert costs(all_records) == result["cost_all"]
        selected = next(candidate for candidate in candidates if candidate["candidate_id"] == result["selected_candidate"])
        assert result["selected_objective"] == selected["objective"]
        assert result["selected_match"] == (selected["objective"] is not None
                                            and abs(selected["objective"] - result["reference"]) <= 0.1)
        scored = [candidate for candidate in candidates if candidate["objective"] is not None]
        if scored:
            oracle = min(scored, key=lambda candidate: abs(candidate["objective"] - result["reference"]))
            assert result["oracle_candidate"] == oracle["candidate_id"]
            assert result["oracle_match"] == (abs(oracle["objective"] - result["reference"]) <= 0.1)
        assert result["public_answer_used_for_selection"] is False
        assert result["oracle_not_deployable"] is True
    if require_complete:
        assert generation_count == 300
    return {"results": len(results), "candidate_generations_verified": generation_count,
            "selector_records_verified": selector_count, "business_scores_recomputed": score_count,
            "source_snapshots_verified": snapshots,
            "analysis_sha256": hashlib.sha256((run / "analysis.json").read_bytes()).hexdigest()}


def build_report(run: Path = RUN, report_path: Path = ROOT / "docs/paper/industryor_k3_results_v0.1.md",
                 figure_dir: Path = ROOT / "docs/paper/figures", require_complete: bool = True):
    run = run.resolve()
    analysis = json.loads((run / "analysis.json").read_text())
    summary = analysis["summary"]
    validation = validate(run, require_complete)
    results = analysis["results"]
    n = len(results)
    historical = baseline()
    previous = json.loads((ROOT / "work/industryor_full_qwen_v0.1/analysis.json").read_text())["summary"]
    lines = ["# IndustryOR k=1/k=3 候选生成与选择结果", "",
             f"**范围：{n} 题，开发性新采样，不是 held-out。** 不叠加 memory 或额外 repair。k=1 与 k=3-first 共用 A。", "",
             "## 主要指标", "",
             "| 指标 | 数量 | 说明 |", "|---|---:|---|",
             f"| 历史 z2 | {historical['z2']['objective_matches_abs_0_1']}/100 | 含执行修复的旧日志复算 |",
             f"| 上一轮完整管线 | {previous['objective_matches_abs_0_1']}/100 | 含有限 Witness/修复 |",
             f"| k=1 目标匹配 | {summary['k1_matches']}/{n} | A 单独生成，abs≤0.1 |",
             f"| k=3 selected 目标匹配 | {summary['k3_selected_matches']}/{n} | 无参考答案选择器选出的实际输出 |",
             f"| k=3 oracle 目标匹配 | {summary['k3_oracle_matches_not_deployable']}/{n} | 仅候选池上界，不是可部署方法 |",
             f"| 选择器错过候选池 | {summary['selection_missed_pool']} | oracle 匹配但 selected 不匹配 |",
             f"| k=1 业务正确 | {summary['k1_business_correct']} | 仅注册审计题 |",
             f"| k=3 selected 业务正确 | {summary['k3_selected_business_correct']} | 仅注册审计题 |",
             f"| k=3 候选池业务正确 | {summary['k3_pool_business_correct']} | 任一候选独立通过，非最终输出 |",
             f"| runner errors | {summary['runner_errors']} | 失败保留在分母 |",
             "",
             f"k=3 selected 相对 k=1 的差值：**{summary['k3_selected_matches'] - summary['k1_matches']:+d}**。oracle 相对 k=1 的差值为 {summary['k3_oracle_matches_not_deployable'] - summary['k1_matches']:+d}，后者只说明候选池潜力，不能作为方法收益。",
             "",
             "本轮 k=1/k=3 不做额外 repair，与历史含修复结果不是严格机制消融；模型 revision 和采样也不同。公开 COOPA 的 76/100 仅作同数据、同绝对误差口径的参考。单次开发采样不构成 SOTA 证明；若 selected 不超过该线，也不得用 oracle 替代。",
             "", "## 成本", "",
             "| 臂 | 逻辑 LLM 调用 | 实际新增调用 | completion tokens | 总 tokens | LLM 延迟(s) |",
             "|---|---:|---:|---:|---:|---:|"]
    for name, prefix in (("k=1", "cost_k1"), ("k=3", "cost_k3")):
        cost = summary[prefix]
        lines.append(f"| {name} | {cost['logical_llm_calls']} | {cost['new_llm_calls']} | {cost['completion_tokens']} | {cost['total_tokens']} | {cost['llm_latency_s']:.3f} |")
    lines.extend(["", "## 逐题差分与选择失败", "",
                  "| ID | A 目标 | selected 目标 | oracle 目标 | selected ID | oracle ID | 选择器漏选 |",
                  "|---:|---:|---:|---:|---|---|---|"])
    for row in results:
        if row["k1_match"] == row["selected_match"] == row["oracle_match"] and not row.get("selection_missed_pool"):
            continue
        lines.append(f"| {row['id']} | {row.get('k1_objective')} | {row.get('selected_objective')} | {row.get('oracle_objective')} | {row.get('selected_candidate')} | {row.get('oracle_candidate')} | {row.get('selection_missed_pool', False)} |")
    missed = [row["id"] for row in results if row.get("selection_missed_pool")]
    lines.extend(["", f"选择器漏选 ID：{missed or '无'}。", "",
                  "## 可追溯性与限制", "",
                  f"- 核验 {validation['candidate_generations_verified']} 份候选生成、{validation['selector_records_verified']} 份选择记录、{validation['business_scores_recomputed']} 份业务评分和 {validation['source_snapshots_verified']} 份执行源码快照。",
                  "- k=3 selected 不使用 `en_answer`；oracle 是事后分析，不参与选择。92 个未注册业务审计题仍保持 `business_unverified`。",
                  "- 本轮没有 memory、额外 repair 或跨题外环，因此结果只回答候选多样性和选择器的贡献。",
                  "", f"机器结果：`{run.relative_to(ROOT)}/analysis.json`；manifest：`{run.relative_to(ROOT)}/manifest.json`。", ""])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines))
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.7))
    labels = ["k=1", "k=3 selected", "k=3 oracle"]
    values = [summary["k1_matches"], summary["k3_selected_matches"], summary["k3_oracle_matches_not_deployable"]]
    bars = axes[0].bar(labels, values, color=["#64748b", "#2563eb", "#f59e0b"])
    for bar, value in zip(bars, values):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + n * 0.015, str(value), ha="center")
    axes[0].set_ylim(0, n * 1.12)
    axes[0].set_ylabel("Objective matches")
    axes[0].set_title(f"Absolute error <= 0.1 (n={n})")
    business_values = [summary["k1_business_correct"], summary["k3_selected_business_correct"], summary["k3_pool_business_correct"]]
    bars = axes[1].bar(labels, business_values, color=["#64748b", "#059669", "#f59e0b"])
    for bar, value in zip(bars, business_values):
        axes[1].text(bar.get_x() + bar.get_width() / 2, value + 0.1, str(value), ha="center")
    axes[1].set_ylim(0, max(8, max(business_values, default=0)) + 1)
    axes[1].set_ylabel("Independently business-correct")
    axes[1].set_title("Selected output versus candidate pool")
    cost_values = [summary["cost_k1"]["logical_llm_calls"], summary["cost_k3"]["logical_llm_calls"]]
    bars = axes[2].bar(["k=1", "k=3"], cost_values, color=["#64748b", "#2563eb"])
    for bar, value in zip(bars, cost_values):
        axes[2].text(bar.get_x() + bar.get_width() / 2, value + 0.5, str(value), ha="center")
    axes[2].set_ylabel("Logical LLM calls")
    axes[2].set_title("Candidate generation and selection cost")
    fig.text(0.5, 0.025,
             "Development samples only; no reference-answer selection. Oracle is a pool upper bound, not a method. "
             "No memory, extra repair or held-out claim.", ha="center", fontsize=9, color="#444444")
    fig.tight_layout(rect=(0, 0.10, 1, 0.95))
    figure_dir.mkdir(parents=True, exist_ok=True)
    image = figure_dir / "industryor_k3_v0.1.png"
    fig.savefig(image, dpi=170, bbox_inches="tight")
    plt.close(fig)
    data = {"scope": "development_new_samples_not_heldout", "n": n, "summary": summary,
            "validation": validation, "selection_missed_pool_ids": missed,
            "claims": {"sota": False, "oracle_is_deployable": False, "memory": False, "extra_repair": False},
            "sources": [f"{run.relative_to(ROOT)}/analysis.json", f"{run.relative_to(ROOT)}/manifest.json"]}
    data_path = figure_dir / "industryor_k3_v0.1.json"
    write_json(data_path, data)
    return report_path, image, data_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=RUN)
    parser.add_argument("--report", type=Path, default=ROOT / "docs/paper/industryor_k3_results_v0.1.md")
    parser.add_argument("--figure-dir", type=Path, default=ROOT / "docs/paper/figures")
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    paths = build_report(args.run, args.report, args.figure_dir, not args.allow_partial)
    print(json.dumps({"report": str(paths[0]), "figure": str(paths[1]), "data": str(paths[2])}, indent=1))


if __name__ == "__main__":
    main()

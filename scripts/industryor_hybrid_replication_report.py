#!/usr/bin/env python3
"""Aggregate independent selector replays without creating a majority-vote output."""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

RUNS = (ROOT / "work/industryor_hybrid_dev_v0.1",
        ROOT / "work/industryor_hybrid_replicate_v0.2",
        ROOT / "work/industryor_hybrid_replicate_v0.3")
OUT = ROOT / "work/industryor_hybrid_replication_v0.1"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    analyses = [json.loads((run / "analysis.json").read_text()) for run in RUNS]
    configs = [analysis["run_config"] for analysis in analyses]
    assert all(config == configs[0] for config in configs[1:])
    summaries = []
    per_problem = {}
    for index, (run, analysis) in enumerate(zip(RUNS, analyses), 1):
        results = analysis["results"]
        assert len(results) == 100 and analysis["summary"]["runner_errors"] == 0
        summary = analysis["summary"]
        assert summary["hybrid_matches"] == sum(row["match"] for row in results)
        summaries.append({"run": f"run_{index}", "matches": summary["hybrid_matches"],
                          "gained_vs_full_ids": summary["gained_vs_full_ids"],
                          "lost_vs_full_ids": summary["lost_vs_full_ids"],
                          "business_correct": summary["business_correct"],
                          "false_business_accepts": summary["false_business_accepts"],
                          "selector_cost": summary["selector_cost"],
                          "analysis_sha256": digest(run / "analysis.json")})
        for row in results:
            per_problem.setdefault(row["id"], {"runs": []})["runs"].append(
                {"run": f"run_{index}", "match": row["match"], "source": row["selected_source"],
                 "objective": row["objective"]})
    matches = [summary["matches"] for summary in summaries]
    result = {"run_config": configs[0], "scope": "selector_only_replication_not_full_pipeline_resampling",
              "reference_line": 76, "runs": summaries, "per_problem": per_problem,
              "aggregate": {"n_runs": len(matches), "min": min(matches), "max": max(matches),
                            "mean": statistics.mean(matches), "median": statistics.median(matches),
                            "all_above_reference": all(value > 76 for value in matches),
                            "all_business_correct": [summary["business_correct"] for summary in summaries],
                            "total_false_business_accepts": sum(summary["false_business_accepts"]
                                                                for summary in summaries)}}
    write_json(OUT / "analysis.json", result)
    write_json(OUT / "manifest.json", {"runs": [str(run.relative_to(ROOT)) for run in RUNS],
                                       "n_runs": len(RUNS), "n_problems_each": 100,
                                       "run_configs_identical": True,
                                       "public_answer_used_for_selection": False,
                                       "majority_vote_created": False})
    report = ROOT / "docs/paper/industryor_hybrid_replication_results_v0.1.md"
    lines = ["# IndustryOR 混合选择独立复现", "",
             "**范围：同一批冻结候选上的三次独立选择采样，不是整条生成管线重采样，也不是 held-out。**", "",
             "| Run | 目标匹配 | 相对 full 新增 | 相对 full 丢失 | 独立业务正确（8题） | 误接受 | 新增选择调用 |",
             "|---|---:|---|---|---:|---:|---:|"]
    for summary in summaries:
        lines.append(f"| {summary['run']} | {summary['matches']} | {summary['gained_vs_full_ids']} | {summary['lost_vs_full_ids']} | {summary['business_correct']} | {summary['false_business_accepts']} | {summary['selector_cost']['new_llm_calls']} |")
    aggregate = result["aggregate"]
    lines.extend(["", f"min/mean/median/max = {aggregate['min']}/{aggregate['mean']:.2f}/{aggregate['median']}/{aggregate['max']}；全部三轮 >76：**{aggregate['all_above_reference']}**。",
                  "每轮都直接输出实际选择结果，不用三轮多数票或候选池 oracle 代替。COOPA=76 是不同模型和配置的公开参考，本复现不据此宣称 SOTA。",
                  "", f"机器结果：`{OUT.relative_to(ROOT)}/analysis.json`；manifest：`{OUT.relative_to(ROOT)}/manifest.json`。", ""])
    report.write_text("\n".join(lines))
    figure_dir = ROOT / "docs/paper/figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    fig, axis = plt.subplots(figsize=(7.5, 4.5))
    bars = axis.bar([summary["run"] for summary in summaries], matches, color="#2563eb")
    axis.axhline(76, color="#dc2626", linestyle="--", linewidth=1.5, label="COOPA public reference = 76")
    for bar, value in zip(bars, matches):
        axis.text(bar.get_x() + bar.get_width() / 2, value + 0.4, str(value), ha="center")
    axis.set_ylim(0, 100)
    axis.set_ylabel("Objective matches (n=100)")
    axis.set_title("Independent selector replays on frozen candidates")
    axis.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(figure_dir / "industryor_hybrid_replication_v0.1.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    write_json(figure_dir / "industryor_hybrid_replication_v0.1.json", result)
    print(json.dumps(aggregate, indent=1))


if __name__ == "__main__":
    main()

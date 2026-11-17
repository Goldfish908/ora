#!/usr/bin/env python3
"""Deploy a three-replay source-majority selector over frozen hybrid inputs."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts.industryor_hybrid_selector import (DATA, FULL_RUN, RAW_RUN, costs, digest_file,
                                                 full_candidate, raw_candidate)
from scripts.industryor_next_stage import score_solution

AUDIT_IDS = (4, 8, 9, 19, 20, 21, 25, 48)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def majority_source(votes: list[str]) -> str:
    counts = Counter(votes)
    if set(counts) - {"structured_full", "raw_selected"} or sum(counts.values()) != 3:
        raise ValueError("expected exactly three full/raw votes")
    return "raw_selected" if counts["raw_selected"] >= 2 else "structured_full"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, nargs=3, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report-name")
    parser.add_argument("--scope", default="development_frozen_candidates")
    args = parser.parse_args()
    runs = [path.resolve() for path in args.runs]
    outdir = args.out.resolve()
    if outdir.exists() and any(outdir.iterdir()):
        raise ValueError("output directory must be empty")
    analyses = [json.loads((run / "analysis.json").read_text()) for run in runs]
    configs = [analysis["run_config"] for analysis in analyses]
    assert all(config == configs[0] for config in configs[1:])
    by_run = [{row["id"]: row for row in analysis["results"]} for analysis in analyses]
    rows = json.loads(DATA.read_text())
    full_analysis = json.loads((FULL_RUN / "analysis.json").read_text())
    raw_analysis = json.loads((RAW_RUN / "analysis.json").read_text())
    full_rows = {row["id"]: row for row in full_analysis["results"] if row["arm"] == "structured_dag_full"}
    raw_rows = {row["id"]: row for row in raw_analysis["results"]}
    results = []
    for row in rows:
        problem_id = row["id"]
        votes = [by_id[problem_id]["selected_source"] for by_id in by_run]
        source = majority_source(votes)
        selected = (full_candidate(full_rows[problem_id]) if source == "structured_full"
                    else raw_candidate(raw_rows[problem_id]))
        reference = float(row["en_answer"])
        objective = selected["objective"]
        result = {"id": problem_id, "status": "completed", "votes": votes,
                  "selected_source": source, "selection_method": "three_replay_source_majority",
                  "objective": objective, "reference": reference,
                  "match": objective is not None and abs(objective - reference) <= 0.1,
                  "full_match": full_rows[problem_id]["match"], "raw_match": raw_rows[problem_id]["selected_match"],
                  "business_correct": selected["business_accepted"],
                  "business_unverified": selected["business_unverified"],
                  "selected_code": selected["code"], "final_record": selected["record"],
                  "final_solution": selected["solution"], "final_score": selected["score"],
                  "public_answer_used_for_selection": False}
        assert result["business_unverified"] or selected["solution"] is None \
            or selected["score"] == score_solution(problem_id, selected["solution"])
        results.append(result)
        write_json(outdir / f"prob_{problem_id:03d}" / "result.json", result)
    cost_keys = ("logical_llm_calls", "new_llm_calls", "api_attempts", "completion_tokens",
                 "total_tokens", "llm_latency_s", "new_llm_latency_s")
    selector_cost = {key: sum(analysis["summary"]["selector_cost"][key] for analysis in analyses)
                     for key in cost_keys}
    summary = {"n": 100, "matches": sum(row["match"] for row in results),
               "gained_vs_full_ids": [row["id"] for row in results if row["match"] and not row["full_match"]],
               "lost_vs_full_ids": [row["id"] for row in results if row["full_match"] and not row["match"]],
               "business_correct": sum(row["business_correct"] for row in results),
               "false_business_accepts": sum(row["business_correct"] and
                                             (row["business_unverified"] or not row["final_score"]["business_correct"])
                                             for row in results),
               "selected_sources": dict(Counter(row["selected_source"] for row in results)),
               "selector_cost_three_replays": selector_cost,
               "aggregation_new_llm_calls": 0}
    analysis = {"run_configs": configs, "scope": args.scope,
                "input_analysis_sha256": [digest_file(run / "analysis.json") for run in runs],
                "ensemble_implementation_sha256": digest_file(ROOT / "scripts/industryor_hybrid_ensemble.py"),
                "ensemble_protocol_sha256": digest_file(ROOT / "docs/paper/industryor_hybrid_ensemble_protocol_v0.1.md"),
                "summary": summary, "results": results}
    write_json(outdir / "analysis.json", analysis)
    write_json(outdir / "manifest.json", {"runs": [str(run) for run in runs], "n_runs": 3,
                                          "accounted_n": len(results), "majority_vote_created": True,
                                          "public_answer_used_for_selection": False})
    report_text = "\n".join(["# IndustryOR 三次选择来源多数表决", "",
                             "**开发性冻结候选，不是 held-out；每次表决由三次真实选择组成，不使用参考答案。**", "",
                             f"目标匹配：**{summary['matches']}/100**；独立业务正确：{summary['business_correct']}/8；误接受：{summary['false_business_accepts']}。",
                             f"相对 full 新增：{summary['gained_vs_full_ids']}；丢失：{summary['lost_vs_full_ids']}。",
                             f"来源：{summary['selected_sources']}；三次选择成本：{json.dumps(selector_cost)}；聚合新增调用=0。", ""])
    (outdir / "report.md").write_text(report_text)
    fig, axis = plt.subplots(figsize=(5.5, 4))
    axis.bar(["full", "three-vote hybrid"], [sum(row["full_match"] for row in results), summary["matches"]],
             color=["#64748b", "#2563eb"])
    axis.axhline(76, color="#dc2626", linestyle="--", linewidth=1.2)
    axis.set_ylim(0, 100)
    axis.set_ylabel("Objective matches")
    fig.tight_layout()
    fig.savefig(outdir / "figure.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    if args.report_name:
        report_dir = ROOT / "docs/paper"
        (report_dir / f"{args.report_name}.md").write_text(report_text)
        (report_dir / "figures" / f"{args.report_name}.png").write_bytes((outdir / "figure.png").read_bytes())
        write_json(report_dir / "figures" / f"{args.report_name}.json", analysis)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

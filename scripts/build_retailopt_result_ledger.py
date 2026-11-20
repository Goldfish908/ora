#!/usr/bin/env python3
"""Build a comparable RetailOpt run ledger without pooling incompatible evaluations."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
A0 = ROOT / "work/retailopt_gepa_stream_a0_v0.3"
GAP = ROOT / "data/m1_retailopt/gapcheck60_f1f4.jsonl"
SCORE = "RetailOpt legacy Witness feasible + saved objective match/better; operational, not complete semantic truth"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def write_csv(path: Path, rows: list[dict]) -> None:
    preferred = ["run_id", "dataset", "split", "comparison_group", "method", "candidate_idx",
                 "scenario_id", "family", "n", "true_correct", "true_correct_rate", "proxy_match",
                 "phantom_proxy", "unknown", "evidence", "source_path"]
    fields = preferred + sorted({key for row in rows for key in row} - set(preferred))
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: ";".join(value) if isinstance(value, list) else value
                             for key, value in row.items() if value is not None})


def historical_run(run_id: str, split: str, n: int, method: str, true_correct: int,
                   source: str, group: str, notes: str, candidates: int = 1,
                   repair_rounds: int = 0) -> dict:
    return {
        "run_id": run_id,
        "dataset": "RetailOpt-190",
        "split": split,
        "comparison_group": group,
        "method": method,
        "model": "Qwen3.8-27B",
        "n": n,
        "true_correct": true_correct,
        "true_correct_rate": true_correct / n,
        "candidate_count": candidates,
        "max_inner_repair_rounds": repair_rounds,
        "score_definition": SCORE,
        "evidence": "documented_aggregate",
        "per_task_records_in_ledger": False,
        "source_path": source,
        "notes": notes,
    }


def historical_runs() -> list[dict]:
    evolution = "docs/paper/experiment_log_v0.1.md"
    return [
        historical_run("p3_g0_seed_gapcheck60", "gapcheck60", 60,
                       "Manual P3 conventions; single generation", 12, evolution,
                       "retailopt_gapcheck60_single_candidate",
                       "Historical g0 seed; documented aggregate, not recomputed here."),
        historical_run("gen1_champion_gapcheck60", "gapcheck60", 60,
                       "Genome evolution gen1 champion; single generation", 8, evolution,
                       "retailopt_gapcheck60_single_candidate",
                       "Historical self-written evolution, not official GEPA."),
        historical_run("gen2_champion_gapcheck60", "gapcheck60", 60,
                       "Genome evolution gen2 champion; single generation", 17, evolution,
                       "retailopt_gapcheck60_single_candidate",
                       "Best historical gapcheck60 result found in the reviewed reports."),
        historical_run("gen3_champion_gapcheck60", "gapcheck60", 60,
                       "Genome evolution gen3 champion; single generation", 15, evolution,
                       "retailopt_gapcheck60_single_candidate",
                       "Historical self-written evolution, not official GEPA."),
        historical_run("zero_shot_full190", "full190", 190,
                       "Zero-shot single generation", 13, "docs/paper/supp_comparisons_v0.1.md",
                       "retailopt_full190_single_candidate", "F1–F8; different denominator from gapcheck60."),
        historical_run("p3_full190", "full190", 190,
                       "Manual P3 conventions; single generation", 41, "docs/paper/supp_comparisons_v0.1.md",
                       "retailopt_full190_single_candidate", "Single-candidate full190 reference."),
        historical_run("b_doubleprime_full190", "full190", 190,
                       "Presolve gate + crash guard + Witness repair", 103,
                       "docs/paper/supp_comparisons_v0.1.md", "retailopt_full190_single_candidate",
                       "Single chain with at most three repair rounds.", repair_rounds=3),
        historical_run("manual_p3_three_chain_full190", "full190", 190,
                       "Manual P3 + three-chain ensemble", 110, "docs/paper/evolution_gen0123_v0.1.md",
                       "retailopt_full190_multi_chain", "Reported as 57.9%=110/190; not a single candidate.",
                       candidates=3, repair_rounds=3),
        historical_run("e3_two_chain_arbitration_full190", "full190", 190,
                       "Two-chain Witness-feasible minimum-objective arbitration", 130,
                       "docs/paper/ensemble_dualchain_v0.1.md", "retailopt_full190_multi_chain",
                       "Multi-chain arbitration; not comparable to one generation.", candidates=2, repair_rounds=3),
        historical_run("e1_two_chain_union_full190", "full190", 190,
                       "Two-chain oracle union of Witness+grade successes", 132,
                       "docs/paper/ensemble_dualchain_v0.1.md", "retailopt_full190_oracle_union",
                       "Oracle upper reference, not a deployable single answer.", candidates=2, repair_rounds=3),
        historical_run("dvsa_dev20", "dev20", 20,
                       "DVSA saved-candidate repair and win-safe replay", 18,
                       "work/dvsa/retailopt_win_safe_v0.1/analysis.json", "retailopt_dev20",
                       "Dev subset and saved candidates; cannot compare its 90% with gapcheck60."),
    ]


def outcome(record: dict) -> str:
    if record["true_correct"]:
        return "true_correct"
    if record["phantom_proxy"]:
        return "phantom_proxy"
    if record.get("witness") == "infeasible":
        return "witness_fail_without_proxy"
    if record.get("witness") == "feasible":
        return "witness_feasible_objective_mismatch"
    return "unknown"


def current_runs_and_tasks() -> tuple[list[dict], list[dict], dict]:
    analysis = read_json(A0 / "analysis.json")
    gap_rows = [json.loads(line) for line in GAP.read_text().splitlines() if line]
    references = {row["scenario_id"]: row["reference_objective"] for row in gap_rows}
    witness_hash = digest(ROOT / "m1_witness/retailopt.py")
    dataset_hash = digest(GAP)
    runs = []
    tasks = []
    for candidate in analysis["curves"]:
        index = candidate["candidate_idx"]
        run_id = f"retailopt_gepa_stream_a0_v0.3/candidate_{index}"
        runs.append({
            "run_id": run_id,
            "dataset": "RetailOpt-190",
            "split": "gapcheck60",
            "comparison_group": "retailopt_gapcheck60_single_candidate",
            "method": "Official GEPA prompt evolution; one generation per task",
            "model": analysis["model"],
            "candidate_idx": index,
            "candidate_sha256": candidate["candidate_sha256"],
            "parent_candidate_idx": candidate["parents"][0],
            "candidate_role": "seed" if index == 0 else "accepted",
            "official_gepa_commit": analysis["official_gepa_commit"],
            "n": candidate["n"],
            "records": candidate["records"],
            "true_correct": candidate["true_correct"],
            "true_correct_rate": candidate["true_correct"] / candidate["n"],
            "proxy_match": candidate["proxy_match"],
            "phantom_proxy": candidate["phantom_proxy"],
            "unknown": candidate["truth_unknown"],
            "executable": candidate["executable"],
            "generation_errors": candidate["generation_errors"],
            "candidate_count": 1,
            "max_inner_repair_rounds": 0,
            "evaluation_role": "GEPA method-validation split; not untouched heldout",
            "score_definition": SCORE,
            "witness_sha256": witness_hash,
            "dataset_sha256": dataset_hash,
            "rollout_completion_tokens_excluding_reflection": candidate["completion_tokens"],
            "rollout_total_tokens_excluding_reflection": candidate["total_tokens"],
            "evidence": "raw_rollouts",
            "per_task_records_in_ledger": True,
            "source_path": "work/retailopt_gepa_stream_a0_v0.3/analysis.json",
            "notes": "Same 60 tasks as the historical gapcheck reports; no per-task Witness repair loop.",
        })
        for scenario_id in analysis["val_ids"]:
            relative = Path("rollouts") / candidate["candidate_sha256"] / f"{scenario_id}.json"
            record = read_json(A0 / relative)
            tasks.append({
                "run_id": run_id,
                "dataset": "RetailOpt-190",
                "split": "gapcheck60",
                "evaluation_role": "GEPA method-validation split; not untouched heldout",
                "scenario_id": scenario_id,
                "family": scenario_id.split("_")[1],
                "variant": scenario_id.rsplit("_", 1)[1],
                "candidate_idx": index,
                "candidate_sha256": candidate["candidate_sha256"],
                "parent_candidate_idx": candidate["parents"][0],
                "code_sha256": hashlib.sha256(record["code"].encode()).hexdigest(),
                "witness_sha256": witness_hash,
                "dataset_sha256": dataset_hash,
                "outcome": outcome(record),
                "exec_status": record.get("exec_status"),
                "solver_status": record.get("solver_status"),
                "objective": record.get("objective"),
                "reference_objective": references[scenario_id],
                "grade": record.get("grade"),
                "proxy_match": record["proxy_match"],
                "witness": record.get("witness"),
                "witness_rules": record.get("witness_rules", []),
                "true_correct": record["true_correct"],
                "phantom_proxy": record["phantom_proxy"],
                "generation_error": record.get("generation_error"),
                "completion_tokens": record.get("completion_tokens"),
                "total_tokens": record.get("total_tokens"),
                "llm_latency_s": record.get("llm_latency_s"),
                "source_record_path": f"work/retailopt_gepa_stream_a0_v0.3/{relative}",
                "score_definition": SCORE,
            })
    return runs, tasks, analysis


def build_report(runs: list[dict], tasks: list[dict]) -> str:
    lines = [
        "# RetailOpt 累积结果台账（v0.1）", "",
        "## 当前判断", "",
        "`57/60=95.0%` 是本次已核实报告中 RetailOpt gapcheck60 的单候选最高真正确率。此前同一60题的最好汇总结果为17/60=28.3%。这不是完整190题、严格 heldout、跨数据集或 SOTA 结论。", "",
        "不同切分、单/多候选、oracle 合并和评分口径不合并成一个总准确率。缺失的历史字段留空，不补零。", "",
        "## 同一 gapcheck60：单候选", "",
        "| 方法/运行 | N | 真正确 | 真正确率 | 代理通过 | 幻影代理成功 | 证据 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    group = [row for row in runs if row["comparison_group"] == "retailopt_gapcheck60_single_candidate"]
    for row in group:
        def count(key):
            return "—" if row.get(key) is None else str(row[key])
        lines.append(f"| {row['method']} / `{row['run_id']}` | 60 | {row['true_correct']} | "
                     f"{row['true_correct_rate']:.1%} | {count('proxy_match')} | {count('phantom_proxy')} | {row['evidence']} |")
    lines += ["", "## 历史完整190题：不能与60题直接排名", "",
              "| 方法/运行 | N | 真正确 | 真正确率 | 候选数 | 内环修复上限 | 口径 |",
              "|---|---:|---:|---:|---:|---:|---|"]
    for row in runs:
        if row["split"] != "full190":
            continue
        lines.append(f"| {row['method']} / `{row['run_id']}` | 190 | {row['true_correct']} | "
                     f"{row['true_correct_rate']:.1%} | {row['candidate_count']} | {row['max_inner_repair_rounds']} | {row['comparison_group']} |")
    lines += ["", "完整190题中的130/190和132/190分别来自双链仲裁与oracle并集，不与当前单候选57/60作直接优劣比较。", "",
              "## 当前候选按题族分解", "",
              "| 题族 | N | seed真正确 | 接受候选真正确 | seed幻影 | 接受候选幻影 | 接受候选UNKNOWN |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    by_family = defaultdict(list)
    for row in tasks:
        by_family[row["family"]].append(row)
    for family in sorted(by_family):
        rows = by_family[family]
        seed = [row for row in rows if row["candidate_idx"] == 0]
        accepted = [row for row in rows if row["candidate_idx"] == 1]
        lines.append(f"| {family.upper()} | {len(accepted)} | {sum(r['true_correct'] for r in seed)} | "
                     f"{sum(r['true_correct'] for r in accepted)} | {sum(r['phantom_proxy'] for r in seed)} | "
                     f"{sum(r['phantom_proxy'] for r in accepted)} | {sum(r['outcome'] == 'unknown' for r in accepted)} |")
    failures = [row for row in tasks if row["candidate_idx"] == 1 and not row["true_correct"]]
    lines += ["", "## 接受候选未获真正确的3题", "",
              "| 题目 | 结果 | 执行 | 求解状态 | 目标等级 | Witness规则 |",
              "|---|---|---|---|---|---|"]
    for row in failures:
        lines.append(f"| `{row['scenario_id']}` | {row['outcome']} | {row['exec_status']} | {row['solver_status']} | "
                     f"{row['grade']} | {','.join(row['witness_rules']) or '—'} |")
    lines += ["", "## 其他切分与排除项", "",
              "DVSA 的18/20=90.0%属于 dev20 saved-candidate replay，单列为 `retailopt_dev20`，不与gapcheck60排名。",
              "N2报告中的57/60是规则撰写成功数，不是模型解题正确数；EvalPlus的57/60属于代码数据集；IndustryOR的74%属于不同数据和业务评分，均未混入本表。", "",
              "## 数据文件与限制", "",
              "- `retailopt_runs.jsonl` / `.csv`：运行级汇总，含历史证据等级和比较分组。",
              "- `retailopt_gapcheck60_tasks.jsonl` / `.csv`：当前seed与接受候选共120条逐题记录。",
              "- 当前Witness、数据切片、候选和代码均记录SHA256；历史汇总暂缺统一的逐题哈希，不能声称已重算。",
              "- 当前token字段不含GEPA reflection成本；完整成本需另表汇总。",
              "- 57个真正确是本次Witness+参考目标定义下的 operational true correct，不是完整业务语义证明。", ""]
    return "\n".join(lines)


def build(outdir: Path) -> dict:
    current, tasks, analysis = current_runs_and_tasks()
    runs = historical_runs() + current
    assert len(tasks) == 120
    for candidate in analysis["curves"]:
        rows = [row for row in tasks if row["candidate_idx"] == candidate["candidate_idx"]]
        assert len(rows) == 60
        assert sum(row["true_correct"] for row in rows) == candidate["true_correct"]
        assert sum(row["phantom_proxy"] for row in rows) == candidate["phantom_proxy"]
    outdir.mkdir(parents=True, exist_ok=False)
    write_jsonl(outdir / "retailopt_runs.jsonl", runs)
    write_csv(outdir / "retailopt_runs.csv", runs)
    write_jsonl(outdir / "retailopt_gapcheck60_tasks.jsonl", tasks)
    write_csv(outdir / "retailopt_gapcheck60_tasks.csv", tasks)
    (outdir / "retailopt_detailed_report.md").write_text(build_report(runs, tasks))
    best = max((row for row in runs if row["comparison_group"] == "retailopt_gapcheck60_single_candidate"),
               key=lambda row: row["true_correct"])
    manifest = {
        "version": "retailopt_result_ledger_v0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_runs": len(runs),
        "n_task_records": len(tasks),
        "best_reviewed_gapcheck60_single_candidate": {
            "run_id": best["run_id"], "true_correct": best["true_correct"], "n": best["n"],
            "scope": "Best among reviewed reports, not a universal or SOTA claim.",
        },
        "historical_evidence": "Documented aggregates; not recomputed per task in this version.",
        "current_witness_sha256": digest(ROOT / "m1_witness/retailopt.py"),
        "current_gapcheck60_sha256": digest(GAP),
        "excluded_from_pooling": ["IndustryOR", "BWOR", "MAMO", "EvalPlus", "N2 rule-authoring success"],
    }
    (outdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="work/retailopt_result_ledger_v0.1")
    args = parser.parse_args()
    print(json.dumps(build(ROOT / args.out), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

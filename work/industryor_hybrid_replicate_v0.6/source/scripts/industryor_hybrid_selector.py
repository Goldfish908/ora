#!/usr/bin/env python3
"""Select between frozen full-chain and raw-selected IndustryOR outputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ora_agent import llm as llm_mod
from scripts.industryor_k3_pipeline import choose_with_llm, costs
from scripts.industryor_next_stage import score_solution

DATA = ROOT / "data/industryor/IndustryOR.json"
FULL_RUN = ROOT / "work/industryor_structured_full_v0.4"
RAW_RUN = ROOT / "work/industryor_k3_dev_v0.1"
PROTOCOL = ROOT / "docs/paper/industryor_hybrid_protocol_v0.1.md"
IMPLEMENTATION = ("scripts/industryor_hybrid_selector.py", "scripts/industryor_k3_pipeline.py",
                  "scripts/industryor_next_stage.py", "ora_agent/llm.py")
AUDIT_IDS = (4, 8, 9, 19, 20, 21, 25, 48)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_execution(candidate: dict) -> bool:
    record = candidate["record"]
    if record.get("exec_status") != "ok" or record.get("solver_status") != "optimal":
        return False
    if record.get("export_error") or not isinstance(candidate.get("objective"), (int, float)) \
            or not math.isfinite(candidate["objective"]):
        return False
    solution = candidate.get("solution")
    return bool(solution is None or (solution.get("solution_count", 0) >= 1
                                     and (solution.get("export") or {}).get("complete") is True))


def full_candidate(row: dict) -> dict:
    return {"candidate_id": "A", "source": "structured_full", "code": row["selected_code"],
            "record": row["final_record"], "solution": row["final_solution"],
            "objective": row["objective"], "score": row["final_score"],
            "business_accepted": row["business_correct"], "business_unverified": row["business_unverified"]}


def raw_candidate(row: dict) -> dict:
    selected = next(candidate for candidate in row["candidates"]
                    if candidate["candidate_id"] == row["selected_candidate"])
    solution_path = RAW_RUN / f"prob_{row['id']:03d}" / f"candidate_{row['selected_candidate']}" / "solution.json"
    solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
    return {"candidate_id": "B", "source": "raw_selected", "code": selected["code"],
            "record": selected["record"], "solution": solution, "objective": row["selected_objective"],
            "score": selected["score"], "business_accepted": selected["business_accepted"],
            "business_unverified": row["business_unverified"]}


def select_candidate(question: str, full: dict, raw: dict, case: Path, config) -> tuple[dict, dict, list[dict]]:
    if full["business_accepted"] or raw["business_accepted"]:
        selected = full if full["business_accepted"] else raw
        return selected, {"method": "independent_business", "record": None}, []
    if full["objective"] == raw["objective"]:
        return full, {"method": "same_objective_preserve_full", "record": None}, []
    full_valid = valid_execution(full)
    raw_valid = valid_execution(raw)
    if full_valid != raw_valid:
        selected = full if full_valid else raw
        return selected, {"method": "complete_execution", "record": None}, []
    selected, selection = choose_with_llm(full["source_id"], question, [full, raw], case, config)
    return selected, selection, [selection["record"]]


def load_inputs() -> tuple[list[dict], dict, dict, dict, dict]:
    rows = json.loads(DATA.read_text())
    full_analysis = json.loads((FULL_RUN / "analysis.json").read_text())
    raw_analysis = json.loads((RAW_RUN / "analysis.json").read_text())
    full = {row["id"]: row for row in full_analysis["results"] if row["arm"] == "structured_dag_full"}
    raw = {row["id"]: row for row in raw_analysis["results"]}
    return rows, full, raw, full_analysis, raw_analysis


def run_problem(row: dict, full_row: dict, raw_row: dict, outdir: Path, config: dict,
                resume: bool) -> dict:
    problem_id = row["id"]
    case = outdir / f"prob_{problem_id:03d}"
    case.mkdir(parents=True, exist_ok=True)
    result_path = case / "result.json"
    if resume and result_path.exists():
        previous = json.loads(result_path.read_text())
        if previous["run_config"] != config["public"]:
            raise ValueError(f"configuration changed for {problem_id}")
        return previous
    full = dict(full_candidate(full_row), source_id=problem_id)
    raw = dict(raw_candidate(raw_row), source_id=problem_id)
    selected, selection, records = select_candidate(row["en_question"], full, raw, case, config["llm_config"])
    reference = float(row["en_answer"])
    objective = selected["objective"]
    result = {"id": problem_id, "run_config": config["public"], "status": "completed",
              "selected_source": selected["source"], "selection_method": selection["method"],
              "selection": selection, "selected_code": selected["code"],
              "final_record": selected["record"], "final_solution": selected["solution"],
              "final_score": selected["score"], "objective": objective, "reference": reference,
              "match": objective is not None and abs(objective - reference) <= 0.1,
              "full_match": full_row["match"], "raw_match": raw_row["selected_match"],
              "business_correct": selected["business_accepted"],
              "business_unverified": selected["business_unverified"],
              "public_answer_used_for_selection": False,
              "selector_cost": costs(records)}
    write_json(result_path, result)
    (case / "error.json").unlink(missing_ok=True)
    return result


def safe_problem(row: dict, full_row: dict, raw_row: dict, outdir: Path, config: dict,
                 resume: bool) -> dict:
    try:
        return run_problem(row, full_row, raw_row, outdir, config, resume)
    except Exception as exc:
        case = outdir / f"prob_{row['id']:03d}"
        case.mkdir(parents=True, exist_ok=True)
        selection_path = case / "selection.json"
        records = [json.loads(selection_path.read_text())] if selection_path.exists() else []
        result = {"id": row["id"], "run_config": config["public"], "status": "runner_error",
                  "error": f"{type(exc).__name__}: {exc}", "match": False,
                  "objective": None, "reference": float(row["en_answer"]),
                  "business_correct": False, "business_unverified": row["id"] not in AUDIT_IDS,
                  "public_answer_used_for_selection": False, "selector_cost": costs(records)}
        write_json(case / "error.json", result)
        return result


def validate(results: list[dict], rows: list[dict]) -> None:
    references = {row["id"]: float(row["en_answer"]) for row in rows}
    assert len(results) == len(rows) == 100
    assert {row["id"] for row in results} == set(references)
    for row in results:
        if row["status"] != "completed":
            continue
        assert row["match"] == (row["objective"] is not None
                                and abs(row["objective"] - references[row["id"]]) <= 0.1)
        assert row["public_answer_used_for_selection"] is False
        record = row["selection"].get("record")
        if record:
            assert "en_answer" not in json.dumps(record["messages"])
        if row["id"] in AUDIT_IDS and row["final_solution"] is not None:
            assert row["final_score"] == score_solution(row["id"], row["final_solution"])
        if row["business_correct"]:
            assert not row["business_unverified"]
            assert (row["final_score"] or {}).get("business_correct") is True


def summarize(results: list[dict], started: float) -> dict:
    completed = [row for row in results if row["status"] == "completed"]
    cost_keys = ("logical_llm_calls", "new_llm_calls", "api_attempts", "completion_tokens",
                 "total_tokens", "llm_latency_s", "new_llm_latency_s")
    return {"n": len(results), "runner_errors": sum(row["status"] == "runner_error" for row in results),
            "hybrid_matches": sum(row["match"] for row in completed),
            "full_matches": sum(row["full_match"] for row in completed),
            "raw_matches": sum(row["raw_match"] for row in completed),
            "gained_vs_full_ids": [row["id"] for row in completed if row["match"] and not row["full_match"]],
            "lost_vs_full_ids": [row["id"] for row in completed if row["full_match"] and not row["match"]],
            "gained_vs_raw_ids": [row["id"] for row in completed if row["match"] and not row["raw_match"]],
            "lost_vs_raw_ids": [row["id"] for row in completed if row["raw_match"] and not row["match"]],
            "business_correct": sum(row["business_correct"] for row in completed),
            "false_business_accepts": sum(row["business_correct"] and
                                          (row["business_unverified"] or not row["final_score"]["business_correct"])
                                          for row in completed),
            "selected_sources": dict(Counter(row["selected_source"] for row in completed)),
            "selection_methods": dict(Counter(row["selection_method"] for row in completed)),
            "selector_cost": {key: sum(row["selector_cost"][key] for row in results) for key in cost_keys},
            "wall_seconds": round(time.monotonic() - started, 3)}


def write_report(outdir: Path, analysis: dict) -> None:
    summary = analysis["summary"]
    report = ROOT / "docs/paper/industryor_hybrid_results_v0.1.md"
    lines = ["# IndustryOR 完整管线与 Raw Selected 混合选择", "",
             "**范围：100 题，开发性冻结候选重放，不是 held-out。** 不使用 raw oracle 或参考答案选择。", "",
             "| 输出 | 目标匹配 abs≤0.1 | 独立业务正确（8题） |", "|---|---:|---:|",
             f"| raw k=3 selected | {summary['raw_matches']} | 3 |",
             f"| structured full memory | {summary['full_matches']} | 7 |",
             f"| hybrid selected | **{summary['hybrid_matches']}** | {summary['business_correct']} |", "",
             f"相对 full：新增 IDs={summary['gained_vs_full_ids']}，丢失 IDs={summary['lost_vs_full_ids']}。",
             f"相对 raw：新增 {len(summary['gained_vs_raw_ids'])}，丢失 {len(summary['lost_vs_raw_ids'])}。",
             f"误接受={summary['false_business_accepts']}；来源={summary['selected_sources']}；选择方式={summary['selection_methods']}。",
             "", "## 新增选择成本", "", "```json", json.dumps(summary["selector_cost"], indent=1), "```",
             "", "输入生成成本分别保留在原 full/raw 报告中；此处只计混合选择新增调用，不把缓存复用冒充新请求。",
             "COOPA=76 仅为不同模型和配置的公开参考；本结果是 COOPA-inspired 开发重放，不据此宣称 SOTA。",
             "", f"机器结果：`{outdir.relative_to(ROOT)}/analysis.json`；manifest：`{outdir.relative_to(ROOT)}/manifest.json`。", ""]
    report.write_text("\n".join(lines))
    figure_dir = ROOT / "docs/paper/figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    labels = ["raw selected", "structured full", "hybrid"]
    values = [summary["raw_matches"], summary["full_matches"], summary["hybrid_matches"]]
    business = [3, 7, summary["business_correct"]]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    for axis, vals, title, ylabel, color in (
            (axes[0], values, "Selected outputs (n=100)", "Objective matches", "#2563eb"),
            (axes[1], business, "Registered business audit (n=8)", "Independent correct", "#059669")):
        bars = axis.bar(labels, vals, color=color)
        for bar, value in zip(bars, vals):
            axis.text(bar.get_x() + bar.get_width() / 2, value + 0.5, str(value), ha="center")
        axis.set_title(title)
        axis.set_ylabel(ylabel)
        axis.tick_params(axis="x", rotation=12)
    fig.tight_layout()
    fig.savefig(figure_dir / "industryor_hybrid_v0.1.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    write_json(figure_dir / "industryor_hybrid_v0.1.json", analysis)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="work/industryor_hybrid_dev_v0.1")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    rows, full, raw, full_analysis, raw_analysis = load_inputs()
    outdir = (ROOT / args.out).resolve()
    if outdir.exists() and any(outdir.iterdir()) and not args.resume:
        raise ValueError("output directory is not empty; use --resume")
    outdir.mkdir(parents=True, exist_ok=True)
    llm_config = llm_mod.load_config()
    public = {"ids": [row["id"] for row in rows], "model": llm_config.model,
              "base_url": llm_config.base_url, "exposure": "development_frozen_candidates_not_heldout",
              "selection": "full_vs_raw_selected_without_reference_answer",
              "full_analysis_sha256": digest_file(FULL_RUN / "analysis.json"),
              "raw_analysis_sha256": digest_file(RAW_RUN / "analysis.json"),
              "protocol_sha256": digest_file(PROTOCOL),
              "implementation_sha256": {name: digest_file(ROOT / name) for name in IMPLEMENTATION}}
    config = {"public": public, "llm_config": llm_config}
    write_json(outdir / "run_config.json", public)
    for name in (*IMPLEMENTATION, "docs/paper/industryor_hybrid_protocol_v0.1.md"):
        destination = outdir / "source" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda row: safe_problem(row, full[row["id"]], raw[row["id"]],
                                                         outdir, config, args.resume), rows))
    results.sort(key=lambda row: row["id"])
    validate(results, rows)
    analysis = {"run_config": public, "summary": summarize(results, started), "results": results,
                "input_costs": {"structured_full": full_analysis["summary"]["arms"]["structured_dag_full"]["cost"],
                                "raw_k3": raw_analysis["summary"]["cost_k3"]}}
    write_json(outdir / "analysis.json", analysis)
    write_json(outdir / "manifest.json", {"run_config": public, "registered_n": 100,
                                          "accounted_n": len(results),
                                          "completed_n": sum(row["status"] == "completed" for row in results),
                                          "runner_error_n": sum(row["status"] == "runner_error" for row in results),
                                          "public_answer_used_for_selection": False})
    print(json.dumps(analysis["summary"], ensure_ascii=False, indent=1), flush=True)
    if analysis["summary"]["runner_errors"] == 0:
        write_report(outdir, analysis)


if __name__ == "__main__":
    main()

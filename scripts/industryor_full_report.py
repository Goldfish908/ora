#!/usr/bin/env python3
"""Validate IndustryOR run artifacts and build the full comparison report."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts.industryor_full_pipeline import AUDIT_IDS, DATA, baseline_records, failure_classification
from scripts.industryor_next_stage import score_solution
from scripts.m3_industryor import SCIP_CONTRACT, load_priors

DEFAULT_RUN = ROOT / "work/industryor_full_qwen_v0.1"
DEFAULT_REPORT = ROOT / "docs/paper/industryor_full_pipeline_results_v0.1.md"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def matched(objective, reference: float) -> bool:
    return isinstance(objective, (int, float)) and math.isfinite(objective) and abs(objective - reference) <= 0.1


def bool_text(value) -> str:
    if value is None:
        return "未审计"
    return "是" if value else "否"


def number(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def validate_run(run_dir: Path, require_full: bool = True) -> dict:
    analysis = json.loads((run_dir / "analysis.json").read_text())
    saved_config = json.loads((run_dir / "run_config.json").read_text())
    saved_manifest = json.loads((run_dir / "manifest.json").read_text())
    config = analysis["run_config"]
    assert config == saved_config == saved_manifest["run_config"]
    rows = json.loads(DATA.read_text())
    problems = {row["id"]: row for row in rows}
    results = analysis["results"]
    ids = [row["id"] for row in results]
    assert len(ids) == len(set(ids)) == len(config["ids"])
    assert set(ids) == set(config["ids"])
    if require_full:
        assert len(rows) == len(results) == 100
        assert set(ids) == set(problems)
        assert saved_manifest["initial_generation_n"] == 100
        assert analysis["summary"]["retry_accounting_complete"] is True
    assert hashlib.sha256(DATA.read_bytes()).hexdigest() == config["dataset_sha256"]
    protocol = run_dir / "source/docs/paper/industryor_full_pipeline_protocol_v0.1.md"
    if protocol.exists():
        assert hashlib.sha256(protocol.read_bytes()).hexdigest() == config["protocol_sha256"]
    elif require_full:
        raise AssertionError("executed protocol snapshot is missing")
    source_verified = 0
    for name, expected in config["implementation_sha256"].items():
        path = run_dir / "source" / name
        if path.exists():
            assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
            source_verified += 1
        elif require_full:
            raise AssertionError(f"executed source snapshot is missing: {name}")
    assert "api_key" not in json.dumps(config)
    old = baseline_records()
    response_count = execution_count = score_count = 0
    for result in results:
        problem_id = result["id"]
        case = run_dir / f"prob_{problem_id:03d}"
        terminal = case / ("result.json" if result["status"] == "completed" else "error.json")
        assert json.loads(terminal.read_text()) == result
        row = problems[problem_id]
        assert result["reference"] == float(row["en_answer"])
        assert result["objective_match_abs_0_1"] == matched(result["objective"], result["reference"])
        prompt = load_priors() + "\n\n" + SCIP_CONTRACT + row["en_question"]
        assert (case / "prompt.txt").read_text() == prompt
        initial = json.loads((case / "initial_response.json").read_text())
        generation_zero = json.loads((case / "generation_00.json").read_text())
        assert generation_zero["response"] == initial
        assert generation_zero["messages"] == [{"role": "user", "content": prompt}]
        assert initial["prompt_sha256"] == result["prompt_sha256"] == digest(prompt)
        assert initial["model"] == config["llm"]["model"]
        response_count += 1
        generation_paths = sorted(case.glob("generation_[0-9][0-9].json"))
        generations = [json.loads(path.read_text()) for path in generation_paths]
        assert [path.name for path in generation_paths] == [f"generation_{i:02d}.json" for i in range(len(generations))]
        successful = [record for record in generations if record.get("response")]
        assert result["llm_calls"] == len(successful)
        assert result["retry_accounting_complete"] == all(
            "request_attempts" in record["response"] for record in successful)
        if require_full:
            assert all("request_attempts" in record for record in generations if record.get("error"))
        for record in generations:
            assert record["messages"][0] == {"role": "user", "content": prompt}
            attempts = record.get("request_attempts") or record.get("response", {}).get("request_attempts")
            if attempts is not None:
                assert [item["attempt"] for item in attempts] == list(range(1, len(attempts) + 1))
                assert sum(item["outcome"] == "success" for item in attempts) == (1 if record.get("response") else 0)
        expected_latency = sum((record["response"].get("request_wall_s")
                                or record["response"].get("latency_s") or 0) for record in successful)
        assert abs(result["llm_latency_s"] - expected_latency) < 0.01
        history = result["history"]
        assert result["candidate_evaluations"] == len(history)
        for entry in history:
            sandbox = case / f"round_{entry['round']}"
            execution = json.loads((sandbox / "execution.json").read_text())
            code = entry["code"]
            assert execution["code_sha256"] == entry["record"]["code_sha256"] == digest(code)
            assert execution["instrumented_sha256"] == digest((sandbox / "gen.py").read_text())
            assert (sandbox / "stdout.txt").is_file()
            assert (sandbox / "stderr.txt").is_file()
            solution_path = sandbox / "solution.json"
            solution = json.loads(solution_path.read_text()) if solution_path.exists() else None
            if problem_id in AUDIT_IDS and isinstance(solution, dict) and solution.get("solution_count", 0) >= 1:
                assert entry["score"] == score_solution(problem_id, solution)
                score_count += 1
            else:
                assert entry["score"] is None
            execution_count += 1
        if result["status"] == "completed":
            assert (case / "final.py").read_text() == result["final_code"]
            if result["final_solution"] is not None:
                assert json.loads((case / "solution.json").read_text()) == result["final_solution"]
            if result["stop_reason"] == "baseline_fallback":
                assert result["final_code"] == result["initial_code"]
                assert result["final_score"] == result["initial_score"]
            if result["accepted"]:
                assert result["final_score"]["business_correct"] is True
                assert result["accepted_but_business_incorrect"] is False
            if problem_id not in AUDIT_IDS:
                assert result["business_unverified"] is True
                assert result["accepted"] is False
            assert result["baseline_z2"] == old[problem_id]["z2"]
    return {
        "registered_n": len(results), "initial_responses_verified": response_count,
        "executions_verified": execution_count, "business_scores_recomputed": score_count,
        "source_snapshots_verified": source_verified,
        "retry_accounting_complete": analysis["summary"]["retry_accounting_complete"],
        "analysis_sha256": hashlib.sha256((run_dir / "analysis.json").read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256((run_dir / "manifest.json").read_bytes()).hexdigest(),
    }


def audit_evidence(row: dict) -> str:
    score = row.get("final_score") or {}
    details = []
    missing = [name for name, item in score.get("variable_audit", {}).items() if not item.get("present")]
    wrong_domain = [name for name, item in score.get("variable_audit", {}).items()
                    if item.get("present") and not item.get("passed")]
    if missing:
        details.append("缺少审计变量 " + ", ".join(missing[:4])
                       + (f" 等{len(missing)}个" if len(missing) > 4 else ""))
    if wrong_domain:
        details.append("变量域不符 " + ", ".join(wrong_domain[:6]))
    observed = list((row.get("final_solution") or {}).get("variables", {}))
    if missing and observed:
        details.append("实际导出名称示例 " + ", ".join(observed[:4]))
    if score.get("audit_status") == "blocked":
        details.extend(score.get("blocking_reasons", []))
    if score.get("audit_status") == "complete" and not score.get("business_correct"):
        details.extend(score.get("violations", [])[:5])
    history = row.get("history") or []
    record = history[-1].get("record", {}) if history else {}
    if record.get("export_error"):
        details.append(record["export_error"])
    if record.get("exec_status") == "crash":
        details.append((record.get("stderr_tail") or "unknown crash").splitlines()[-1])
    if row.get("error"):
        details.append(row["error"])
    if not details and row.get("business_unverified"):
        return "目标不匹配；未注册独立业务审计，不能进一步断言业务原因"
    return "；".join(details) if details else "见目标值、执行状态与独立评分"


def comparison_rows(analysis: dict) -> list[dict]:
    old = baseline_records()
    result = []
    for row in analysis["results"]:
        problem_id = row["id"]
        reference = row["reference"]
        old_row = old[problem_id]
        old_match = {arm: matched(old_row[arm].get("objective"), reference) for arm in ("z0", "z1", "z2")}
        final_score = row.get("final_score") or {}
        initial_score = row.get("initial_score") or {}
        evidence = ("unregistered" if problem_id not in AUDIT_IDS else
                    final_score.get("audit_status") or "no_solution")
        result.append({
            "id": problem_id, "objective": row["objective"], "reference": reference,
            "initial_objective": row.get("initial_objective"),
            "initial_match": row.get("initial_objective_match_abs_0_1"),
            "match": row["objective_match_abs_0_1"], "exec_status": row["exec_status"],
            "solver_status": row["solver_status"], "status": row["status"],
            "stop_reason": row["stop_reason"],
            "failure_class": failure_classification(row),
            "runner_failure_class_original": row["failure_class"],
            "accepted": row["accepted"], "business_unverified": row["business_unverified"],
            "business_evidence": evidence, "audit_evidence": audit_evidence(row),
            "initial_business_correct": initial_score.get("business_correct"),
            "final_business_correct": final_score.get("business_correct"),
            "initial_audit_status": initial_score.get("audit_status"),
            "final_audit_status": final_score.get("audit_status"),
            "score_violations": final_score.get("violations", []),
            "llm_calls": row["llm_calls"], "api_attempts": row["api_attempts"],
            "total_tokens": row["total_tokens"], "llm_latency_s": row["llm_latency_s"],
            "candidate_evaluations": row["candidate_evaluations"], "solver_runs": row["solver_runs"],
            "deterministic_transforms": row["deterministic_transforms"],
            "failed_deterministic_transforms": row["failed_deterministic_transforms"],
            "patch_errors": [entry["deterministic_patch_error"] for entry in row["history"]
                             if entry.get("deterministic_patch_error")],
            "objective_recovery": row.get("initial_objective_match_abs_0_1") is False
            and row["objective_match_abs_0_1"],
            "objective_loss": row.get("initial_objective_match_abs_0_1") is True
            and not row["objective_match_abs_0_1"],
            "old": old_row, "old_match": old_match,
            "delta_vs_z2": int(row["objective_match_abs_0_1"]) - int(old_match["z2"]),
            "error": row.get("error"),
        })
    return result


def baseline_costs() -> dict:
    records = baseline_records()
    costs = {}
    for arm in ("z0", "z1", "z2"):
        rows = [values[arm] for values in records.values()]
        costs[arm] = {
            "llm_calls": sum(row["round"] for row in rows),
            "completion_tokens_recorded": sum(row.get("completion_tokens") or 0 for row in rows),
            "reasoning_tokens_recorded": sum(row.get("reasoning_tokens") or 0 for row in rows),
            "token_rows": sum(row.get("completion_tokens") is not None for row in rows),
            "llm_latency_s_recorded": round(sum(row.get("llm_latency_s") or 0 for row in rows), 3),
            "latency_rows": sum(row.get("llm_latency_s") is not None for row in rows),
            "legacy_candidate_evaluations": sum(row["round"] for row in rows),
        }
    return costs


def build_report(run_dir: Path = DEFAULT_RUN, report_path: Path = DEFAULT_REPORT,
                 figure_dir: Path = ROOT / "docs/paper/figures", require_full: bool = True) -> tuple[Path, Path, Path]:
    run_dir = run_dir.resolve()
    analysis = json.loads((run_dir / "analysis.json").read_text())
    validation = validate_run(run_dir, require_full)
    summary = analysis["summary"]
    comparisons = comparison_rows(analysis)
    n = len(comparisons)
    selected = [row["id"] for row in comparisons]
    old_metrics = {}
    for arm in ("z0", "z1", "z2"):
        old_metrics[arm] = {
            "n": n,
            "objective_matches_abs_0_1": sum(row["old_match"][arm] for row in comparisons),
            "exec_ok": sum(row["old"][arm].get("exec_status") == "ok" for row in comparisons),
            "optimal": sum(row["old"][arm].get("solver_status") == "optimal" for row in comparisons),
        }
    new_metrics = {"n": n, "objective_matches_abs_0_1": summary["objective_matches_abs_0_1"],
                   "exec_ok": summary["exec_ok"], "optimal": summary["optimal"]}
    costs = baseline_costs()
    generation_records = []
    for problem_id in selected:
        for path in sorted((run_dir / f"prob_{problem_id:03d}").glob("generation_[0-9][0-9].json")):
            generation_records.append(json.loads(path.read_text()))
    retries = 0
    failed_wall = 0.0
    for record in generation_records:
        attempts = record.get("request_attempts") or record.get("response", {}).get("request_attempts") or []
        retries += max(0, len(attempts) - 1)
        if record.get("error"):
            failed_wall += record.get("wall_s") or 0
    audit_rows = [row for row in comparisons if row["id"] in AUDIT_IDS]
    improved = [row["id"] for row in comparisons if row["delta_vs_z2"] > 0]
    worsened = [row["id"] for row in comparisons if row["delta_vs_z2"] < 0]
    recovered = [row["id"] for row in comparisons if row["objective_recovery"]]
    lost = [row["id"] for row in comparisons if row["objective_loss"]]
    semantic_recoveries = [row for row in audit_rows
                           if row["initial_audit_status"] == "complete"
                           and row["initial_business_correct"] is False
                           and row["final_business_correct"] is True]
    incomplete_audits = [row["id"] for row in audit_rows if row["business_evidence"] != "complete"]
    outcome_counts = Counter(row["failure_class"] for row in comparisons)
    export_errors = Counter()
    crash_errors = Counter()
    for result in analysis["results"]:
        for entry in result["history"]:
            record = entry["record"]
            if record.get("export_error"):
                export_errors[record["export_error"]] += 1
            if record.get("exec_status") == "crash":
                crash_errors[(record.get("stderr_tail") or "unknown crash").splitlines()[-1]] += 1
    derived_summary = {
        "outcome_classes_recomputed_from_business_evidence": dict(sorted(outcome_counts.items())),
        "objective_recovered_ids": recovered, "objective_lost_ids": lost,
        "business_semantic_recovery_ids": [row["id"] for row in semantic_recoveries],
        "audit_incomplete_or_blocked_ids": incomplete_audits,
        "historical_export_errors": dict(export_errors),
        "historical_crash_last_lines": dict(crash_errors),
    }
    comparison = {"run_config": analysis["run_config"], "validation": validation,
                  "old_metrics_same_ids": old_metrics, "new_metrics": new_metrics,
                  "baseline_costs": costs, "derived_summary": derived_summary, "results": comparisons}
    comparison_path = run_dir / "comparison.json"
    write_json(comparison_path, comparison)
    scope = "完整 IndustryOR-100" if require_full else f"工程冒烟（{n} 题，非全集结论）"
    recovery_text = "; ".join(f"ID{row['id']}(LLM={row['llm_calls']}, deterministic={row['deterministic_transforms']})"
                              for row in semantic_recoveries)
    lines = [
        "# IndustryOR 全管线结果与旧基线对照",
        "",
        f"**范围：{scope}。** 统一使用绝对误差 `|objective-en_answer| <= 0.1`。目标匹配不是完整业务正确率。",
        "",
        "## 主要结果",
        "",
        f"- 新管线目标匹配 **{new_metrics['objective_matches_abs_0_1']}/{n}**；初始候选为 {summary['initial_objective_matches_abs_0_1']}/{n}。本轮有 {len(recovered)} 题从不匹配变为匹配，{len(lost)} 题从匹配变为不匹配；这是目标值变化，不是业务正确性证明。",
        f"- 同一批 ID 的旧 z2 为 **{old_metrics['z2']['objective_matches_abs_0_1']}/{n}**，新管线差值 **{new_metrics['objective_matches_abs_0_1'] - old_metrics['z2']['objective_matches_abs_0_1']:+d} 题**；改善 {len(improved)} 题，退步 {len(worsened)} 题，**没有超过旧 z2**。",
        f"- 独立业务审计仅覆盖 {len(audit_rows)} 个已注册 ID：初始正确 {summary['business_audit']['initial_business_correct']}，最终正确 {summary['business_audit']['final_business_correct']}；审计不完整或 blocked 的 ID={incomplete_audits}。其余题目没有完整业务验证，不计作业务正确。",
        f"- 有明确初始业务违例并最终恢复的题目：{recovery_text or '无'}。这里区分真实语义恢复与仅有名称/导出证据不足。",
        f"- runner error={summary['runner_errors']}，错误业务接受={summary['accepted_but_business_incorrect']}， harmed-win={summary['harmed_win']}。本轮初始完整业务正确为 {summary['business_audit']['initial_business_correct']}，回滚为 {summary['rollbacks']}，所以 harmed-win=0 不是充分的 win-safe 证明。",
        "",
        "这些差分不是严格消融：新旧服务 revision 未被证明一致，采样也没有共享随机种子。不能将差值全部归因于 Witness、确定性修复或 DAG，也不据此声称 SOTA 或通用自进化。",
        "",
        "## 同一分母的结果表",
        "",
        "| 方法 | n | 目标匹配 abs≤0.1 | exec_ok | optimal |",
        "|---|---:|---:|---:|---:|",
    ]
    for arm in ("z0", "z1", "z2"):
        metrics = old_metrics[arm]
        lines.append(f"| 旧 {arm}（日志复算） | {n} | {metrics['objective_matches_abs_0_1']} | {metrics['exec_ok']} | {metrics['optimal']} |")
    lines.append(f"| 新 Qwen + 当前管线 | {n} | {new_metrics['objective_matches_abs_0_1']} | {new_metrics['exec_ok']} | {new_metrics['optimal']} |")
    if require_full:
        lines.extend(["", f"COOPA 的公开 76/100 只作不同模型与配置的参考，不与本表构成同条件排名；数值差为 {new_metrics['objective_matches_abs_0_1'] - 76:+d}，不称为同条件超越。"])
    lines.extend([
        "",
        "## 独立业务审计",
        "",
        "这里重新读取每轮 `solution.json` 并调用独立评分器，不信任 solver 的 `optimal` 或打印目标值。`business_unverified` 和 `invalid_solution` 都不等于业务错误；后者表示当前证据无法完成审计。只有 `complete` 且规则违例才是明确业务拒绝。",
        "",
        "| ID | 初始审计状态 | 最终审计状态 | 最终独立通过 | 修复路径 | 主要证据 |",
        "|---:|---|---|---|---|---|",
    ])
    for row in audit_rows:
        path = f"LLM={row['llm_calls']}, det={row['deterministic_transforms']}, {row['stop_reason']}"
        evidence = row["audit_evidence"] if row["final_business_correct"] is not True else "全部已注册业务检查通过"
        lines.append(f"| {row['id']} | {row['initial_audit_status'] or '无可用解'} | {row['final_audit_status'] or '无可用解'} | {bool_text(row['final_business_correct'])} | {path} | {evidence} |")
    lines.extend([
        "",
        "## 成本与执行轨迹",
        "",
        f"- 新管线成功生成 {summary['llm_calls']} 次，其中本进程实际调用 {summary['new_llm_calls']} 次；API attempts={summary['api_attempts']}，可见网络重试={retries}，重试元数据完整={summary['retry_accounting_complete']}。",
        f"- tokens：prompt={summary['prompt_tokens']}，completion={summary['completion_tokens']}，reasoning={summary['reasoning_tokens']}，total={summary['total_tokens']}。成功生成墙钟累计 {summary['llm_latency_s']:.3f}s；失败生成额外墙钟 {failed_wall:.3f}s。并行总墙钟 {summary['wall_seconds']:.3f}s。",
        f"- 相对旧 z2：LLM 调用 {summary['llm_calls'] - costs['z2']['llm_calls']:+d} 次（{summary['llm_calls'] / costs['z2']['llm_calls'] - 1:+.1%}），completion tokens {summary['completion_tokens'] - costs['z2']['completion_tokens_recorded']:+d}（{summary['completion_tokens'] / costs['z2']['completion_tokens_recorded'] - 1:+.1%}），已记录 LLM 延迟 {summary['llm_latency_s'] - costs['z2']['llm_latency_s_recorded']:+.3f}s（{summary['llm_latency_s'] / costs['z2']['llm_latency_s_recorded'] - 1:+.1%}）。",
        f"- 候选评估 {summary['candidate_evaluations']} 次，实际 SCIP {summary['solver_runs']} 次，缓存执行复用 {summary['reused_candidate_evaluations']} 次；确定性变换 {summary['deterministic_transforms']}，失败变换 {summary['failed_deterministic_transforms']}，回滚 {summary['rollbacks']}。",
        "",
        "| 旧方法 | LLM 调用 | 已记录 completion tokens | token 记录覆盖 | 已记录 LLM 延迟(s) | 延迟记录覆盖 |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for arm in ("z0", "z1", "z2"):
        cost = costs[arm]
        lines.append(f"| {arm} | {cost['llm_calls']} | {cost['completion_tokens_recorded']} | {cost['token_rows']}/100 | {cost['llm_latency_s_recorded']:.3f} | {cost['latency_rows']}/100 |")
    lines.extend(["", "旧日志没有与新管线完全相同的 DAG/插桩成本字段，因此不伪造旧的 DAG 开销。", "", "## 结果分类与失败原因", "",
                  "分类由原始执行和独立业务证据重新推导；原 runner 标签保留在 `comparison.json`。`invalid_solution` 归入 `business_unknown`，不冒充已知业务错误。", "",
                  "| 分类 | 题数 |", "|---|---:|"])
    for name, count in sorted(outcome_counts.items()):
        lines.append(f"| {name} | {count} |")
    lines.extend(["", f"本轮初始→最终目标恢复 ID：{recovered or '无'}；目标损失 ID：{lost or '无'}。",
                  f"相对 z2 改善的 ID：{improved or '无'}。", f"相对 z2 退步的 ID：{worsened or '无'}。",
                  f"重复候选停止 ID：{[row['id'] for row in comparisons if row['stop_reason'] == 'duplicate_candidate'] or '无'}。",
                  "", "### 历史执行与修复信号", "",
                  "以下信号可出现在后来成功的候选之前，不等于最终失败题数。原始 stderr 和逐轮轨迹均保留。",
                  "", "| 导出错误 | 发生次数 |", "|---|---:|"])
    for error, count in sorted(export_errors.items()):
        lines.append(f"| {error} | {count} |")
    lines.extend(["", "| crash 最后一行 | 发生次数 |", "|---|---:|"])
    for error, count in sorted(crash_errors.items()):
        lines.append(f"| `{error}` | {count} |")
    for row in comparisons:
        if row["patch_errors"]:
            lines.append(f"\nID {row['id']} 的确定性修复失败：" + "；".join(row["patch_errors"]))
    lines.extend(["", "### 未匹配题目的逐题证据", "",
                  "| ID | 新目标 | 参考目标 | 旧 z2 目标 | 执行/求解状态 | 停止原因 | 分类 | 观测证据 |",
                  "|---:|---:|---:|---:|---|---|---|---|"])
    for row in comparisons:
        if row["match"]:
            continue
        lines.append(f"| {row['id']} | {number(row['objective'])} | {number(row['reference'])} | {number(row['old']['z2'].get('objective'))} | {row['exec_status']}/{row['solver_status']} | {row['stop_reason']} | {row['failure_class']} | {row['audit_evidence']} |")
    lines.extend([
        "",
        "## 可追溯性与限制",
        "",
        f"- 核验了 {validation['initial_responses_verified']} 份初始响应、{validation['executions_verified']} 份执行记录，并重算 {validation['business_scores_recomputed']} 份业务评分；实际执行的源码快照 {validation['source_snapshots_verified']} 份。",
        "- `analysis.json` 保存逐题结果，`manifest.json` 登记全集，`comparison.json` 保存逐题新旧差分；每题目录包含 prompt、原始响应、代码、stdout/stderr、执行、轨迹、DAG 和成本。",
        "- 只使用当前注册的 19/20/21 窄修复及 8 题独立审计；未把局部 Witness 或 ID 20 名称适配推广为跨族有效性。",
        "- 初始候选和修复使用同一生成配置；未读取 `en_answer` 生成或修复。旧 79/100 是相对误差 1% 口径，不与本报告混用。",
        "",
        "复验命令：`python3 scripts/industryor_full_report.py`；完整测试命令见项目最终回归记录。",
        "",
    ])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines))
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    names = ["z0", "z1", "z2", "New"]
    match_values = [old_metrics[arm]["objective_matches_abs_0_1"] for arm in names[:3]] + [new_metrics["objective_matches_abs_0_1"]]
    bars = axes[0].bar(names, match_values, color=["#94a3b8", "#64748b", "#2563eb", "#059669"])
    for bar, value in zip(bars, match_values):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + n * 0.015, str(value), ha="center")
    axes[0].set_ylim(0, n * 1.13)
    axes[0].set_ylabel("Objective matches")
    axes[0].set_title(f"Absolute error <= 0.1 (n={n})")
    positions = list(range(4))
    exec_values = [old_metrics[arm]["exec_ok"] for arm in names[:3]] + [new_metrics["exec_ok"]]
    optimal_values = [old_metrics[arm]["optimal"] for arm in names[:3]] + [new_metrics["optimal"]]
    bars1 = axes[1].bar([value - 0.18 for value in positions], exec_values, width=0.36,
                        label="exec_ok", color="#60a5fa")
    bars2 = axes[1].bar([value + 0.18 for value in positions], optimal_values, width=0.36,
                        label="optimal", color="#1e40af")
    for bars in (bars1, bars2):
        for bar in bars:
            axes[1].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + n * 0.015,
                         str(int(bar.get_height())), ha="center", fontsize=8)
    axes[1].set_xticks(positions, names)
    axes[1].set_ylim(0, n * 1.16)
    axes[1].set_title("Execution is not business correctness")
    axes[1].legend(frameon=False, fontsize=9)
    audit_values = [summary["business_audit"]["initial_business_correct"],
                    summary["business_audit"]["final_business_correct"]]
    bars = axes[2].bar(["Initial", "Final"], audit_values, color=["#f59e0b", "#059669"], width=0.55)
    for bar, value in zip(bars, audit_values):
        axes[2].text(bar.get_x() + bar.get_width() / 2, value + 0.1, str(value), ha="center")
    axes[2].set_ylim(0, max(8, len(audit_rows)) + 1)
    axes[2].set_ylabel("Independently correct")
    axes[2].set_title(f"Business audit n={len(audit_rows)}; {len(incomplete_audits)} incomplete/blocked", fontsize=11)
    figure_scope = "IndustryOR-100 (full)" if require_full else f"Engineering smoke (n={n}; not full)"
    fig.text(0.5, 0.025,
             f"{figure_scope}; same IDs per arm. Business audit is separate; {summary['business_unverified']} cases are unverified. "
             "Model revisions are not proven identical; no causal ablation or SOTA claim.",
             ha="center", fontsize=9, color="#444444")
    fig.tight_layout(rect=(0, 0.10, 1, 0.96))
    figure_dir.mkdir(parents=True, exist_ok=True)
    image_path = figure_dir / "industryor_full_qwen_v0.1.png"
    fig.savefig(image_path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    figure_data = {"scope": scope, "n": n, "objective_tolerance": "absolute_error_at_most_0.1",
                   "old_metrics_same_ids": old_metrics, "new_metrics": new_metrics,
                   "business_audit": summary["business_audit"],
                   "business_unverified": summary["business_unverified"],
                   "derived_summary": derived_summary,
                   "delta_vs_z2": new_metrics["objective_matches_abs_0_1"] - old_metrics["z2"]["objective_matches_abs_0_1"],
                   "improved_ids": improved, "worsened_ids": worsened,
                   "validation": validation,
                   "claims": {"controlled_model_revision_ablation": False, "sota_claim": False,
                              "general_self_evolution_claim": False},
                   "sources": [f"{run_dir.relative_to(ROOT)}/analysis.json",
                               f"{run_dir.relative_to(ROOT)}/comparison.json",
                               "docs/paper/industryor_full_pipeline_protocol_v0.1.md"]}
    data_path = figure_dir / "industryor_full_qwen_v0.1.json"
    write_json(data_path, figure_data)
    return report_path, image_path, data_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--figure-dir", type=Path, default=ROOT / "docs/paper/figures")
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    paths = build_report(args.run, args.report, args.figure_dir, not args.allow_partial)
    print(json.dumps({"report": str(paths[0]), "figure": str(paths[1]), "data": str(paths[2])},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

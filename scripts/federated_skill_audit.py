#!/usr/bin/env python3
"""Audit federated_sub_milp_v0.1 against the real SkillRegistry lifecycle."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ora_agent.federated_skill_candidate import (
    SOURCE_ROOT,
    audit_candidate,
    load_source_audit,
    prepare_candidate,
)

DEFAULT_OUT = ROOT / "work/federated_skill_audit_v0.1"


def _number(value: Any, digits: int = 6) -> str:
    if value is None:
        return "NA"
    return f"{float(value):.{digits}f}"


def _yn(value: Any) -> str:
    return "是" if value is True else "否"


def render_report(audit: Mapping[str, Any]) -> str:
    asset = audit["asset"]
    method = audit["method"]
    registry = audit["registry"]
    decision = audit["decision"]
    scoped = audit["scoped_findings"]
    coverage = audit["coverage"]
    provenance = audit["provenance"]
    lines = [
        "# federated_sub_milp_v0.1 SkillRegistry 真实审计",
        "",
        f"## 结论：不晋升（asset status = `{decision['status']}`）",
        "",
        (
            "本候选是 method-level `SkillAsset`，但现有真实记录没有满足注册器的非零 "
            "`gained_true` 要求；三个场景又都来自同一 problem 的预声明开发实验，不能证明跨任务晋升。"
            "审计没有调用 `promote` 绕过 dev 失败，资产也不能被 registry 选择或激活。"
        ),
        "",
        f"- 审计 HEAD：`{audit['repository_head']}`",
        f"- 源实验 HEAD：`{provenance['source_generation_git_head']}`",
        f"- 源 audit SHA256：`{provenance['source_audit_sha256']}`",
        f"- direct-full baseline：`{method['baseline_implementation_sha256']}`",
        f"- sub-MILP treatment：`{method['treatment_implementation_sha256']}`",
        f"- official evaluator binding：`{method['evaluator_sha256']}`",
        f"- baseline/treatment hash 不同：**{_yn(method['implementation_hashes_differ'])}**",
        "",
        (
            "control 是独立执行的 direct-full 臂和独立成本账本，每次从共同 root 做一次全变量求解；"
            "treatment 是 single-chain 声明式 sub-MILP 臂，最终 best 必须确有固定变量。"
            "两臂绑定不同的实现源文件及 hash，共享同一官方评价器与公开输入。"
        ),
        "",
        "## 资产契约与证据边界",
        "",
        f"- trigger：`{json.dumps(asset['trigger_signature'], ensure_ascii=False, sort_keys=True)}`",
        f"- required inputs：{len(asset['required_inputs'])} 项，包括 incumbent、parent hash、全部公开数据、违规、模式和求解限制。",
        f"- dataset scope：`{asset['dataset_scope'][0]}`",
        f"- domain scope：`{asset['domain_scope'][0]}`",
        f"- API scope：`{', '.join(asset['api_scope'])}`",
        f"- schema scope：`{asset['schema_scope'][0]}`",
        f"- required seeds：`{coverage['required_seeds']}`；实际覆盖：`{coverage['observed_seeds']}`",
        f"- dev tasks：`{coverage['dev_tasks']}`；gapcheck tasks：`{coverage['gapcheck_tasks']}`",
        f"- gapcheck 分类：`{coverage['gapcheck_classification']}`",
        "",
        (
            "资产明确限定只能编辑 released binary decisions，禁止改变 fixed variables、公开数据/约束/目标、"
            "隐藏违规、用官方反馈选父或扩展、把 gaplimit 称为全局最优，以及跨 scope 激活。"
            "不变量包括 parent hash、完整变量划分、fixed values、无新增违规、目标不退化、UNKNOWN 拒绝和官方事后复评。"
            "正反例、near-miss、ambiguous 和 out-of-scope 示例完整保存在 `audit.json` 的 `asset` 中。"
        ),
        "",
        "## 真实配对结果",
        "",
        (
            "下表的 official feasible/quality/true/objective 均由每条保存的 `official_evaluation.json` "
            "通过当前 `official_metrics` 重新计算，并与源 audit 摘要逐项核对；final artifact 同时匹配冻结 manifest、"
            "源 best hash 和官方输入 hash。指标不是在本审计代码中填写的。"
        ),
        "",
        "| Split | Scenario | Root（前12位） | Arm | Feasible | Quality | True | Objective | Sub-MILP fixed |",
        "|---|---|---|---|---:|---:|---|---:|---:|",
    ]
    for pair in audit["pairs"]:
        for arm_name, arm in (("direct-full", pair["control"]), ("sub-MILP", pair["treatment"])):
            official = arm["official"]
            spec = arm["spec_signature"] or {}
            lines.append(
                f"| {pair['split']} | {pair['scenario']} | `{pair['initial_sha256'][:12]}` | {arm_name} | "
                f"{official['feasible']} | {_number(official['quality'], 12)} | {official['true_correct']} | "
                f"{_number(official['objective'], 9)} | {spec.get('fixed_variable_count', 0)} |"
            )
    lines.extend([
        "",
        "| Scenario | Δ quality | Δ objective（最大化） | Control search s | Treatment search s | Control total s | Treatment total s | Child eval C/T | Solver calls C/T |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for pair in audit["pairs"]:
        control = pair["control"]["cost"]
        treatment = pair["treatment"]["cost"]
        lines.append(
            f"| {pair['scenario']} | {_number(pair['deltas']['quality_treatment_minus_control'], 12)} | "
            f"{_number(pair['deltas']['objective_treatment_minus_control'], 9)} | "
            f"{_number(control['search_seconds'])} | {_number(treatment['search_seconds'])} | "
            f"{_number(control['total_seconds'])} | {_number(treatment['total_seconds'])} | "
            f"{control['child_evaluations']}/{treatment['child_evaluations']} | "
            f"{control['solver_calls']}/{treatment['solver_calls']} |"
        )
    treatment_cost = asset["cost"]
    lines.extend([
        "",
        (
            "成本包括各自 root public check、全部 proposal/evaluation（含重复提议和 solver）、以及 post-freeze "
            "official runner wall time；solver 不重复相加。资产记录的真实 treatment 均值为 "
            f"search **{_number(treatment_cost['mean_search_seconds_across_3_predeclared_scenarios'])} s**、"
            f"official **{_number(treatment_cost['mean_official_wall_seconds_across_3_predeclared_scenarios'])} s**、"
            f"total **{_number(treatment_cost['mean_total_seconds_across_3_predeclared_scenarios'])} s**，"
            "LLM calls 为 0。direct-full 上限 1 次、single 上限 6 次 child evaluation，预算不等价。"
        ),
        "",
        "## Clean control（不计入修复 gained_true）",
        "",
        "| Arm | Root unchanged | Best not worse than root | Feasible | Quality | True | Objective | Search s | Total s |",
        "|---|---|---|---:|---:|---|---:|---:|---:|",
    ])
    clean = audit["clean_control"]
    for arm_name, arm in (("direct-full", clean["control"]), ("sub-MILP", clean["treatment"])):
        official = arm["official"]
        lines.append(
            f"| {arm_name} | {arm['unchanged']} | {arm['best_not_worse_than_initial']} | "
            f"{official['feasible']} | {_number(official['quality'], 12)} | {official['true_correct']} | "
            f"{_number(official['objective'], 9)} | {_number(arm['cost']['search_seconds'])} | "
            f"{_number(arm['cost']['total_seconds'])} |"
        )
    lines.extend([
        "",
        (
            f"clean control 无回归：**{_yn(scoped['clean_control_preserved'])}**。direct-full 最终保留 root，"
            "sub-MILP 最终制品有变化且 official objective 提升；它与三个预先构造的受损 root 分开报告，"
            "不把 clean 上的目标优化冒充受损修复的 `gained_true`。"
        ),
        "",
        "## SkillRegistry 重放",
        "",
        "| Layer | Pairs | gained_true | Required | lost_true | new_phantom | UNKNOWN | Passed |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ])
    for layer in ("dev", "gapcheck"):
        report = registry["full_replay"]["layers"][layer]
        lines.append(
            f"| {layer} | {report['pairs']} | {report['gained_true']} | {report['required_gained_true']} | "
            f"{report['lost_true']} | {report['new_phantom']} | {report['unknown']} | {report['passed']} |"
        )
    lines.extend([
        "",
        (
            "两臂在三个场景的最终 official `true_correct` 全都已经是 true，因此 dev 为 0/2、"
            "gapcheck 为 0/1 新增真通过；质量和 objective 改善不能替代注册器的 `gained_true`。"
            f"dev 实际生命周期结果为 `{registry['dev']['status']}`，promotion attempted="
            f"**{_yn(registry['promotion_attempted'])}**，selectable assets="
            f"`{registry['selectable_asset_ids']}`。"
        ),
        "",
        "拒绝/阻止原因：",
        "",
    ])
    lines.extend(f"- `{reason}`" for reason in decision["reasons"])
    lines.extend([
        "",
        "## 仅限当前 scope 能支持的结论",
        "",
        (
            f"真实同 root 记录支持当前三场景的 official true/feasible、quality 和 objective 不退化："
            f"**{_yn(scoped['scope_limited_quality_and_objective_evidence'])}**；"
            f"search cost 全场景不退化：**{_yn(scoped['search_cost_not_worse_in_all_scenarios'])}**；"
            f"含官方评价的总成本全场景不退化：**{_yn(scoped['total_cost_not_worse_in_all_scenarios'])}**。"
            "这些结果只适用于当前 problem、三个预声明场景、单个 seed 和本次运行时，不支持跨任务优越性、"
            "普遍成本优势或全局最优。"
        ),
        "",
        scoped["treatment_attribution_note"],
        "",
        "## 后续仍缺证据",
        "",
    ])
    lines.extend(f"{index}. {item}" for index, item in enumerate(decision["missing_evidence"], 1))
    lines.extend([
        "",
        (
            "源 snapshot 标记 `development_only=true`。只有补齐独立 dev/gapcheck 的真实新增真通过、"
            "多种子、预算/成本对照和跨 problem 证据后，才应重新提出新 revision 并重新走完整生命周期；"
            "不得直接改写本次 rejected 记录为 promoted。"
        ),
        "",
    ])
    return "\n".join(lines)


def run(*, source_root: Path = SOURCE_ROOT, out: Path = DEFAULT_OUT, root: Path = ROOT) -> dict[str, Any]:
    source = load_source_audit(source_root, root=root)
    bundle = prepare_candidate(source, source_root=source_root, root=root)
    audit = audit_candidate(bundle)
    audit["repository_head"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render_report(audit), encoding="utf-8")
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(SOURCE_ROOT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    source_root = Path(args.source).resolve()
    out = Path(args.out).resolve()
    audit = run(source_root=source_root, out=out)
    print(json.dumps({
        "out": str(out),
        "asset_id": audit["asset"]["asset_id"],
        "asset_status": audit["decision"]["status"],
        "promoted": audit["decision"]["promoted"],
        "dev_gained_true": audit["registry"]["dev"]["layers"]["dev"]["gained_true"],
        "gapcheck_gained_true": audit["registry"]["full_replay"]["layers"]["gapcheck"]["gained_true"],
        "scope_limited_quality_and_objective_evidence": (
            audit["scoped_findings"]["scope_limited_quality_and_objective_evidence"]),
        "cross_task_evidence": audit["coverage"]["cross_task_evidence"],
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

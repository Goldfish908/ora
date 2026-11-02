#!/usr/bin/env python3
"""Distill convention/prior candidates from feedback trajectories.

Memory layer step 1 (deterministic, zero-LLM-cost): mines historical runs
(round-1 pilot, arm A feedback loop, arm B pre-solve gate loop, arm B'
crash-guard loop) for recurring failure patterns that an a-priori memory
could prevent:

- crash-guard rule hits re-computed on every sandbox gen.py (AST, offline)
- crash exception signatures from stderr_tail in run records
- failure-class stickiness: same failure_type in consecutive rounds of a cell
  (evidence that point feedback is not retained within an episode)

Output: docs/paper/conventions_draft_v0.1.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.guard_check import guard_source  # noqa: E402
from scripts.m1_feedback import failure_type  # noqa: E402
from scripts.m1_pilot import SCHEMA_PRELUDE  # noqa: E402

ARMS = {
    "pilot": (ROOT / "runs/m1_pilot", "m1_pilot_schema_sol*.jsonl"),
    "A": (ROOT / "runs/m1_feedback", "m1_feedback*.jsonl"),
    "B": (ROOT / "runs/m1_presolve", "m1_presolve_v*.jsonl"),
    "Bp": (ROOT / "runs/m1_presolve", "m1_presolve_guard_v*.jsonl"),
}

PRIOR_TEXT = {
    "G0": "Code must parse as Python 3 (no syntax errors).",
    "G1": "PySCIPOpt setObjective: sense must be the string \"minimize\" or "
          "\"maximize\" (never \"min\"/\"max\"); pass sense as a keyword.",
    "G2": "setObjective takes ONE expression, not a Python list; sum terms "
          "with quicksum([...]) first.",
    "G3": "Build comparisons ONLY inside addCons(...); never use <=, >=, == "
          "on expressions in if/assert/bool context (it raises TypeError).",
    "G4": "quicksum is a module-level function (from pyscipopt import "
          "quicksum), not a Model method (m.quicksum does not exist).",
    "G5": "setParam only with real SCIP parameter names (e.g. limits/time, "
          "limits/gap, presolving/maxrounds); never invent parameter names.",
    "G6": "The prelude already loads `data` from data.json; NEVER reassign "
          "it (data = None kills every data[...] access).",
    "G7": "m.infinity is a METHOD: call m.infinity() — passing it uncalled "
          "as ub/lb raises TypeError.",
    "G8": "Read data ONLY from data.json; opening other filenames "
          "(scenario.json, <sid>.json, ...) raises FileNotFoundError.",
}


HOLDOUT: str | None = None  # e.g. "f4": exclude that family from mining


def family_of(sid: str) -> str:
    m = re.match(r"retail_(f\d+)_", sid)
    return m.group(1) if m else "other"


def sandbox_units():
    """Yield (arm, scenario, thinking, round, code) for every sandbox gen.py."""
    for arm, (d, _g) in ARMS.items():
        sb = d / "sandbox"
        if not sb.exists():
            continue
        for sub in sorted(sb.iterdir()):
            gen = sub / "gen.py"
            if not gen.exists():
                continue
            name = sub.name
            if arm == "pilot":
                sid, _, th = name.rpartition("__")
                rnd = 1
            else:
                parts = name.split("__")
                if len(parts) != 4:
                    continue
                sid, th, rnd = parts[1], parts[2], int(parts[3][1:])
            if arm in ("B", "Bp"):
                if not name.startswith("psv"):
                    continue
                if arm == "B" and name.startswith("psv_guard"):
                    continue
                if arm == "Bp" and not name.startswith("psv_guard"):
                    continue
            if HOLDOUT and family_of(sid) == HOLDOUT:
                continue
            try:
                code = gen.read_text()
            except UnicodeDecodeError:
                continue
            yield arm, sid, th, rnd, code


def load_records():
    """Yield (arm, record) for every jsonl record."""
    for arm, (d, g) in ARMS.items():
        for f in sorted(d.glob(g)):
            for line in f.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    if HOLDOUT and family_of(r["scenario_id"]) == HOLDOUT:
                        continue
                    yield arm, r


def crash_sig(stderr: str) -> str | None:
    if not stderr or not stderr.strip():
        return None
    lines = [ln.strip() for ln in stderr.strip().splitlines() if ln.strip()]
    last = lines[-1]
    m = re.match(r"([A-Za-z_.]*(?:Error|Exception|Interrupt|Exit|Fault))\b:?\s*(.*)", last)
    if not m:
        return f"other: {last[:50]}"
    msg = re.sub(r"\d+", "N", m.group(2))[:55]
    ctx = ""
    for ln in lines:
        if "pyscipopt" in ln and "src/" in ln:
            ctx = " [pyscipopt:" + ln.split(",")[0].split(".")[-1].strip() + "]"
            break
    return f"{m.group(1)}: {msg}{ctx}"


def main() -> None:
    global HOLDOUT
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--holdout", metavar="FAMILY",
                    help="exclude one scenario family (e.g. f4) from mining; "
                         "rules distilled without it stay leak-free for "
                         "held-out evaluation on that family")
    args = ap.parse_args()
    HOLDOUT = args.holdout

    units = list(sandbox_units())
    recs = list(load_records())

    # ---- guard rule re-play on all sandbox code ----
    rule_by_arm = defaultdict(Counter)          # arm -> rule -> hits
    cell_rules = defaultdict(list)              # (arm,sid,th) -> [(rnd, rules)]
    rule_examples = {}
    for arm, sid, th, rnd, code in units:
        hits = guard_source(SCHEMA_PRELUDE + code)
        rules = sorted({h["rule"] for h in hits})
        for rl in rules:
            rule_by_arm[arm][rl] += 1
            rule_examples.setdefault(rl, f"{sid} ({arm} r{rnd})")
        cell_rules[(arm, sid, th)].append((rnd, rules))
    # within-cell repetition: same rule in two consecutive rounds
    rule_repeat = Counter()
    cells_with_repeat = 0
    for key, seq in cell_rules.items():
        seq.sort()
        rep = set()
        for (r0, rs0), (r1, rs1) in zip(seq, seq[1:]):
            if r1 == r0 + 1:
                rep |= set(rs0) & set(rs1)
        if rep:
            cells_with_repeat += 1
            for rl in rep:
                rule_repeat[rl] += 1

    # ---- crash signatures from records ----
    sig_by_arm = defaultdict(Counter)
    sig_examples = {}
    # ---- failure-class stickiness ----
    by_cell = defaultdict(list)
    for arm, r in recs:
        by_cell[(arm, r["scenario_id"], r["thinking"])].append(r)
        if r.get("exec_status") != "ok":
            sig = crash_sig(r.get("stderr_tail") or "")
            if sig:
                sig_by_arm[arm][sig] += 1
                sig_examples.setdefault(
                    sig, f"{r['scenario_id']} ({arm} r{r.get('round', 1)})")
    sticky = Counter()
    transitions = Counter()
    for key, rs in by_cell.items():
        rs.sort(key=lambda r: r.get("round", 1))
        fts = [failure_type(r) for r in rs]
        for f0, f1 in zip(fts, fts[1:]):
            if f0 is not None and f1 is not None:
                transitions[f0] += 1
                if f0 == f1:
                    sticky[f0] += 1

    # ---- emit markdown ----
    L = ["# 约定/修复模式自动蒸馏草案 v0.1", ""]
    if HOLDOUT:
        L.append(f"**本次挖掘已留出 `{HOLDOUT}` 族（--holdout）：所有统计均不含"
                 "该族轨迹，蒸馏出的规则可安全用于该族的 held-out 评测。**")
        L.append("")
    L.append("方法：对全部历史轨迹（round-1 pilot、A 反馈环、B 预求解闸门、"
             "B' crash guard）做零 LLM 成本的确定性挖掘——guard AST 规则在"
             "每份 sandbox gen.py 上重放、stderr 崩溃签名聚类、失败类逐轮"
             "粘连率（同一 cell 相邻两轮同失败类 = 点反馈未被吸收）。")
    L.append("")
    L.append("> 注意：历史 B/B' 臂的 sandbox 目录共用 psv__ 前缀（B' 覆盖同名 "
             "B 臂 gen.py；已于 m1_presolve_loop 修复，新臂命名含 out-tag）。"
             "§1 的 B 列因此混入少量 B' 早期代码（偏低估计 B 的违规数）;"
             "§2/§3 基于 jsonl 记录，不受影响。")
    L.append("")
    L.append("> 防泄题协议：蒸馏来源目前是 RetailOpt-190 自身轨迹。当前产物"
             "（G1–G8）全部是 PySCIPOpt API 用法与 harness 环境约定，不含题目"
             "语义/答案，属工具知识；但规则集是集内失败分布驱动选出的，严格"
             "意义上是 dev-set fitting。协议：① memory 蒸馏只用 dev 部分"
             "（--holdout 留出整族），冻结后只在 held-out 上主表评测；"
             "② 语义层约定（场景建模知识）必须走该协议，reference 目标值"
             "永不进 memory;③ 跨数据集迁移（RetailOpt 蒸馏 → IndustryOR/"
             "NL4Opt 评测）作为更强的泛化 claim。")
    L.append("")

    L.append("## 1. guard 规则在全部历史代码上的重放命中")
    L.append("")
    L.append("| rule | pilot | A | B | B' | 合计 | 跨轮重复 cell 数 | 例 |")
    L.append("|---|---|---|---|---|---|---|---|")
    all_rules = sorted({rl for c in rule_by_arm.values() for rl in c})
    for rl in all_rules:
        row = [f"| {rl}"] + [str(rule_by_arm[a][rl]) for a in ("pilot", "A", "B", "Bp")]
        tot = sum(rule_by_arm[a][rl] for a in ARMS)
        row += [str(tot), str(rule_repeat[rl]), rule_examples.get(rl, "")]
        L.append(" | ".join(row) + " |")
    L.append("")
    L.append(f"跨轮重复（同一 cell 相邻两轮命中同一规则）的 cell 共 "
             f"{cells_with_repeat} 个——模型在同一回合内收到反馈仍复发，"
             "说明需要**事前**先验而非仅靠事后反馈。")
    L.append("")

    L.append("## 2. crash 异常签名（stderr 末行聚类，top 15）")
    L.append("")
    L.append("| signature | pilot | A | B | B' | 合计 | 例 |")
    L.append("|---|---|---|---|---|---|---|")
    sig_tot = Counter()
    for a, c in sig_by_arm.items():
        sig_tot.update(c)
    for sig, _ in sig_tot.most_common(15):
        row = [f"| `{sig}`"] + [str(sig_by_arm[a][sig]) for a in ("pilot", "A", "B", "Bp")]
        row += [str(sig_tot[sig]), sig_examples.get(sig, "")]
        L.append(" | ".join(row) + " |")
    L.append("")

    L.append("## 3. 失败类粘连率（相邻两轮同失败类）")
    L.append("")
    L.append("| failure class | 转移总数 | 粘连次数 | 粘连率 |")
    L.append("|---|---|---|---|")
    for ft, tot in transitions.most_common():
        st = sticky[ft]
        L.append(f"| {ft} | {tot} | {st} | {st/tot:.0%} |")
    L.append("")

    L.append("## 4. 候选事前约定（按历史命中量排序）")
    L.append("")
    L.append("以下文本可注入生成 prompt 作为 memory/先验；括号内为历史命中证据。")
    L.append("")
    for rl in all_rules:
        tot = sum(rule_by_arm[a][rl] for a in ARMS)
        if tot == 0:
            continue
        L.append(f"- **[{rl}]** {PRIOR_TEXT.get(rl, '')} "
                 f"(命中 {tot} 份代码，跨轮重复 {rule_repeat[rl]} cell)")
    L.append("")
    g2_gap = sig_tot.get(
        "AssertionError: given coefficients are neither Expr or number but "
        "list [pyscipopt:pyx\"]", 0)
    L.append("crash 签名中未被 guard 规则覆盖的高频项，是 guard 规则扩充的"
             "候选：")
    L.append("")
    L.append(f"- `AssertionError: ... neither Expr or number but list` 共 "
             f"{g2_gap} 次，但 G2 重放命中 {sum(rule_by_arm[a]['G2'] for a in ARMS)}"
             " ——G2 只覆盖**字面量** list 参数，经变量间接传入（`obj=[...]; "
             "setObjective(obj)`）漏检。候选扩充：简单数据流（Name=List 赋值"
             "流入 setObjective 调用）。")
    nl = sig_tot.get("NotImplementedError:  [pyscipopt:pxi\"]", 0)
    L.append(f"- `NotImplementedError`（pyscipopt）共 {nl} 次：多为表达式比较/"
             "链式比较的运行时形态，与 G3 同源但 AST 形态不同，候选扩充 G3 "
             "覆盖更多上下文。")
    L.append("")

    out = "\n".join(L) + "\n"
    p = ROOT / "docs/paper/conventions_draft_v0.1.md"
    p.write_text(out)
    print(out)


if __name__ == "__main__":
    main()

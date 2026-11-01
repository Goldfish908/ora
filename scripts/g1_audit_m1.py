#!/usr/bin/env python3
"""R2-G1 eco-validity arm: audit the 27B's OWN real M1 outputs.

The synthetic-mutant G1 (g1_audit.py) is the lower bound: single-point,
template-consistent errors. This script audits real model failures from
the M1 schema_sol pilot (phantom initial inventory etc., ground truth from
the f1 witness) plus the validated reference solutions as PASS controls.
Solutions are 700-2700 entries — too large to eyeball, so only the tool
arm makes sense: the auditor sees problem + code, and must write a Python
checker (runs with data.json + solution.json in cwd), then verdicts.

Usage (from /home/hewj13/wm/ora):
    source ~/.leagent_env
    python3 scripts/g1_audit_m1.py --workers 4

Results: runs/g1_audit/g1_audit_m1.jsonl (resume-safe).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from scripts.m1_pilot import adapt_prompt_schema, SCIP_OUTPUT_FORMAT  # noqa

DATA = ROOT / "data" / "m1_retailopt" / "retailopt_190.jsonl"
M1_JSONL = ROOT / "runs" / "m1_pilot" / "m1_pilot_schema_sol.jsonl"
REF_DIR = ROOT / "runs" / "m1_witness_ref"
OUT_DIR = ROOT / "runs" / "g1_audit"
EXEC_PYTHON = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"
EXEC_TIMEOUT_SEC = 120

VERDICT_RE = re.compile(r"\*{0,2}VERDICT\*{0,2}\s*[:：]\s*\*{0,2}(PASS|FAIL)",
                        re.IGNORECASE)

TASK = """
你是审计员。给定一个优化问题的题面、建模代码 gen.py;它写出的
solution.json 在检查脚本的运行目录下(太大,不要指望肉眼核对)。
判断这个解是否**严格满足题面的每一条业务规则**,且报告的 objective
是否与解的真实成本一致。注意:错误可能是整块约束缺失、凭空引入题面
没有的资源(如期初库存)、下标/符号错误、求和轴错误,而不仅仅是某行写错。

先输出一段 Python 检查脚本(运行目录下有 data.json 与 solution.json,
打印核对结果;只输出脚本)。我会执行并把输出给你,然后你下结论:
最后一行必须是 `VERDICT: PASS` 或 `VERDICT: FAIL <一句话理由>`。
"""


def extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    return stripped.strip()


def collect_items() -> list[dict]:
    rows = {r["scenario_id"]: r for r in
            (json.loads(l) for l in DATA.read_text().splitlines()
             if l.strip())}
    pilot = [json.loads(l) for l in M1_JSONL.read_text().splitlines()
             if l.strip()]
    items = []
    for p in pilot:
        if p.get("witness") != "infeasible":
            continue
        sid = p["scenario_id"]
        sandbox = (ROOT / "runs" / "m1_pilot" / "sandbox"
                   / f"schema_sol__{sid}__{p['thinking']}")
        items.append({
            "id": f"model__{sid}__{p['thinking']}",
            "sid": sid,
            "code": (sandbox / "gen.py").read_text(),
            "solution": (sandbox / "solution.json").read_text(),
            "expected": "FAIL",
            "truth_rules": p.get("witness_rules", []),
        })
    for sid in ("retail_f1_base_v0", "retail_f1_52_weeks_v0",
                "retail_f1_high_waste_v0", "retail_f1_jit_logic_v0"):
        items.append({
            "id": f"ref__{sid}",
            "sid": sid,
            "code": (ROOT / "scripts" / "m1_f1_reference.py").read_text(),
            "solution": (REF_DIR / f"{sid}.solution.json").read_text(),
            "expected": "PASS",
            "truth_rules": [],
        })
    for it in items:
        it["problem"] = adapt_prompt_schema(rows[it["sid"]]["prompt_schema"])
        it["data"] = rows[it["sid"]]["data"]
    return items


def run_checker(code: str, sandbox: Path) -> str:
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "check.py").write_text(code, encoding="utf-8")
    try:
        p = subprocess.run([EXEC_PYTHON, "check.py"], cwd=sandbox,
                           capture_output=True, text=True,
                           timeout=EXEC_TIMEOUT_SEC)
        out = (p.stdout + ("\n[stderr]\n" + p.stderr if p.stderr else ""))
        return out[-3000:]
    except subprocess.TimeoutExpired:
        return "[timeout]"


def one_job(item: dict, mode: str, cfg) -> dict:
    rec = {"id": item["id"], "sid": item["sid"], "expected": item["expected"],
           "thinking": mode,
           "truth_rules": item["truth_rules"]}
    extra = ({"chat_template_kwargs": {"enable_thinking": False}}
             if mode == "off" else {"reasoning_effort": "medium"})
    max_tokens = 16384 if mode == "off" else 32768
    materials = (f"## 题面\n{item['problem']}\n\n## gen.py\n"
                 f"```python\n{item['code']}\n```\n")
    t0 = time.time()
    try:
        msgs = [{"role": "user", "content": materials + TASK}]
        r1 = llm_mod.chat(msgs, max_tokens=max_tokens, temperature=0.6,
                          extra=extra, config=cfg)
        t1 = (r1.get("content") or "")
        sandbox = (OUT_DIR / "sandbox_m1"
                   / f"{item['id']}__{mode}")
        shutil.rmtree(sandbox, ignore_errors=True)
        sandbox.mkdir(parents=True, exist_ok=True)
        (sandbox / "data.json").write_text(item["data"])
        (sandbox / "solution.json").write_text(item["solution"])
        tool_out = run_checker(extract_code(t1), sandbox)
        msgs += [{"role": "assistant", "content": t1},
                 {"role": "user", "content":
                  "检查脚本输出如下:\n```\n" + tool_out +
                  "\n```\n请给出最终结论(最后一行 VERDICT: ...)。"}]
        r2 = llm_mod.chat(msgs, max_tokens=max_tokens, temperature=0.6,
                          extra=extra, config=cfg)
        t2 = r2.get("content") or ""
        m = VERDICT_RE.search(t2.strip().splitlines()[-1]
                              if t2.strip() else "") \
            or VERDICT_RE.search(t2)
        rec.update(exec_status="ok",
                   verdict=m.group(1).upper() if m else None,
                   verdict_src_tail=t2[-300:],
                   tool_output_tail=tool_out[-300:],
                   latency_s=round(time.time() - t0, 1))
    except Exception as e:
        rec.update(exec_status="llm_error",
                   error=f"{type(e).__name__}: {e}",
                   latency_s=round(time.time() - t0, 1))
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", nargs="*", default=["on", "off"],
                    choices=["on", "off"])
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    items = collect_items()
    print(f"{len(items)} audit items "
          f"({sum(1 for i in items if i['expected'] == 'FAIL')} real model "
          f"failures, {sum(1 for i in items if i['expected'] == 'PASS')} "
          f"references)")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "g1_audit_m1.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["id"], r["thinking"]))
    jobs = [(it, m) for it in items for m in args.modes
            if (it["id"], m) not in done]
    print(f"{len(jobs)} jobs ({len(done)} done)")

    cfg = llm_mod.load_config()
    lock = threading.Lock()
    fp = out_path.open("a", encoding="utf-8")
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(one_job, it, m, cfg): (it["id"], m)
                for it, m in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            rec = fut.result()
            with lock:
                fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fp.flush()
            print(f"[{i}/{len(jobs)}] {rec['id']} {rec['thinking']}: "
                  f"verdict={rec.get('verdict')} expect={rec['expected']} "
                  f"({time.time() - t_start:.0f}s elapsed)")
    fp.close()


if __name__ == "__main__":
    main()

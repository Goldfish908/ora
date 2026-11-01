#!/usr/bin/env python3
"""R2-G1 pilot: can an audit agent detect injected connection errors?

Gate G1 of the research prereg. Each m2gen instance ships correct + mutant
artifacts with ground-truth labels (expected_witness). The auditor (27B)
gets problem.md + solve.py + solution.json and must verdict PASS/FAIL.

Arms:
  static — read-only judgment, one LLM call;
  tool   — stage 1: auditor writes a Python checker (reads params.json and
           solution.json from cwd); harness runs it; stage 2: auditor sees
           the checker output and gives the final verdict. Two LLM calls.

Detection = mutant judged FAIL; false alarm = correct judged FAIL.

Usage (from /home/hewj13/wm/ora):
    source ~/.leagent_env
    python3 scripts/g1_audit.py --structures dist_plan dist_setup

Results: runs/g1_audit/g1_audit.jsonl, one row per
(instance x artifact x thinking x arm). Resume-safe.
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

GEN_DIR = ROOT / "controlled_m2" / "gen"
OUT_DIR = ROOT / "runs" / "g1_audit"
EXEC_PYTHON = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"
EXEC_TIMEOUT_SEC = 60

VERDICT_RE = re.compile(r"\*{0,2}VERDICT\*{0,2}\s*[:：]\s*\*{0,2}(PASS|FAIL)",
                        re.IGNORECASE)

TASK_COMMON = """
你是审计员。给定一个优化问题的题面、建模代码 solve.py 和它写出的解
solution.json,判断这个解是否**严格满足题面的每一条业务规则**,且报告的
objective 是否与解的真实成本一致。不要假设代码是对的:逐条核对题面规则
(注意期初库存、到货时滞、聚合 vs 逐条上限、启用激活、费用映射方向等)。

最后一行必须输出 `VERDICT: PASS` 或 `VERDICT: FAIL <一句话理由>`。
"""

TOOL_STAGE1 = """
你可以先写一段 Python 检查脚本来核对。脚本运行目录下**直接**有
params.json 和 solution.json(不在子目录,用 open("params.json")
和 open("solution.json") 读取,不要写任何路径搜索逻辑)。只输出脚本,
我会执行并把输出给你,下一轮再下结论。
"""

TOOL_STAGE2 = """检查脚本输出如下:
```
%s
```
不要再写代码。基于输出直接给最终结论,最后一行必须是
VERDICT: PASS 或 VERDICT: FAIL <一句话理由>。"""


def extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    return stripped.strip()


def chat(prompt: str, mode: str, cfg, history: list | None = None) -> dict:
    extra = ({"chat_template_kwargs": {"enable_thinking": False}}
             if mode == "off" else {"reasoning_effort": "medium"})
    max_tokens = 16384 if mode == "off" else 32768
    msgs = (history or []) + [{"role": "user", "content": prompt}]
    t0 = time.time()
    resp = llm_mod.chat(msgs, max_tokens=max_tokens, temperature=0.6,
                        extra=extra, config=cfg)
    return {"text": resp.get("content") or "",
            "latency_s": round(time.time() - t0, 1),
            "finish_reason": resp.get("finish_reason"),
            "_msgs": msgs}


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


def one_job(inst: Path, aid: str, expect: str, mode: str, arm: str,
            cfg) -> dict:
    problem = (inst / "problem.md").read_text()
    art = inst / ("correct" if aid == "correct" else f"mutants/{aid}")
    code = (art / "solve.py").read_text()
    sol_text = (art / "solution.json").read_text()
    materials = (f"## 题面\n{problem}\n\n## solve.py\n```python\n{code}\n```"
                 f"\n\n## solution.json\n```json\n{sol_text}\n```\n")
    rec = {"instance": inst.name, "artifact": aid, "expected": expect,
           "thinking": mode, "arm": arm}
    t0 = time.time()
    try:
        if arm == "static":
            r1 = chat(materials + TASK_COMMON, mode, cfg)
            verdict_src = r1["text"]
            rec["latency_s"] = r1["latency_s"]
        else:
            r1 = chat(materials + TASK_COMMON + TOOL_STAGE1, mode, cfg)
            sandbox = (OUT_DIR / "sandbox"
                       / f"{inst.name}__{aid}__{mode}__{arm}")
            sandbox.mkdir(parents=True, exist_ok=True)
            shutil.copy(inst / "data" / "params.json",
                        sandbox / "params.json")
            shutil.copy(art / "solution.json", sandbox / "solution.json")
            tool_out = run_checker(extract_code(r1["text"]), sandbox)
            # what the auditor's own checker concluded (analysis aid when
            # the stage-2 verdict cannot be parsed)
            pm = re.findall(r"\b(PASS|FAIL)\b", tool_out)
            rec["checker_printed"] = pm[-1] if pm else None
            r2 = chat(TOOL_STAGE2 % tool_out,
                      mode, cfg,
                      history=r1["_msgs"] + [
                          {"role": "assistant", "content": r1["text"]}])
            verdict_src = r2["text"]
            rec["latency_s"] = round(time.time() - t0, 1)
            rec["tool_output_tail"] = tool_out[-300:]
        m = VERDICT_RE.search(verdict_src.strip().splitlines()[-1] if
                              verdict_src.strip() else "")
        if not m:  # tolerate verdict not on the literal last line
            m = VERDICT_RE.search(verdict_src or "")
        rec["verdict"] = m.group(1).upper() if m else None
        rec["verdict_src_tail"] = (verdict_src or "")[-300:]
        rec["verdict_correct"] = (rec["verdict"] == expect) \
            if rec["verdict"] else None
        rec["exec_status"] = "ok"
    except Exception as e:
        rec.update(exec_status="llm_error",
                   error=f"{type(e).__name__}: {e}",
                   latency_s=round(time.time() - t0, 1))
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--structures", nargs="*",
                    default=["dist_plan", "dist_setup"])
    ap.add_argument("--modes", nargs="*", default=["on", "off"],
                    choices=["on", "off"])
    ap.add_argument("--arms", nargs="*", default=["static", "tool"],
                    choices=["static", "tool"])
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    instances = sorted(p for p in GEN_DIR.iterdir()
                       if (p / "labels.json").exists() and
                       json.loads((p / "labels.json").read_text())
                       ["structure"] in args.structures)
    jobs = []
    for inst in instances:
        labels = json.loads((inst / "labels.json").read_text())
        for aid, meta in labels["artifacts"].items():
            for mode in args.modes:
                for arm in args.arms:
                    jobs.append((inst, aid, meta["expected_witness"],
                                 mode, arm))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "g1_audit.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["instance"], r["artifact"], r["thinking"],
                          r["arm"]))
    jobs = [j for j in jobs
            if (j[0].name, j[1], j[3], j[4]) not in done]
    print(f"{len(jobs)} audit jobs ({len(done)} done)")

    cfg = llm_mod.load_config()
    lock = threading.Lock()
    fp = out_path.open("a", encoding="utf-8")
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(one_job, *j, cfg): j for j in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            rec = fut.result()
            with lock:
                fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fp.flush()
            print(f"[{i}/{len(jobs)}] {rec['instance']} {rec['artifact']} "
                  f"{rec['thinking']} {rec['arm']}: "
                  f"verdict={rec.get('verdict')} "
                  f"expect={rec['expected']} "
                  f"({'%.0f' % rec.get('latency_s', 0)}s, "
                  f"{time.time() - t_start:.0f}s elapsed)")
    fp.close()


if __name__ == "__main__":
    main()

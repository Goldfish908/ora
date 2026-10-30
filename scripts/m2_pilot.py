#!/usr/bin/env python3
"""M2 pilot: natural generation on the controlled-M2 set (evidence group 2).

For each instance in controlled_m2/gen (plus flip variants), sample the
internal Qwen3_8-27B n times per thinking mode, execute the generated
PySCIPOpt code, and grade it with the instance's own witness (programmatic
attribution — no LLM labeling, m2_design §6).

M1 pilot lessons applied (e_stage_report §4.6):
  - data is given as a FILE (data/params.json copied into the sandbox), so
    transcription errors cannot occur — the prompt explicitly forbids them;
  - a short PySCIPOpt idiom cheatsheet is appended to suppress API-noise
    failures (quicksum list errors etc.).

Usage (from /home/hewj13/wm/ora):
    source ~/.leagent_env
    python3 scripts/m2_pilot.py --samples 4 --workers 4

Results: runs/m2_pilot/m2_pilot.jsonl, one row per
(instance x variant x thinking x sample). Resume-safe (dedup on that key).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402

GEN_DIR = ROOT / "controlled_m2" / "gen"
OUT_DIR = ROOT / "runs" / "m2_pilot"
EXEC_PYTHON = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"
EXEC_TIMEOUT_SEC = 180
OBJ_TOL = 1e-6

CHEATSHEET = """
## 实现提示(PySCIPOpt 惯用法,务必遵守)

- `from pyscipopt import Model`;`m = Model()`;`m.hideOutput()`
- 约束:`m.addCons(线性表达式 <= 常数)`;求和用 Python `sum(...)`,
  系数必须是数字或变量表达式,**不要把 list 当作系数传入**
- 变量:`m.addVar(name=..., vtype="I")` 整数,`vtype="B"` 0/1,`vtype="C"` 连续
- `m.setObjective(表达式)` 默认就是最小化;**不要传 sense 参数**("min" 不是合法值,最大化才写 `sense="maximize"`)
- `m.optimize()` 后用 `m.getVal(变量)` 取值,`m.getObjVal()` 取目标值
- **下标纪律**:数据列表一律 0 起始,题面的第 t 期(1..T)对应数组下标 `[t-1]`。若循环用 `range(1, T+1)`,访问数据数组必须写 `[t-1]`;状态变量(库存等)的下标方案要与之一致,t==1(或 t==0)的边界单独处理。生成后请心算一遍第一期和最后一期是否越界
- gurobipy 惯用法不可用:`quicksum` 用 Python `sum` 代替;没有 `m.getObjective().terms`、`gp.and_`、`addVars` 批量接口(用字典推导逐个 `addVar`)
- 数据文件 `data/params.json` 已在当前工作目录,**必须用代码读取**:
  `json.loads(open("data/params.json").read())`
  **禁止把数据誊抄进代码**(禁止手写数据数组)。
- 只输出可执行的 Python 脚本本体,不要解释。
"""


def extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    return stripped.strip()


def run_and_grade(inst_dir: Path, variant: str, code: str,
                  sandbox: Path) -> dict:
    """Lay out a fake artifact dir (correct/ = model code), copy the
    instance's witness and data, run the witness, parse the verdict."""
    root = sandbox
    if root.exists():
        shutil.rmtree(root)
    (root / "correct").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "witness").mkdir()
    (root / "correct" / "solve.py").write_text(code, encoding="utf-8")
    src_data = (inst_dir / "data" / "params.json") if variant == "base" \
        else (inst_dir / variant / "data" / "params.json")
    shutil.copy(src_data, root / "data" / "params.json")
    # the witness runs solve.py with cwd=correct/; model code reads
    # "data/params.json" relative to its cwd, so mirror the data there
    (root / "correct" / "data").mkdir()
    shutil.copy(src_data, root / "correct" / "data" / "params.json")
    shutil.copy(inst_dir / "witness" / "correct.py",
                root / "witness" / "correct.py")
    t0 = time.time()
    try:
        r = subprocess.run([EXEC_PYTHON, str(root / "witness" / "correct.py")],
                           cwd=root, capture_output=True, text=True,
                           timeout=EXEC_TIMEOUT_SEC)
        out = (r.stdout or "").strip()
        tail = (r.stderr or "")[-300:]
        rc = r.returncode
    except subprocess.TimeoutExpired:
        return {"exec_status": "timeout", "wall_s": time.time() - t0}
    res = {
        "exec_status": "ok" if rc == 0 else "fail",
        "model_code_crash": out.startswith("FAIL:crash"),
        "wall_s": round(time.time() - t0, 1),
        "witness_pass": out.startswith("PASS"),
        "rules": re.findall(r"(W\d+)", out.split(":", 1)[-1])
        if rc != 0 else [],
        "stderr_tail": "" if rc == 0 else tail,
    }
    m = re.search(r"objective=([-\d.eE]+)", out)
    if m:
        res["objective"] = float(m.group(1))
    else:
        sol = root / "correct" / "solution.json"
        if sol.exists():
            res["objective"] = json.loads(sol.read_text()).get("objective")
    return res


def one_job(inst_dir: Path, variant: str, mode: str, sample_idx: int,
            cfg) -> dict:
    labels = json.loads((inst_dir / "labels.json").read_text())
    if variant == "base":
        problem = (inst_dir / "problem.md").read_text()
    else:
        problem = (inst_dir / variant / "problem.md").read_text()
    prompt = problem + CHEATSHEET
    extra = ({"chat_template_kwargs": {"enable_thinking": False}}
             if mode == "off" else {"reasoning_effort": "medium"})
    max_tokens = 16384 if mode == "off" else 32768
    key = f"{inst_dir.name}|{variant}|{mode}|{sample_idx}"
    rec = {"instance": inst_dir.name, "structure": labels["structure"],
           "variant": variant, "thinking": mode, "sample": sample_idx,
           "reference_objective": labels["reference_objective"]}
    t0 = time.time()
    try:
        resp = llm_mod.chat([{"role": "user", "content": prompt}],
                            max_tokens=max_tokens, temperature=0.6,
                            extra=extra, config=cfg)
        text = resp.get("content") or ""
        u = resp.get("usage") or {}
        rec["reasoning_tokens"] = (
            (u.get("completion_tokens_details") or {}).get("reasoning_tokens"))
        rec["completion_tokens"] = u.get("completion_tokens")
        rec["finish_reason"] = resp.get("finish_reason")
    except Exception as e:
        rec.update(exec_status="llm_error",
                   error=f"{type(e).__name__}: {e}",
                   llm_latency_s=round(time.time() - t0, 1))
        return rec
    rec["llm_latency_s"] = round(time.time() - t0, 1)
    rec["code_chars"] = len(text)
    sandbox = OUT_DIR / "sandbox" / key.replace("|", "__")
    rec.update(run_and_grade(inst_dir, variant, extract_code(text), sandbox))
    obj, ref = rec.get("objective"), labels["reference_objective"]
    if variant == "base" and ref is not None and rec.get("objective") is not None:
        rec["obj_match_reference"] = abs(rec["objective"] - ref) <= OBJ_TOL
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--modes", nargs="*", default=["on", "off"],
                    choices=["on", "off"])
    ap.add_argument("--limit-instances", type=int, default=0)
    args = ap.parse_args()

    instances = sorted(p for p in GEN_DIR.iterdir()
                       if (p / "labels.json").exists())
    if args.limit_instances:
        instances = instances[: args.limit_instances]
    jobs = []
    for inst in instances:
        variants = ["base"] + sorted(
            p.name for p in inst.iterdir()
            if p.is_dir() and p.name.startswith("flip_"))
        for variant in variants:
            for mode in args.modes:
                for s in range(args.samples):
                    jobs.append((inst, variant, mode, s))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "m2_pilot.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["instance"], r["variant"], r["thinking"],
                          r["sample"]))
    jobs = [j for j in jobs
            if (j[0].name, j[1], j[2], j[3]) not in done]
    print(f"{len(jobs)} jobs to run ({len(done)} already done)")

    cfg = llm_mod.load_config()
    lock = threading.Lock()
    fp = out_path.open("a", encoding="utf-8")
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(one_job, inst, variant, mode, s, cfg):
                (inst.name, variant, mode, s)
                for inst, variant, mode, s in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            rec = fut.result()
            with lock:
                fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fp.flush()
            print(f"[{i}/{len(jobs)}] {rec['instance']} {rec['variant']} "
                  f"{rec['thinking']} s{rec['sample']}: "
                  f"{rec.get('exec_status')} witness={rec.get('witness_pass')} "
                  f"rules={rec.get('rules')} "
                  f"({time.time() - t_start:.0f}s elapsed)")
    fp.close()


if __name__ == "__main__":
    main()

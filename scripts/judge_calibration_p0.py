"""P0 judge calibration: local LLM as a stand-in for a System-One-style judge (JEV).

Design doc: docs/paper/jev_integration_exploration_v0.1.md (§6 校准协议).

Idea: JEV (TypeSafe System One) answers typed questions over a state:
Noul (yes/no + probability), Choice (option set), Score (rubric). We cannot
call JEV yet (early-access key pending), so we replay the SAME question shapes
with intranet Qwen3.8-27B as judge, on cells whose semantic ground truth is
already known via the deterministic witness checker (the calibration oracle).

Outputs a confusion matrix vs witness, with a dedicated phantom subset
(grade looks fine but witness=infeasible) — the adversarial core of our
setting: phantoms are built to look plausible.

Usage:
  # 1) dry-run: load cells, report counts, NO LLM calls
  python scripts/judge_calibration_p0.py --dry-run
  # 2) smoke: 3 cells (needs LLM env)
  source ~/.leagent_env && export ORA_LLM_BASE_URL=$QWEN27B_BASE_URL \
      ORA_LLM_API_KEY=$QWEN27B_API_KEY ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
  python scripts/judge_calibration_p0.py --limit 3
  # 3) full
  python scripts/judge_calibration_p0.py --out runs/judge_calib_p0/judge_p0.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LEDGER_GLOB = "m1_feedback_v*.jsonl"
SANDBOX = ROOT / "runs" / "m1_feedback" / "sandbox"
SCENARIOS = ROOT / "data" / "m1_retailopt" / "retailopt_190.jsonl"

NOUL_PROMPT = """You are a strict semantics auditor for operations-research modeling.

Below is (1) an optimization problem statement, (2) modeling code written by an
AI agent, and (3) a summary of the solution the solver returned for that model.

Your ONLY job: decide whether the returned solution violates the problem's
stated or clearly implied semantics (e.g. inventory appearing from nowhere,
demand balance broken, capacity exceeded, lead time ignored, min-order violated).

You do NOT re-solve the problem. You judge semantic consistency between the
statement and the returned solution.

[PROBLEM]
{prompt}

[MODEL CODE] (truncated to first 4000 chars)
{code}

[RETURNED SOLUTION SUMMARY]
objective = {objective}
first decision entries = {sol_head}

Answer in EXACTLY this format (two lines, nothing else):
VIOLATION: YES or NO
CONFIDENCE: a number in [0,1]
"""


def load_cells() -> list[dict]:
    """Latest-version ledger rows with a definitive witness label + sandbox dir."""
    cells: dict[tuple, dict] = {}
    for f in sorted((ROOT / "runs" / "m1_feedback").glob(LEDGER_GLOB)):
        ver = int(re.search(r"_v(\d+)", f.name).group(1))
        for line in f.open():
            r = json.loads(line)
            if r.get("witness") not in ("feasible", "infeasible"):
                continue
            key = (r["scenario_id"], r.get("thinking"), r.get("round"))
            if key not in cells or ver > cells[key][0]:
                cells[key] = (ver, r)
    out = []
    for (sid, thinking, rnd), (_, r) in sorted(cells.items()):
        sb = SANDBOX / f"fb__{sid}__{'on' if thinking else 'off'}__r{rnd}"
        if (sb / "gen.py").exists() and (sb / "solution.json").exists():
            r["_sandbox"] = sb
            out.append(r)
    return out


def load_prompts() -> dict[str, str]:
    prompts = {}
    with SCENARIOS.open() as f:
        for line in f:
            r = json.loads(line)
            prompts[r["scenario_id"]] = r["prompt_schema"]
    return prompts


def sol_head(sol: dict, n: int = 12) -> str:
    items = []
    for key in ("Q", "I", "S", "W", "X", "Y", "Z"):
        tbl = sol.get(key)
        if isinstance(tbl, dict):
            for k, v in list(tbl.items())[: max(1, n // max(1, len(items) + 1))]:
                items.append(f"{key}[{k}]={v}")
        if len(items) >= n:
            break
    return "; ".join(items[:n])


def parse_noul(text: str) -> tuple[str | None, float | None]:
    m1 = re.search(r"VIOLATION:\s*(YES|NO)", text, re.I)
    m2 = re.search(r"CONFIDENCE:\s*([01](?:\.\d+)?)", text)
    return (m1.group(1).upper() if m1 else None,
            float(m2.group(1)) if m2 else None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="no LLM calls")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(ROOT / "runs" / "judge_calib_p0" / "judge_p0.jsonl"))
    args = ap.parse_args()

    cells = load_cells()
    prompts = load_prompts()
    ph = [c for c in cells if c["witness"] == "infeasible"
          and c.get("grade") in ("match", "better_than_reference")]
    ts = [c for c in cells if c["witness"] == "feasible" and c.get("grade") == "match"]
    print(f"cells with witness label + sandbox: {len(cells)}")
    print(f"  phantom subset (looks-fine but infeasible): {len(ph)}")
    print(f"  true-success subset (feasible & match):   {len(ts)}")
    fam: dict[str, int] = {}
    for c in cells:
        m = re.match(r"retail_(f\d+)", c["scenario_id"])
        fam[m.group(1) if m else "?"] = fam.get(m.group(1) if m else "?", 0) + 1
    print("  by family:", dict(sorted(fam.items())))
    if args.dry_run:
        print("dry-run: no LLM calls. Use --limit 3 for a smoke test.")
        return

    from ora_agent import llm as llm_mod  # noqa: E402

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.exists():
        done = {json.loads(l)["_key"] for l in out_path.open()}
    n_call = 0
    with out_path.open("a") as out:
        for c in cells:
            if args.limit and n_call >= args.limit:
                break
            key = (c["scenario_id"], c.get("thinking"), c.get("round"))
            if str(key) in done:
                continue
            code = c["_sandbox"].joinpath("gen.py").read_text()[:4000]
            sol = json.loads(c["_sandbox"].joinpath("solution.json").read_text())
            msg = NOUL_PROMPT.format(
                prompt=prompts[c["scenario_id"]][:6000], code=code,
                objective=c.get("objective"), sol_head=sol_head(sol))
            try:
                resp = llm_mod.chat(
                    [{"role": "user", "content": msg}],
                    max_tokens=64, temperature=0.0,
                    # judge mimics JEV's fast non-reasoning form factor;
                    # thinking would eat the tiny completion budget (shared
                    # budget on this vLLM build) and leave content empty
                    extra={"chat_template_kwargs": {"enable_thinking": False}})
                text = resp if isinstance(resp, str) else resp.get("content", "")
            except Exception as e:  # noqa: BLE001
                text = f"__ERROR__ {e}"
            viol, conf = parse_noul(text)
            rec = {"_key": str(key), "scenario_id": c["scenario_id"],
                   "thinking": c.get("thinking"), "round": c.get("round"),
                   "witness": c["witness"], "grade": c.get("grade"),
                   "witness_rules": c.get("witness_rules"),
                   "judge_violation": viol, "judge_confidence": conf,
                   "raw": text[:400]}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            n_call += 1
            print(f"[{n_call}] {c['scenario_id']} r{c.get('round')} "
                  f"witness={c['witness']} judge={viol} conf={conf}")
    print(f"wrote {out_path}; run analysis with scripts/judge_calibration_p0_analyze.py")


if __name__ == "__main__":
    main()

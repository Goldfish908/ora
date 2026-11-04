#!/usr/bin/env python3
"""P-track synthetic injection factory v0 (docs/paper/p_track_repair_training_v0.1.md).

Takes CORRECT solution code for RetailOpt dev40 scenarios (training slice
only — data/m1_retailopt/dev40_f1f4.jsonl; gapcheck60 / F5-F8 are never
touched), injects one known semantic bug per (scenario, mutant_type) with an
LLM, then runs a repair loop: the LLM gets {problem, broken_code,
witness violation text} and rewrites the full script; each repair attempt is
executed (PySCIPOpt sandbox) and re-verified by the m1_witness checker.
A repair is `verified` iff witness reports zero violations AND
|objective - reference_objective| / |reference_objective| <= 1e-3.

Mutant operators v0 (D2 templates):
  phantom_inventory : free initial stock / free resources not in the problem
  wrong_constant    : one problem-data constant shifted by 10-30%
  drop_constraint   : one constraint family required by the prompt removed

Correct-code sources, in preference order:
  1. LLM-written gen.py from earlier mainline cells whose ledger row is
     witness-feasible AND grade==match (runs/m1_pilot, runs/m1_feedback,
     runs/m1_pilot_priors{,2,3}); the stored solution.json is re-checked
     against dev40 data before use.
  2. Fallback: standalone script wrapping scripts/m1_reference.build_and_solve
     (executed once and witness+gold verified before use).

Samples land in runs/p1_factory/samples_<scenario>__<mutant>.json (one file
per pair; existing files are skipped => resume + sharding safe).

Usage (from /home/hewj13/wm/ora):
    source ~/.leagent_env
    export ORA_LLM_BASE_URL=$QWEN27B_BASE_URL ORA_LLM_API_KEY=$QWEN27B_API_KEY \
        ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
    PY=/home/hewj13/planbb/miniforge3/envs/rl/bin/python
    $PY scripts/p1_inject_factory.py --scenarios retail_f1_jit_logic_v0 \
        retail_f2_cannibalization_v4            # smoke: 2 x 3 = 6 samples
    $PY scripts/p1_inject_factory.py --shard 0/4  # full run, 4 shards
"""

from __future__ import annotations

import argparse
import difflib
import inspect
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent import llm as llm_mod  # noqa: E402
from m1_witness import retailopt as witness  # noqa: E402
from scripts.m1_pilot import (  # noqa: E402
    SCIP_OUTPUT_FORMAT_SOL, adapt_prompt_schema, extract_code, run_code,
    grade)

DEV40 = ROOT / "data" / "m1_retailopt" / "dev40_f1f4.jsonl"
OUT_DIR = ROOT / "runs" / "p1_factory"
MUTANTS = ["phantom_inventory", "wrong_constant", "drop_constraint"]
OBJ_REL_TOL = 1e-3
MAX_TOKENS = 16384
TEMPERATURE = 0.3
THINKING_OFF = {"chat_template_kwargs": {"enable_thinking": False}}

MUTANT_INSTRUCTIONS = {
    "phantom_inventory": (
        "Give the model INITIAL INVENTORY or another free source of goods "
        "that the problem does NOT provide. Typical ways: remove or relax "
        "the constraints that pin period-1 inventory to zero, or add an "
        "extra unconstrained inflow of stock in the first period(s). The "
        "model will then satisfy demand out of thin air and report a cost "
        "that is too low."),
    "wrong_constant": (
        "Pick exactly ONE numeric constant in the code that stands for a "
        "problem parameter (a cost coefficient, a capacity, a demand level, "
        "shelf life, lead time, a budget, a rate, ...) and change its value "
        "by 10-30% in either direction — e.g. scale the value where it is "
        "read from `data`, or replace the expression with a hard-coded "
        "wrong value. The change must actually alter the optimal solution "
        "or the reported objective (a binding capacity/demand/shelf-life "
        "value changes decisions; a cost coefficient always shifts the "
        "reported objective)."),
    "drop_constraint": (
        "Delete exactly ONE constraint family that the problem statement "
        "explicitly requires (for example: cold-storage capacity, aggregate "
        "production capacity, sales <= inventory availability, the demand "
        "balance with lost sales, the inventory aging equations, or the "
        "waste definition). Remove the whole family of addCons calls for "
        "it; keep everything else identical. IMPORTANT: choose a constraint "
        "that is BINDING at the optimum — removing a slack constraint "
        "changes nothing and is useless. Do not remove balance equations "
        "that make the model unbounded; the solver must still reach a "
        "finite optimal solution."),
}


# ---------------------------------------------------------------- correct code

def _ledger_rows():
    """All mainline ledger rows, tagged with where their sandbox lives."""
    sources = [
        # (ledger run dir, ledger glob, sandbox dir, sandbox name template)
        ("runs/m1_pilot", "m1_pilot_schema_sol*.jsonl",
         "runs/m1_pilot/sandbox", "schema_sol__{sid}__{mode}"),
        ("runs/m1_feedback", "m1_feedback*.jsonl",
         "runs/m1_feedback/sandbox", "fb__{sid}__{mode}__r{rnd}"),
        ("runs/m1_pilot_priors", "m1_pilot_schema_sol*.jsonl",
         "runs/m1_pilot_priors/sandbox", "schema_sol__{sid}__{mode}"),
        ("runs/m1_pilot_priors2", "m1_pilot_schema_sol*.jsonl",
         "runs/m1_pilot_priors2/sandbox", "schema_sol__{sid}__{mode}"),
        ("runs/m1_pilot_priors3", "m1_pilot_schema_sol*.jsonl",
         "runs/m1_pilot_priors3/sandbox", "schema_sol__{sid}__{mode}"),
    ]
    for run_dir, glob, sb_dir, tmpl in sources:
        for f in sorted(ROOT.glob(f"{run_dir}/{glob}")):
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                r["_sb"] = ROOT / sb_dir / tmpl.format(
                    sid=r.get("scenario_id"), mode=r.get("thinking"),
                    rnd=r.get("round", 1))
                yield r


def _true_success(rec: dict) -> bool:
    return (rec.get("witness") == "feasible"
            and rec.get("grade") in ("match", "better_than_reference"))


def _verified_correct(data: dict, sol_path: Path, gold: float) -> bool:
    try:
        sol = json.loads(sol_path.read_text())
    except Exception:
        return False
    if not isinstance(sol, dict) or "objective" not in sol:
        return False
    res = witness.check(data, sol)
    if res["violations"]:
        return False
    gap = abs(float(sol["objective"]) - gold) / max(1.0, abs(gold))
    return gap <= OBJ_REL_TOL


def _reference_template_code() -> str:
    """Standalone per-scenario script wrapping m1_reference.build_and_solve."""
    from scripts import m1_reference
    fn_src = inspect.getsource(m1_reference.build_and_solve)
    return (
        "import json\n\n" + fn_src + "\n\n"
        "data = json.loads(open('data.json').read())\n"
        "meta, sol = build_and_solve(data, time_limit=570,"
        " handled_mode='received')\n"
        "print(f\"status: {meta['status']}\")\n"
        "if sol is not None:\n"
        "    print(f\"objective: {meta['objective']}\")\n"
        "    json.dump(sol, open('solution.json', 'w'))\n"
    )


def find_correct_code(sid: str, row: dict) -> tuple[str, str] | None:
    """Return (code_text, source_description) or None.

    Preference: earliest-round LLM cell whose stored solution re-passes the
    witness against the dev40 data row; fallback: reference-solver template,
    executed once and verified (cached under runs/p1_factory/correct/).
    """
    data = json.loads(row["data"])
    gold = row["reference_objective"]
    cands = [r for r in _ledger_rows()
             if r.get("scenario_id") == sid and _true_success(r)]
    cands.sort(key=lambda r: r.get("round", 1))
    for r in cands:
        sb = r["_sb"]
        code_p, sol_p = sb / "gen.py", sb / "solution.json"
        if not (code_p.exists() and sol_p.exists()):
            continue
        if _verified_correct(data, sol_p, gold):
            src = (f"{code_p.relative_to(ROOT)} "
                   f"(mode={r.get('thinking')} round={r.get('round', 1)})")
            return code_p.read_text(), src
    # fallback: reference template, verified by one execution
    cache = OUT_DIR / "correct" / sid
    code_p, sol_p = cache / "gen.py", cache / "solution.json"
    if not sol_p.exists():
        code = _reference_template_code()
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "data.json").write_text(row["data"])
        rec = run_code(code, cache)
        if rec.get("exec_status") != "ok" or not sol_p.exists():
            return None
    if _verified_correct(data, sol_p, gold):
        return code_p.read_text(), "m1_reference.build_and_solve template"
    return None


# ---------------------------------------------------------------- LLM helpers

def llm_call(cfg, messages) -> tuple[str, dict]:
    t0 = time.time()
    try:
        resp = llm_mod.chat(messages, max_tokens=MAX_TOKENS,
                            temperature=TEMPERATURE, extra=THINKING_OFF,
                            config=cfg)
        return resp.get("content") or "", {
            "llm_latency_s": round(time.time() - t0, 1),
            "finish_reason": resp.get("finish_reason"),
            "completion_tokens": (resp.get("usage") or {}).get(
                "completion_tokens"),
        }
    except Exception as e:
        return "", {"llm_latency_s": round(time.time() - t0, 1),
                    "llm_error": f"{type(e).__name__}: {e}"}


def inject(cfg, problem_text: str, code: str, mutant_type: str,
           prev_feedback: str | None) -> tuple[str | None, str | None, dict]:
    """One injection attempt -> (broken_code, injected_error, meta)."""
    msg = (
        "You are building a dataset of buggy optimization code to train a "
        "repair model.\n\n"
        "[PROBLEM STATEMENT]\n" + problem_text + "\n\n"
        "[CORRECT SOLUTION CODE]\n```python\n" + code + "\n```\n\n"
        "Introduce EXACTLY ONE semantic bug of this type: "
        f"{mutant_type}\n{MUTANT_INSTRUCTIONS[mutant_type]}\n\n"
        "Requirements:\n"
        "- The mutated script must still RUN to completion and the solver "
        "must still find a solution (no syntax errors, no crash, do not "
        "make the model infeasible).\n"
        "- Make one coherent change only; keep everything else identical, "
        "including the status/objective prints and the solution.json dump "
        "contract.\n"
        "- Do NOT leave any comment in the code that marks or explains the "
        "bug.\n"
        "- Output format: first line exactly "
        "`# INJECTED_ERROR: <one sentence describing what you changed>`, "
        "then the COMPLETE mutated Python script. No markdown fences around "
        "the script, no other text.")
    if prev_feedback:
        msg += ("\n\nYour previous attempt was rejected: " + prev_feedback +
                "\nProduce a different, valid mutation.")
    text, meta = llm_call(cfg, [{"role": "user", "content": msg}])
    if meta.get("llm_error") or not text.strip():
        return None, None, meta
    m = re.match(r"\s*# INJECTED_ERROR:\s*(.+)", text)
    if not m:
        meta["reject"] = "missing INJECTED_ERROR marker"
        return None, None, meta
    injected_error = m.group(1).strip()[:400]
    body = text[m.end():]
    code_out = extract_code(body)
    # strip any residual marker-ish comment lines so the repairer never
    # sees the label
    code_out = "\n".join(
        ln for ln in code_out.splitlines()
        if "INJECTED_ERROR" not in ln)
    try:
        compile(code_out, "broken.py", "exec")
    except SyntaxError as e:
        meta["reject"] = f"syntax error: {e}"
        return None, None, meta
    return code_out, injected_error, meta


REPAIR_TASK = (
    "{problem}\n\n"
    "[BUGGY CODE]\n```python\n{broken}\n```\n\n"
    "[CONSTRAINT VIOLATIONS — an independent witness checker re-verified "
    "the solution produced by the code above and found hard violations]\n"
    "```\n{violations}\n```\n"
    "The code contains a semantic modeling error (for example phantom "
    "resources that the problem never provides, a wrong parameter value, "
    "or a missing required constraint). Diagnose the root cause from the "
    "violations and the problem statement, fix the MODEL, and rewrite the "
    "COMPLETE corrected PySCIPOpt script. It must print status/objective "
    "and dump solution.json exactly as required by [OUTPUT FORMAT]. "
    "Output ONLY executable Python code.")


def violation_text_of(rec: dict) -> str:
    details = rec.get("witness_details") or rec.get("witness_rules") or []
    return "\n".join(details) if details else "(no details)"


def repair_feedback(rec: dict) -> str:
    """Follow-up feedback for rounds >= 2 (m1_feedback style)."""
    tail = (rec.get("stderr_tail") or "")[-600:]
    if rec.get("exec_status") == "crash":
        return ("The repaired script CRASHED. stderr (tail):\n```\n" + tail +
                "\n```\nFix and rewrite the COMPLETE script. Output ONLY "
                "executable Python code.")
    if rec.get("exec_status") == "timeout":
        return ("The repaired script exceeded the execution time limit. "
                "Make it substantially more efficient and rewrite the "
                "COMPLETE script. Output ONLY executable Python code.")
    if rec.get("solver_status") == "infeasible":
        return ("The solver reports the repaired model is INFEASIBLE — it "
                "is over-constrained. Rewrite the COMPLETE script. Output "
                "ONLY executable Python code.")
    if rec.get("witness") == "infeasible":
        return ("The repaired script still produces a solution that FAILS "
                "the independent constraint checker:\n```\n" +
                violation_text_of(rec)[:1500] +
                "\n```\nFix the MODEL and rewrite the COMPLETE script. "
                "If the violations involve quantities that NO existing "
                "constraint pins down, a required constraint family may be "
                "MISSING entirely rather than merely wrong — re-check every "
                "balance/aging/capacity/availability equation in the "
                "problem statement against the code and re-add any that "
                "are absent. Output ONLY executable Python code.")
    if rec.get("witness") in ("no_solution", "parse_error"):
        return ("The repaired script did not produce a valid solution.json. "
                "Follow the [OUTPUT FORMAT] contract exactly. Rewrite the "
                "COMPLETE script. Output ONLY executable Python code.")
    return ("The repaired solution is feasible but its objective does not "
            "match the expected optimum (|gap| > 1e-3). Re-check the model "
            "against the problem statement and rewrite the COMPLETE script. "
            "Output ONLY executable Python code.")


def run_witness_local(data: dict, sandbox: Path) -> dict:
    sol_path = sandbox / "solution.json"
    if not sol_path.exists():
        return {"witness": "no_solution"}
    try:
        sol = json.loads(sol_path.read_text())
    except json.JSONDecodeError as e:
        return {"witness": "parse_error", "witness_error": str(e)[:200]}
    res = witness.check(data, sol)
    return {
        "witness": "feasible" if not res["violations"] else "infeasible",
        "witness_rules": sorted({r for r, _ in res["violations"]}),
        "witness_details": [f"{r}: {d}" for r, d in res["violations"][:10]],
        "witness_warnings": len(res["warnings"]),
    }


def removed_lines_summary(correct: str, broken: str, max_lines: int = 4
                          ) -> str:
    """What the injection attempt deleted/changed vs the correct code."""
    removed = [l[1:].strip() for l in difflib.unified_diff(
        correct.splitlines(), broken.splitlines(), lineterm="", n=0)
        if l.startswith("-") and not l.startswith("---")]
    removed = [l for l in removed if l and not l.startswith("#")]
    return "; ".join(removed[:max_lines])[:300]


# ---------------------------------------------------------------- main pipeline

def seed_tag_safe(seed_tag: str) -> str:
    return seed_tag


def process_pair(cfg, row: dict, mutant_type: str, code: str, code_src: str,
                 problem_text: str, max_repair_rounds: int,
                 inject_retries: int, seed_note: str | None = None,
                 seed_tag: str = "") -> dict:
    sid = row["scenario_id"]
    data = json.loads(row["data"])
    gold = row["reference_objective"]
    sb_root = OUT_DIR / "sandbox" / f"{sid}__{mutant_type}{seed_tag_safe(seed_tag)}"
    sample = {
        "scenario_id": sid, "mutant_type": mutant_type,
        "problem_text": problem_text,
        "broken_code": None, "violation_text": None,
        "repaired_code": None, "witness_verdict": None,
        "objective_before": None, "objective_after": None,
        "gold_objective": gold, "repair_rounds": 0,
        "code_source": code_src, "injected_error": None,
        "mutant_valid": False, "invalid_reason": None,
        "repair_history": [],
    }

    # ---- injection (with retries gated by the witness)
    feedback = seed_note
    tried: list[str] = []
    for attempt in range(1, inject_retries + 1):
        attempt_feedback = feedback or ""
        if tried:
            attempt_feedback += (
                "\nAttempts already made and REJECTED: "
                + " | ".join(tried)
                + ". You MUST pick a target you have not tried before.")
        broken, injected_error, meta = inject(
            cfg, problem_text, code, mutant_type, attempt_feedback or None)
        sample.setdefault("injection_attempts", []).append(meta)
        if broken is None:
            feedback = meta.get("reject") or meta.get("llm_error") \
                or "empty LLM response"
            continue
        tried.append(removed_lines_summary(code, broken) or "(no diff)")
        sb = sb_root / f"inject_a{attempt}"
        sb.mkdir(parents=True, exist_ok=True)
        (sb / "data.json").write_text(row["data"])
        exec_rec = run_code(broken, sb)
        exec_rec.update(run_witness_local(data, sb))
        sample["injection_attempts"][-1]["exec"] = {
            k: exec_rec.get(k) for k in
            ("exec_status", "solver_status", "objective", "witness",
             "witness_rules", "wall_s")}
        removed = tried[-1]
        if exec_rec.get("exec_status") != "ok":
            feedback = (f"the mutated script did not run cleanly "
                        f"(exec_status={exec_rec.get('exec_status')}, "
                        f"solver={exec_rec.get('solver_status')})")
            continue
        if exec_rec.get("solver_status") != "optimal" \
                or exec_rec.get("objective") is None:
            feedback = (
                f"the mutated script's solver status was "
                f"{exec_rec.get('solver_status')} — the model became "
                "infeasible or unbounded. Pick a mutation that keeps the "
                "model solvable with a finite optimum (e.g. relax/remove a "
                "capacity or availability constraint rather than a "
                "balance/flow equation)")
            if removed:
                feedback += (f". Your attempt changed: {removed}")
            continue
        if exec_rec.get("witness") != "infeasible":
            feedback = ("the mutated script's solution triggered NO "
                        "witness violation — the bug must produce a "
                        "feasible-looking solution that violates the "
                        "problem's real constraints. Pick a parameter or "
                        "constraint that BINDS: a wrong cost coefficient "
                        "always shifts the reported objective; a wrong "
                        "capacity/demand/shelf-life value changes the "
                        "decisions themselves")
            if removed:
                feedback += (f". Your attempt changed: {removed} — that "
                             "had NO effect on the solution; choose a "
                             "DIFFERENT target")
            continue
        # valid mutant
        sample.update(mutant_valid=True, broken_code=broken,
                      injected_error=injected_error,
                      objective_before=exec_rec.get("objective"),
                      violation_text=violation_text_of(exec_rec),
                      violation_rules=exec_rec["witness_rules"],
                      exec_before=exec_rec)
        break
    else:
        sample["invalid_reason"] = feedback
        return sample

    # ---- repair loop
    messages = [{"role": "user", "content": REPAIR_TASK.format(
        problem=problem_text, broken=sample["broken_code"],
        violations=sample["violation_text"])}]
    for rnd in range(1, max_repair_rounds + 1):
        text, meta = llm_call(cfg, messages)
        hrec = {"round": rnd, **meta}
        if meta.get("llm_error") or not text.strip():
            hrec["exec_status"] = "llm_error"
            sample["repair_history"].append(hrec)
            break
        repaired = extract_code(text)
        sb = sb_root / f"repair_r{rnd}"
        sb.mkdir(parents=True, exist_ok=True)
        (sb / "data.json").write_text(row["data"])
        exec_rec = run_code(repaired, sb)
        exec_rec.update(run_witness_local(data, sb))
        g = grade(exec_rec.get("objective"), gold,
                  exec_rec.get("solver_status"))
        hrec.update({k: exec_rec.get(k) for k in
                     ("exec_status", "solver_status", "objective",
                      "witness", "witness_rules", "witness_details",
                      "wall_s")})
        hrec["grade"] = g
        sample["repair_history"].append(hrec)
        verified = exec_rec.get("witness") == "feasible" and g == "match"
        sample["repair_rounds"] = rnd
        sample["repaired_code"] = repaired
        sample["objective_after"] = exec_rec.get("objective")
        if verified:
            sample["witness_verdict"] = {
                "verdict": "pass", "grade": g,
                "objective": exec_rec.get("objective"),
                "rules": [], "details": [],
                "warnings": exec_rec.get("witness_warnings", 0)}
            break
        sample["witness_verdict"] = {
            "verdict": "fail", "grade": g,
            "objective": exec_rec.get("objective"),
            "rules": exec_rec.get("witness_rules") or [],
            "details": exec_rec.get("witness_details") or [],
            "exec_status": exec_rec.get("exec_status"),
            "solver_status": exec_rec.get("solver_status")}
        if rnd < max_repair_rounds:
            messages.append({"role": "assistant", "content": repaired})
            messages.append({"role": "user",
                             "content": repair_feedback(exec_rec)})
    return sample


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", default="0/1", help="k/K zero-based")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap on (scenario, mutant) pairs AFTER sharding")
    ap.add_argument("--scenarios", nargs="*", default=None,
                    help="restrict to these scenario_ids (smoke)")
    ap.add_argument("--mutants", nargs="*", default=MUTANTS,
                    choices=MUTANTS)
    ap.add_argument("--max-repair-rounds", type=int, default=3)
    ap.add_argument("--inject-retries", type=int, default=2)
    ap.add_argument("--data", default=str(DEV40),
                    help="input jsonl (default: dev40); use f1f4_all100 for "
                         "the scale-out run")
    ap.add_argument("--seeds", type=int, default=1,
                    help="injection seeds per (scenario, mutant); seed 0 "
                         "keeps the legacy output name so existing samples "
                         "are reused")
    args = ap.parse_args()

    data_path = Path(args.data)
    rows = [json.loads(l) for l in data_path.read_text().splitlines()
            if l.strip()]
    sids = sorted({r["scenario_id"] for r in rows})
    by_sid = {r["scenario_id"]: r for r in rows}
    if args.scenarios:
        unknown = [s for s in args.scenarios if s not in by_sid]
        if unknown:
            sys.exit(f"not in {data_path.name}: {unknown}")
        sids = [s for s in sids if s in set(args.scenarios)]

    pairs = [(s, m, sd) for s in sids for m in args.mutants
             for sd in range(args.seeds)]
    k, kk = (int(x) for x in args.shard.split("/"))
    pairs = [p for i, p in enumerate(pairs) if i % kk == k]
    if args.limit:
        pairs = pairs[: args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = llm_mod.load_config()
    prompt_cache: dict[str, str] = {}

    stats = {"done": 0, "skip": 0, "no_code": 0, "invalid": 0}
    for sid, mtype, seed in pairs:
        seed_tag = f"__s{seed}" if seed > 0 else ""
        out_path = OUT_DIR / f"samples_{sid}__{mtype}{seed_tag}.json"
        if out_path.exists():
            print(f"[skip] {sid} {mtype}{seed_tag} (sample exists)", flush=True)
            stats["skip"] += 1
            continue
        row = by_sid[sid]
        found = find_correct_code(sid, row)
        if found is None:
            rec = {"scenario_id": sid, "mutant_type": mtype,
                   "gold_objective": row["reference_objective"],
                   "mutant_valid": False,
                   "invalid_reason": "no_correct_code"}
            out_path.write_text(json.dumps(rec, ensure_ascii=False,
                                           indent=2))
            print(f"[no-code] {sid} {mtype}{seed_tag}", flush=True)
            stats["no_code"] += 1
            continue
        code, code_src = found
        if sid not in prompt_cache:
            prompt_cache[sid] = adapt_prompt_schema(row["prompt_schema"],
                                                    SCIP_OUTPUT_FORMAT_SOL)
        seed_note = None
        if seed > 0:
            seed_note = (f"This is injection seed #{seed}: the same problem "
                         f"has already been mutated {seed} time(s) at OTHER "
                         f"locations. You MUST pick a different constant, "
                         f"constraint, or injection point than the obvious "
                         f"first choice.")
        t0 = time.time()
        sample = process_pair(cfg, row, mtype, code, code_src,
                              prompt_cache[sid], args.max_repair_rounds,
                              args.inject_retries, seed_note=seed_note,
                              seed_tag=seed_tag)
        sample["wall_s_total"] = round(time.time() - t0, 1)
        out_path.write_text(json.dumps(sample, ensure_ascii=False,
                                       indent=2))
        stats["done" if sample["mutant_valid"] else "invalid"] += 1
        wv = sample.get("witness_verdict") or {}
        print(f"[{sid}][{mtype}{seed_tag}] valid={sample['mutant_valid']} "
              f"rules={sample.get('violation_rules')} "
              f"obj {sample.get('objective_before')} -> "
              f"{sample.get('objective_after')} (gold={sample['gold_objective']}) "
              f"verdict={wv.get('verdict')} rounds={sample['repair_rounds']} "
              f"wall={sample['wall_s_total']}s", flush=True)
    print("SUMMARY", json.dumps(stats), flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""N3b: does the playbook method transfer across datasets? (IndustryOR)

Two-phase experiment on the 61 wrong IndustryOR judge cells:

Phase 1 (baseline repair): repair each wrong cell with D2.1 rule violations
as feedback, up to 3 rounds. Verified by re-execution + objective match vs
the reference + zero rule violations. The gold value is NEVER shown to the
repairer (only "does not match the expected optimum").

Phase 2 (card rescue): distill a repair card from up to 4 verified Phase-1
successes, then re-attempt the Phase-1 failures with the card prepended.

This mirrors the RetailOpt P2 playbook experiment (97% rescue of stubborn
phantom-inventory failures) but on a different dataset whose errors are
natural LLM modeling errors rather than injected mutants.

Usage:
    python3 scripts/n3b_ior_rescue.py --phase 1 --shard 0/4
    python3 scripts/n3b_ior_rescue.py --card      # distill card
    python3 scripts/n3b_ior_rescue.py --phase 2 --shard 0/4
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ora_agent import llm as llm_mod  # noqa: E402
from d1_apply import run_rule  # noqa: E402
from m1_pilot import extract_code, grade, run_code  # noqa: E402
from p1_inject_factory import MAX_TOKENS, TEMPERATURE, THINKING_OFF  # noqa: E402
from p2_repair_hints import CARD_TASK, PLAYBOOK_HEADER  # noqa: E402

CELLS = ROOT / "runs" / "industryor" / "industryor_judge_cells.jsonl"
RULES_DIR = ROOT / "runs" / "d2_authoring"
OUT_DIR = ROOT / "runs" / "n3b_ior_rescue"
CARD_PATH = OUT_DIR / "card_industryor.json"
OBJ_REL_TOL = 1e-4

REPAIR_TASK_IOR = (
    "[PROBLEM]\n{problem}\n\n"
    "[BUGGY CODE]\n```python\n{broken}\n```\n\n"
    "[AUDIT FINDINGS — independent audit rules checked the code and its "
    "printed objective against the problem statement]\n```\n{violations}\n"
    "```\n"
    "The code contains a semantic modeling error. Diagnose the root cause "
    "from the findings and the problem statement, fix the MODEL, and "
    "rewrite the COMPLETE corrected PySCIPOpt script. It must print "
    "`status: <solver status>` and `objective: <value>` exactly. "
    "Output ONLY executable Python code.")


def load_rules() -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for p in sorted(RULES_DIR.glob("d2rules_*.json")):
        try:
            rec = json.loads(p.read_text())
        except Exception:
            continue
        if rec.get("ok"):
            out[rec["id"]] = [r for r in rec.get("rules", [])
                              if r.get("code") and r.get("status") == "calibrated"]
    return out


def audit(code: str, objective, rules: list[dict]) -> list[str]:
    """Violation strings from all calibrated rules that fire."""
    out = []
    for r in rules:
        res = run_rule(r["code"], code, objective, {})
        if res.get("status") == "ok" and res.get("violation"):
            out.append(f"[{r['template']}] {res['violation']}")
    return out


def verified(code: str, reference, rules: list[dict], sandbox: Path) -> dict:
    exec_rec = run_code(code, sandbox)
    g = grade(exec_rec.get("objective"), reference,
              exec_rec.get("solver_status"))
    vios = audit(code, exec_rec.get("objective"), rules)
    ok = (exec_rec.get("exec_status") == "ok" and g == "match" and not vios)
    return {"ok": ok, "grade": g, "violations": vios,
            **{k: exec_rec.get(k) for k in
               ("exec_status", "solver_status", "objective", "wall_s",
                "stderr_tail")}}


def feedback_for(v: dict) -> str:
    if v.get("exec_status") == "crash":
        return ("The repaired script CRASHED. stderr (tail):\n```\n" +
                (v.get("stderr_tail") or "")[-600:] +
                "\n```\nFix and rewrite the COMPLETE script. Output ONLY "
                "executable Python code.")
    if v.get("exec_status") == "timeout":
        return ("The repaired script exceeded the execution time limit. "
                "Make it substantially more efficient. Output ONLY "
                "executable Python code.")
    if v.get("violations"):
        return ("The repaired script still FAILS the audit rules:\n```\n" +
                "\n".join(v["violations"])[:1500] +
                "\n```\nFix the MODEL and rewrite the COMPLETE script. "
                "Output ONLY executable Python code.")
    if v.get("grade") != "match":
        return ("The repaired solution's objective does not match the "
                "expected optimum. Re-check the model against the problem "
                "statement (constants, constraint directions, missing "
                "constraints). Output ONLY executable Python code.")
    return "Rewrite the COMPLETE script. Output ONLY executable Python code."


def repair_cell(cfg, cell: dict, rules: list[dict], card: str | None,
                max_rounds: int) -> dict:
    key = cell["key"]
    sb_root = OUT_DIR / "sandbox" / key
    sb_root.mkdir(parents=True, exist_ok=True)
    vios0 = audit(cell["code"], cell.get("objective"), rules)
    task = REPAIR_TASK_IOR.format(
        problem=cell["prompt"], broken=cell["code"],
        violations="\n".join(vios0) if vios0 else "(no rule fired; the "
        "objective value is wrong for a reason the rules did not capture)")
    if card:
        task = PLAYBOOK_HEADER + "```\n" + card + "\n```\n\n" + task
    rec = {"key": key, "id": cell["id"], "arm": cell["arm"],
           "reference": cell.get("reference"),
           "card": bool(card), "rounds": 0, "rescued": False,
           "initial_violations": vios0, "history": []}
    messages = [{"role": "user", "content": task}]
    for rnd in range(1, max_rounds + 1):
        t0 = time.time()
        try:
            resp = llm_mod.chat(messages, max_tokens=MAX_TOKENS,
                                temperature=TEMPERATURE, extra=THINKING_OFF,
                                config=cfg)
            text = resp.get("content") or ""
        except Exception as e:
            rec["history"].append({"round": rnd,
                                   "llm_error": f"{type(e).__name__}: {e}"})
            break
        code = extract_code(text)
        sb = sb_root / ("card_r%d" % rnd if card else "base_r%d" % rnd)
        sb.mkdir(parents=True, exist_ok=True)
        v = verified(code, cell.get("reference"), rules, sb)
        v["round"] = rnd
        v["llm_latency_s"] = round(time.time() - t0, 1)
        rec["history"].append(v)
        rec["rounds"] = rnd
        if v["ok"]:
            rec["rescued"] = True
            rec["rescued_code"] = code
            break
        if rnd < max_rounds:
            messages.append({"role": "assistant", "content": code})
            messages.append({"role": "user", "content": feedback_for(v)})
    return rec


def is_rescued(rec: dict) -> bool:
    return bool(rec.get("rescued"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", type=int, default=1)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--card", action="store_true")
    ap.add_argument("--n-card-examples", type=int, default=4)
    args = ap.parse_args()

    cells = [json.loads(l) for l in CELLS.read_text().splitlines() if l.strip()]
    wrong = [c for c in cells if c.get("wrong") and c.get("reference") is not None]
    rules_by_id = load_rules()
    wrong = [c for c in wrong if rules_by_id.get(c["id"])]
    print(f"wrong cells with rules: {len(wrong)}", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = llm_mod.load_config()

    if args.card:
        successes = []
        for p in sorted(OUT_DIR.glob("base_*.json")):
            rec = json.loads(p.read_text())
            if is_rescued(rec):
                successes.append(rec)
        if not successes:
            sys.exit("no phase-1 successes to distill a card from")
        blocks = []
        for s in successes[: args.n_card_examples]:
            cell = next(c for c in cells if c["key"] == s["key"])
            diff = "\n".join(difflib.unified_diff(
                cell["code"].splitlines(),
                (s.get("rescued_code") or "").splitlines(),
                lineterm="", n=2))
            blocks.append(f"=== example ({s['key']}) ===\n"
                          f"[AUDIT FINDINGS]\n"
                          f"{chr(10).join(s.get('initial_violations') or [])[:900]}\n"
                          f"[FIX DIFF]\n{diff[:2600]}")
        resp = llm_mod.chat(
            [{"role": "user", "content":
              CARD_TASK.format(n=min(args.n_card_examples, len(successes)),
                               examples="\n\n".join(blocks))}],
            max_tokens=2048, temperature=0.2, extra=THINKING_OFF, config=cfg)
        card = {"dataset": "industryor",
                "n_examples": min(args.n_card_examples, len(successes)),
                "example_keys": [s["key"] for s in successes[: args.n_card_examples]],
                "card": (resp.get("content") or "").strip()}
        CARD_PATH.write_text(json.dumps(card, ensure_ascii=False, indent=2))
        print(f"[card] authored from {card['n_examples']} examples -> {CARD_PATH}",
              flush=True)
        return

    card_text = None
    if args.phase == 2:
        if not CARD_PATH.exists():
            sys.exit("run --card first")
        card = json.loads(CARD_PATH.read_text())
        card_text = card["card"]
        # phase-2 subjects: phase-1 failures, excluding card example problems
        ex_keys = set(card.get("example_keys") or [])
        done = {}
        for p in sorted(OUT_DIR.glob("base_*.json")):
            rec = json.loads(p.read_text())
            done[rec["key"]] = rec
        subjects = [c for c in wrong
                    if c["key"] in done and not is_rescued(done[c["key"]])
                    and c["key"] not in ex_keys]
        print(f"phase-2 subjects (phase-1 failures minus card examples): "
              f"{len(subjects)}", flush=True)
    else:
        card_text = None
        subjects = wrong

    k, kk = (int(x) for x in args.shard.split("/"))
    todo = [s for i, s in enumerate(subjects) if i % kk == k]
    if args.limit:
        todo = todo[: args.limit]

    for c in todo:
        prefix = "card" if args.phase == 2 else "base"
        out = OUT_DIR / f"{prefix}_{c['key']}.json"
        if out.exists():
            print(f"[{c['key']}] exists, skip", flush=True)
            continue
        rec = repair_cell(cfg, c, rules_by_id[c["id"]], card_text,
                          args.max_rounds)
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
        print(f"[{c['key']}] rescued={rec['rescued']} rounds={rec['rounds']}",
              flush=True)


if __name__ == "__main__":
    main()

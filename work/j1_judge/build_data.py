#!/usr/bin/env python3
"""J1: build SFT data for the semantic judge.

Train: 316 RetailOpt cells (the P0/Open-Jev calibration key set), labels from
the witness checker in runs/m1_feedback ledgers (latest version per key),
code from the cell's OWN sandbox fb__{sid}__{thinking}__r{round}/gen.py
(NOTE: scripts/judge_calibration_p0.py had a truthiness bug mapping
thinking='off' cells to the '__on__' sandbox; we use the correct per-key dir).

Test: 240 IndustryOR cells (runs/industryor/industryor_judge_cells.jsonl),
wrong=true == phantom (printed objective mismatches en_answer).

Hard constraint: IndustryOR cells go ONLY to test.jsonl.

Outputs (work/j1_judge/data/):
  train_cells.jsonl  316 labeled RetailOpt cells (raw, natural order)
  train.jsonl        SFT-ready 316 unique cells, class-weight field
                     (w_pass=2.079, w_wrong=0.658; loss multiplied per sample)
  test.jsonl         240 IndustryOR cells, prompt only + wrong label
  stats.json         counts and length stats
"""
import json
import re
import random
import statistics
from pathlib import Path

ROOT = Path("/home/hewj13/wm/ora")
OUT = ROOT / "work" / "j1_judge" / "data"
OUT.mkdir(parents=True, exist_ok=True)

PROMPT_BUDGET = 6000
CODE_BUDGET = 4000

SYSTEM = ("You are a strict semantics auditor for operations-research "
          "optimization models. Given a problem statement, the modeling code, "
          "and the objective value returned by the solver, decide whether the "
          "returned solution is semantically consistent with the problem "
          "statement. Reply with a single JSON object: "
          '{"verdict": "pass" or "fail", "reason": "brief justification"}. '
          'Use "fail" when the solution violates stated or implied '
          "constraints, or the reported objective is inconsistent with the "
          "model (a phantom solution).")


def user_content(prompt: str, code: str, objective) -> str:
    prompt = prompt[:PROMPT_BUDGET]
    if len(code) > CODE_BUDGET:
        code = code[:CODE_BUDGET] + "\n# ... [truncated]"
    return (f"[PROBLEM]\n{prompt}\n\n[MODEL CODE]\n{code}\n\n"
            f"[RETURNED OBJECTIVE]\n{objective}")


# ---------- RetailOpt train cells ----------
cells = {}
for f in sorted((ROOT / "runs" / "m1_feedback").glob("m1_feedback_v*.jsonl")):
    ver = int(re.search(r"_v(\d+)", f.name).group(1))
    for line in f.open():
        r = json.loads(line)
        if r.get("witness") not in ("feasible", "infeasible"):
            continue
        key = (r["scenario_id"], r.get("thinking"), r.get("round"))
        if key not in cells or ver > cells[key][0]:
            cells[key] = (ver, r)

prompts = {}
for line in (ROOT / "data" / "m1_retailopt" / "retailopt_190.jsonl").open():
    r = json.loads(line)
    prompts[r["scenario_id"]] = r["prompt_schema"]

sb = ROOT / "runs" / "m1_feedback" / "sandbox"
train_cells = []
for line in (ROOT / "runs" / "judge_calib_p0" / "judge_p0.jsonl").open():
    jr = json.loads(line)
    key = (jr["scenario_id"], jr["thinking"], jr["round"])
    ver, r = cells[key]
    d = sb / f"fb__{key[0]}__{key[1]}__r{key[2]}"  # correct per-key sandbox
    code = (d / "gen.py").read_text()
    wrong = r["witness"] == "infeasible"
    train_cells.append({
        "key": f"{key[0]}|{key[1]}|r{key[2]}",
        "scenario_id": key[0], "thinking": key[1], "round": key[2],
        "prompt": prompts[key[0]], "code": code,
        "objective": r.get("objective"),
        "reference": r.get("reference_objective"),
        "wrong": wrong, "grade": r.get("grade"),
        "witness_rules": r.get("witness_rules") or [],
        "witness_detail0": (r.get("witness_details") or [""])[0][:200],
    })
assert len(train_cells) == 316

with (OUT / "train_cells.jsonl").open("w") as f:
    for c in train_cells:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")


def target_for(c) -> str:
    if c["wrong"]:
        reason = c["witness_detail0"] or "violates problem semantics"
        reason = reason.split(";")[0][:160]
    else:
        reason = "solution satisfies the checked semantic constraints; reported objective is consistent with the model"
    return json.dumps({"verdict": "fail" if c["wrong"] else "pass",
                       "reason": reason}, ensure_ascii=False)


# ---------- SFT-ready train.jsonl, class-weighted (no duplication) ----------
n_wrong = sum(1 for c in train_cells if c["wrong"])
n_pass = len(train_cells) - n_wrong
w_wrong = len(train_cells) / (2 * n_wrong)
w_pass = len(train_cells) / (2 * n_pass)
rows = []
for c in train_cells:
    rows.append({"key": c["key"], "wrong": c["wrong"],
                 "weight": round(w_wrong if c["wrong"] else w_pass, 6),
                 "system": SYSTEM,
                 "user": user_content(c["prompt"], c["code"], c["objective"]),
                 "target": target_for(c)})
rng = random.Random(0)
rng.shuffle(rows)
with (OUT / "train.jsonl").open("w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# ---------- IndustryOR test.jsonl ----------
test_rows = []
for line in (ROOT / "runs" / "industryor" / "industryor_judge_cells.jsonl").open():
    c = json.loads(line)
    test_rows.append({"key": c["key"], "arm": c["arm"],
                      "difficulty": c["difficulty"], "wrong": c["wrong"],
                      "system": SYSTEM,
                      "user": user_content(c["prompt"], c["code"],
                                           c["objective"])})
assert len(test_rows) == 240
with (OUT / "test.jsonl").open("w") as f:
    for r in test_rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# ---------- RetailOpt in-distribution sanity eval (same format as test) ----------
train_eval = [{"key": c["key"], "arm": "retailopt", "wrong": c["wrong"],
               "system": SYSTEM,
               "user": user_content(c["prompt"], c["code"], c["objective"])}
              for c in train_cells]
with (OUT / "train_eval.jsonl").open("w") as f:
    for r in train_eval:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

stats = {
    "train_cells": len(train_cells),
    "train_wrong": n_wrong, "train_pass": n_pass,
    "train_sft_rows": len(rows),
    "train_sft_wrong": sum(1 for r in rows if r["wrong"]),
    "train_sft_pass": sum(1 for r in rows if not r["wrong"]),
    "class_weight_wrong": round(w_wrong, 4),
    "class_weight_pass": round(w_pass, 4),
    "test_cells": len(test_rows),
    "test_wrong": sum(1 for r in test_rows if r["wrong"]),
    "test_pass": sum(1 for r in test_rows if not r["wrong"]),
    "train_user_chars": {"min": min(len(r["user"]) for r in rows),
                         "med": int(statistics.median(len(r["user"]) for r in rows)),
                         "max": max(len(r["user"]) for r in rows)},
    "test_user_chars": {"min": min(len(r["user"]) for r in test_rows),
                        "med": int(statistics.median(len(r["user"]) for r in test_rows)),
                        "max": max(len(r["user"]) for r in test_rows)},
}
(OUT / "stats.json").write_text(json.dumps(stats, indent=1))
print(json.dumps(stats, indent=1))

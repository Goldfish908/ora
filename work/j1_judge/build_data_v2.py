#!/usr/bin/env python3
"""J1.1 (v2): rebuild SFT data — 381 RetailOpt cells (316 P0 + 65 unused),
varied pass reasons (anti template-memorization), verdict-fail reasons keep
witness detail. Test set NOT rebuilt (IndustryOR stays untouched, test-only).

Changes vs build_data.py (v1):
- train pool = ALL labeled cells in runs/m1_feedback (latest version per key),
  not just the judge_p0 key set: 381 = 294 wrong / 87 pass.
- pass reason: one of 8 templates chosen by md5(key), embedding the returned
  objective value -> input-dependent, not a constant string.
- outputs go to data/v2/ (v1 artifacts in data/ are left intact).

Outputs (work/j1_judge/data/v2/):
  train_cells_v2.jsonl / train_v2.jsonl / train_eval_v2.jsonl / stats_v2.json
"""
import hashlib
import json
import re
import random
import statistics
from pathlib import Path

ROOT = Path("/home/hewj13/wm/ora")
OUT = ROOT / "work" / "j1_judge" / "data" / "v2"
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

PASS_TEMPLATES = [
    "checked constraints are satisfied; reported objective {obj} matches the model",
    "no semantic violation found; objective {obj} is consistent with the code",
    "the model respects the stated constraints; solver returned {obj}",
    "all audited constraints hold; returned objective {obj} agrees with the formulation",
    "solution is semantically consistent with the statement; objective {obj}",
    "constraints verified against the statement; objective value {obj} is coherent",
    "no phantom objective: {obj} follows from the stated model",
    "model semantics match the problem; reported value {obj} accepted",
]


def user_content(prompt: str, code: str, objective) -> str:
    prompt = prompt[:PROMPT_BUDGET]
    if len(code) > CODE_BUDGET:
        code = code[:CODE_BUDGET] + "\n# ... [truncated]"
    return (f"[PROBLEM]\n{prompt}\n\n[MODEL CODE]\n{code}\n\n"
            f"[RETURNED OBJECTIVE]\n{objective}")


# ---------- all labeled RetailOpt cells (latest version per key) ----------
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
skipped = []
for key in sorted(cells):
    ver, r = cells[key]
    d = sb / f"fb__{key[0]}__{key[1]}__r{key[2]}"  # correct per-key sandbox
    if not (d / "gen.py").exists():
        skipped.append(key)
        continue
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
print(f"cells: {len(cells)} labeled, {len(train_cells)} usable, "
      f"{len(skipped)} skipped (no sandbox)")

with (OUT / "train_cells_v2.jsonl").open("w") as f:
    for c in train_cells:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")


def target_for(c) -> str:
    if c["wrong"]:
        reason = c["witness_detail0"] or "violates problem semantics"
        reason = reason.split(";")[0][:160]
    else:
        h = int(hashlib.md5(c["key"].encode()).hexdigest(), 16)
        reason = PASS_TEMPLATES[h % len(PASS_TEMPLATES)].format(obj=c["objective"])
    return json.dumps({"verdict": "fail" if c["wrong"] else "pass",
                       "reason": reason}, ensure_ascii=False)


# ---------- SFT-ready train_v2.jsonl, class-weighted ----------
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
with (OUT / "train_v2.jsonl").open("w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# ---------- in-distribution sanity eval (all 381, same format as test) ----------
train_eval = [{"key": c["key"], "arm": "retailopt", "wrong": c["wrong"],
               "system": SYSTEM,
               "user": user_content(c["prompt"], c["code"], c["objective"])}
              for c in train_cells]
with (OUT / "train_eval_v2.jsonl").open("w") as f:
    for r in train_eval:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# pass-reason template usage histogram
from collections import Counter
tmpl_use = Counter(json.loads(r["target"])["reason"].split(" ")[0]
                   for r in rows if not r["wrong"])

stats = {
    "train_cells": len(train_cells),
    "train_wrong": n_wrong, "train_pass": n_pass,
    "class_weight_wrong": round(w_wrong, 4),
    "class_weight_pass": round(w_pass, 4),
    "skipped_no_sandbox": len(skipped),
    "pass_templates": len(PASS_TEMPLATES),
    "train_user_chars": {"min": min(len(r["user"]) for r in rows),
                         "med": int(statistics.median(len(r["user"]) for r in rows)),
                         "max": max(len(r["user"]) for r in rows)},
}
(OUT / "stats_v2.json").write_text(json.dumps(stats, indent=1))
print(json.dumps(stats, indent=1))
# show two sample pass targets and one fail target
shown_p = shown_f = 0
for r in rows:
    if not r["wrong"] and shown_p < 2:
        print("PASS:", r["target"]); shown_p += 1
    if r["wrong"] and shown_f < 1:
        print("FAIL:", r["target"]); shown_f += 1

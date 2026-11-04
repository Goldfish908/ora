#!/usr/bin/env python3
"""D2: template-slot checker authoring with self-calibration.

Stage 1: the LLM reads ONLY the problem text and returns extracted params
plus template instances (slots + verbatim evidence spans + must-fire /
must-pass cases). It never writes rule code — code comes from the
human-written skeletons in ora_agent.spec_templates.

Stage 2: each instance is rendered, then its must-fire / must-pass cases are
executed in the subprocess sandbox (d1_apply.run_rule, 5s timeout). Failures
are fed back to the LLM for revision (<= 2 rounds per rule); a rule still
failing is discarded with the reason recorded.

Usage:
    python3 scripts/d2_author.py --limit 3        # smoke
    python3 scripts/d2_author.py --shard 0/4      # batch
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ora_agent import llm as llm_mod  # noqa: E402
from ora_agent import spec_templates as st  # noqa: E402
from d1_apply import run_rule  # noqa: E402

DATA = ROOT / "data" / "industryor" / "IndustryOR.json"
OUT_DIR = ROOT / "runs" / "d2_authoring"
MAX_REVISIONS = 2
MAX_RULES = 6

PROMPT = """You are auditing AI-generated optimization code BEFORE trusting its answer.
Below is an optimization problem. An LLM (not you) wrote Python code to
solve it; such code often runs fine yet models the problem WRONG (silent
failures: fabricated resources, wrong constants, wrong direction, ...).

You will NOT write code. You instantiate FIXED audit-rule templates: pick
the applicable ones, fill their slots, cite the verbatim text span that
evidences each slot value, and design two tiny self-test cases per rule.

The audit rule sees: code (str, the audited script's full text) and
objective (float or null, the printed optimal objective value).

Step 1 - "params": flat JSON dict of the problem's numeric data: short
names -> numbers (or lists of numbers for tables). Include every quantity
your slot expressions reference.

Step 2 - "rules": template instances. Available templates:

1) objective_range - flags a printed objective outside physical bounds.
   slots: {"lower": X or null, "upper": Y or null}; X/Y are numbers or
   arithmetic over params names, e.g. "(a1+a2)*train_rate", "sum(demand)".
   Operators: + - * / %% and parentheses; functions: min max abs sum round.
   At least one bound required.
   Use only for bounds CERTAIN from the text (counts >= 0; revenue <=
   total demand * max price; total production <= total capacity).
   Cases: must_fire = {"code": "", "objective": <out-of-range value>};
          must_pass = {"code": "", "objective": <in-range value>}.

1b) anchor_bound - PREFERRED over objective_range whenever the text has a
   binding clause or an obvious trivial-policy reference. A tight anchor
   catches silent errors that loose physical ranges miss.
   slots: {"direction": "lower"|"upper", "value": number/expr,
           "anchor_type": "binding_clause"|"trivial_policy",
           "evidence": "<verbatim span>"}.
   - binding_clause: "at least 100 chairs" at a known unit price => minimum
     spend lower = 100*price; "at most 5 trucks" with per-trip revenue =>
     revenue upper; capacity caps; mandatory minimums.
   - trivial_policy: cost of an obvious feasible naive plan, e.g. "buy
     everything new every stage" => a minimization objective must NOT
     exceed it; "meet all demand by purchasing at the max listed price"
     => another valid upper anchor.
   - wrong side = silent error: minimization cost BELOW a binding lower
     anchor, or ABOVE a trivial-policy upper anchor, both mean the model
     is wrong.
   Cases: must_fire = objective just across the anchor;
          must_pass = objective exactly at / safely inside the anchor.

2) sense_direction - flags the wrong optimization direction.
   slots: {"expected": "maximize" or "minimize"}.
   Declare ONLY when the text unambiguously says maximize or minimize.
   WARNING: some code legally minimizes the negated objective; if that
   pattern is plausible, skip this template.
   Cases: short snippets containing the opposite / the expected sense word
   (e.g. "model.setObjective(obj, 'minimize')").

3) constant_fidelity - flags a key text constant missing from the code's
   numeric literals.
   slots: {"name": "...", "expected": number or params expression}.
   Use only for constants that MUST appear literally in any correct code;
   avoid 0/1 and totals derivable by unit conversion.
   Cases: must_fire = short plausible snippet WITHOUT the constant;
          must_pass = same snippet WITH the constant as a literal.

4) phantom_resource - flags code assigning more of a resource than the
   text grants (classic: nonzero initial inventory the text never gives).
   slots: {"resource": "...", "keywords": [<identifier substrings a coder
   would use, e.g. "initial_inventory", "init_inv", "I0", "start_stock">],
   "granted": number (0 when the text grants none)}.
   Declare ONLY when the text is silent about the resource or states the
   granted amount explicitly.
   Cases: must_fire = snippet assigning the resource above the granted
   amount (e.g. "initial_inventory = 500" with granted 0);
          must_pass = snippet with no such assignment (or <= granted).

5) conditional_moq - flags a missing all-or-nothing relation (q = 0 or
   q >= m), which requires a binary/indicator variable.
   slots: {"m": number/expr or null, "require_binary": true or false}.
   Declare only when the text states a minimum lot / either-or condition.
   Cases: must_fire = snippet with only a continuous quantity variable;
          must_pass = snippet with a binary variable and the threshold m.

Rules of engagement:
- EVIDENCE: every slot value must cite a verbatim span of the problem text
  ("evidence": {"<slot>": "<exact quote from the problem>"}). If you cannot
  quote it, drop the rule - hallucinated bounds are the known failure mode.
- MANDATORY ATTEMPT: you MUST try to instantiate anchor_bound (both
  directions) and phantom_resource on EVERY problem. If you decline, you
  MUST state in "not_used" which required ingredient the text lacks
  (e.g. "no binding quantity clause", "no resource notion at all").
  "I did not think of it" is not an acceptable reason.
- CONSERVATIVE: instantiate a template only with clear textual evidence.
  2-4 solid rules beat 5 shaky ones. Never invent numbers.
- SELF-TEST: must_fire MUST trigger your rule, must_pass MUST NOT. Both
  are executed in a sandbox; failing rules are sent back for revision, so
  make the cases minimal, robust, and consistent with the slots.
- Optionally explain rejected templates: "not_used": {"<template>": "why"}.

Reply with EXACTLY one JSON object, no markdown fences:
{"params": {...},
 "rules": [{"template": "...", "slots": {...}, "evidence": {...},
            "why": "...",
            "must_fire": {"code": "...", "objective": null},
            "must_pass": {"code": "...", "objective": null}}],
 "not_used": {"<template>": "<reason>"}}

[PROBLEM]
%s
"""

REPAIR_PROMPT = """A rule instance you authored for the problem below FAILED its sandbox
self-calibration. Fix it (or drop it).

[PROBLEM]
%s

[FAILING RULE INSTANCE]
%s

[SANDBOX FAILURE]
%s

[PARAMS YOU EXTRACTED]
%s

Reminder of slot schemas:
- objective_range: {"lower": num/expr|null, "upper": num/expr|null}; cases
  vary only "objective" (code can be "").
- sense_direction: {"expected": "maximize"|"minimize"}; cases are code
  snippets with the opposite / expected sense word.
- constant_fidelity: {"name": str, "expected": num/expr}; must_fire snippet
  lacks the literal, must_pass contains it as a literal.
- phantom_resource: {"resource": str, "keywords": [str], "granted": num};
  must_fire assigns the resource above granted, must_pass does not.
- anchor_bound: {"direction": "lower"|"upper", "value": num/expr,
  "anchor_type": "binding_clause"|"trivial_policy", "evidence": str}; cases
  vary only "objective" (code can be "").
- conditional_moq: {"m": num/expr|null, "require_binary": bool}; must_fire
  has no binary variable, must_pass has one plus the threshold m.
Expressions may reference only the params names listed above.

Reply with EXACTLY one JSON object: the fixed rule with the same schema as
before (template, slots, evidence, why, must_fire, must_pass). If the rule
is unsalvageable, reply {"drop": true, "reason": "..."}. No markdown fences.
"""


def parse_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1:]
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(text[i:j + 1], strict=False)
    except json.JSONDecodeError:
        return None


def _case(case) -> dict:
    """Normalize an LLM-supplied self-test case to {"code": str, "objective": num|None}."""
    if not isinstance(case, dict):
        return {"code": "", "objective": None}
    obj = case.get("objective")
    if isinstance(obj, str):
        try:
            obj = float(obj)
        except ValueError:
            obj = None
    if isinstance(obj, bool) or not isinstance(obj, (int, float)):
        obj = None
    return {"code": str(case.get("code") or ""), "objective": obj}


def _normalize_rule(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    return {
        "template": raw.get("template"),
        "slots": raw.get("slots") if isinstance(raw.get("slots"), dict) else {},
        "evidence": raw.get("evidence"),
        "why": raw.get("why"),
        "must_fire": _case(raw.get("must_fire")),
        "must_pass": _case(raw.get("must_pass")),
    }


def calibrate(rule: dict, params: dict):
    """Render + run must-fire/must-pass in the sandbox.

    Returns (rendered_code|None, ok, detail)."""
    try:
        code = st.render(rule.get("template"), rule.get("slots") or {}, params)
    except st.TemplateError as e:
        return None, False, {"render_error": str(e)}
    detail, ok = {}, True
    for kind, expect in (("must_fire", True), ("must_pass", False)):
        case = _case(rule.get(kind))
        res = run_rule(code, case["code"], case["objective"], params)
        fired = res.get("status") == "ok" and bool(res.get("violation"))
        detail[kind] = {"status": res.get("status"), "fired": fired,
                        "violation": (res.get("violation") or "")[:200],
                        "err": (res.get("err") or "")[:200]}
        if res.get("status") != "ok" or fired != expect:
            ok = False
    return code, ok, detail


def failure_text(detail: dict) -> str:
    if detail.get("render_error"):
        return "render error: " + detail["render_error"]
    parts = []
    mf, mp = detail.get("must_fire") or {}, detail.get("must_pass") or {}
    if mf.get("status") != "ok":
        parts.append(f"must_fire case crashed the rule "
                     f"({mf.get('status')}: {mf.get('err')})")
    elif not mf.get("fired"):
        parts.append("must_fire case did NOT fire (rule returned None)")
    if mp.get("status") != "ok":
        parts.append(f"must_pass case crashed the rule "
                     f"({mp.get('status')}: {mp.get('err')})")
    elif mp.get("fired"):
        parts.append(f"must_pass case FIRED (false alarm): {mp.get('violation')}")
    return "; ".join(parts) or "unknown failure"


def author_rule(rule: dict, params: dict, question: str, ask):
    """Self-calibration loop for one rule instance.

    Returns (entry, status) where status is "calibrated" or "discarded"."""
    attempts = []
    current, code = rule, None
    for rnd in range(MAX_REVISIONS + 1):
        code, ok, detail = calibrate(current, params)
        attempts.append({"round": rnd, "ok": ok, "detail": detail,
                         "slots": current.get("slots")})
        if ok:
            break
        if rnd >= MAX_REVISIONS:
            break
        resp = ask(REPAIR_PROMPT % (question,
                                    json.dumps(current, ensure_ascii=False),
                                    failure_text(detail),
                                    json.dumps(params, ensure_ascii=False)))
        fixed = parse_json(resp["content"])
        if not isinstance(fixed, dict):
            attempts.append({"round": rnd, "repair_unparseable": True})
            continue
        if fixed.get("drop"):
            entry = {**current, "code": code, "attempts": attempts,
                     "revisions": len(attempts) - 1,
                     "discard_reason":
                         f"dropped_by_author: {str(fixed.get('reason'))[:200]}"}
            return entry, "discarded"
        merged = _normalize_rule(fixed)
        if merged is None:
            attempts.append({"round": rnd, "repair_unparseable": True})
            continue
        current = {k: merged[k] if merged.get(k) is not None else current.get(k)
                   for k in ("template", "slots", "evidence", "why",
                             "must_fire", "must_pass")}
    status = "calibrated" if attempts[-1]["ok"] else "discarded"
    entry = {**current, "code": code, "attempts": attempts,
             "revisions": len(attempts) - 1}
    if status == "discarded":
        entry["discard_reason"] = failure_text(attempts[-1]["detail"])
    return entry, status


def _sum_usage(calls: list) -> dict:
    tot = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for c in calls:
        for k in tot:
            v = (c.get("usage") or {}).get(k)
            if isinstance(v, (int, float)):
                tot[k] += int(v)
    return tot


def author_problem(d: dict, ask) -> dict:
    t0 = time.time()
    resp = ask(PROMPT % d["en_question"])
    if resp.get("finish_reason") == "length":
        resp = ask((PROMPT % d["en_question"]) +
                   "\nIMPORTANT: reply with COMPACT JSON, at most 4 rules, "
                   "short code snippets.", max_tokens=32768)
    parsed = parse_json(resp["content"])
    rec = {"id": d["id"], "difficulty": d["difficulty"]}
    if not parsed or not isinstance(parsed.get("rules"), list):
        rec.update(ok=False, stage1_finish_reason=resp.get("finish_reason"),
                   raw_head=(resp.get("content") or "")[:300])
        return rec
    params = parsed.get("params")
    params = params if isinstance(params, dict) else {}
    rec.update(ok=True, params=params, not_used=parsed.get("not_used"))
    calibrated, discarded = [], []
    for raw in (parsed.get("rules") or [])[:MAX_RULES]:
        rule = _normalize_rule(raw)
        if rule is None:
            continue
        entry, status = author_rule(rule, params, d["en_question"], ask)
        entry["status"] = status
        (calibrated if status == "calibrated" else discarded).append(entry)
    rec.update(rules=calibrated, discarded=discarded,
               n_calibrated=len(calibrated), n_discarded=len(discarded),
               n_revised=sum(1 for r in calibrated if r["revisions"] > 0),
               latency_s=round(time.time() - t0, 1))
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--skip-fixtures", action="store_true")
    args = ap.parse_args()
    k, K = (int(x) for x in args.shard.split("/"))

    if not args.skip_fixtures:
        fx = st.run_fixtures()
        if not fx["ok"]:
            print("template fixtures FAILED, aborting:",
              json.dumps(fx, ensure_ascii=False))
            sys.exit(1)

    data = json.loads(DATA.read_text())
    data = [d for i, d in enumerate(data) if i % K == k]
    if args.limit:
        data = data[: args.limit]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for d in data:
        out = OUT_DIR / f"d2rules_{d['id']}.json"
        if out.exists():
            print(f"[{d['id']}] exists, skip", flush=True)
            continue
        calls = []

        def ask(prompt, max_tokens=16384):
            resp = llm_mod.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=max_tokens, temperature=0.3,
                extra={"chat_template_kwargs": {"enable_thinking": False}})
            calls.append({"usage": resp.get("usage"),
                          "latency_s": round(resp.get("latency_s") or 0, 1),
                          "finish_reason": resp.get("finish_reason")})
            return resp

        try:
            rec = author_problem(d, ask)
        except Exception as e:
            rec = {"id": d["id"], "difficulty": d["difficulty"], "ok": False,
                   "error": f"{type(e).__name__}: {e}"}
            print(f"[{d['id']}] LLM error: {type(e).__name__}: {e}", flush=True)
        rec["calls"] = calls
        rec["usage"] = _sum_usage(calls)
        rec["n_llm_calls"] = len(calls)
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
        if rec.get("ok"):
            total = rec["n_calibrated"] + rec["n_discarded"]
            print(f"[{d['id']}] calibrated={rec['n_calibrated']} "
                  f"(revised={rec['n_revised']}) discarded={rec['n_discarded']} "
                  f"calib_pass={rec['n_calibrated']}/{total} "
                  f"llm_calls={len(calls)} {rec['latency_s']}s", flush=True)
        else:
            print(f"[{d['id']}] stage1 failed", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Offline analysis of ora_agent prediction/outcome pairs and trial summaries.

Stdlib only; never touches LLM credentials or the network.

Input: one or more trial "ora" directories (e.g.
runs/<job>/<task>__<id>/agent/ora/) containing trajectory.jsonl and
optionally predictions/*.json + outcomes/*.json. A directory without a
trajectory.jsonl is scanned recursively for nested trial dirs.

Pairing: predictions/<seq>_<action_hash>.json <-> outcomes/<seq>_<action_hash>.json
by (seq, action_hash) parsed from the filename.

Field reference (see ora_agent/predict.py, ora_agent/loop.py):
- prediction payload: {seq, action_hash, predictor_mode, input_hash, action,
  prediction: {will_succeed_prob, expected_outcome, likely_failure_modes,
  post_state_guess, confidence, unknown?, ...}}
- outcome payload: {seq, action_hash, prediction_file, action,
  outcome: {return_code, timed_out, error, stdout_tail, stderr_tail,
  classification}}  where classification in ok|nonzero_exit|timeout|exec_error
- trajectory events: run_meta/llm_request/llm_response/action/outcome/budget/
  finish; the final budget event carries status + cumulative usage.

Usage:
    python3 scripts/analyze_predictions.py <trial_dir> [<trial_dir>...] [--out report.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

SUCCESS_CLASS = "ok"
ALL_CLASSES = ("ok", "nonzero_exit", "timeout", "exec_error")
BUCKETS = ((0.0, 0.33, "0.00-0.33"), (0.34, 0.66, "0.34-0.66"),
           (0.67, 1.0, "0.67-1.00"))


def find_trial_dirs(paths: list[str]) -> list[Path]:
    trials = []
    for raw in paths:
        p = Path(raw)
        if (p / "trajectory.jsonl").is_file():
            trials.append(p)
        elif p.is_dir():
            for traj in sorted(p.rglob("trajectory.jsonl")):
                trials.append(traj.parent)
        else:
            print(f"[warn] not a trial dir, skipped: {p}", file=sys.stderr)
    # de-duplicate, keep order
    seen, out = set(), []
    for t in trials:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _parse_pair_filename(path: Path) -> tuple[int, str] | None:
    stem = path.stem  # <seq>_<hash>
    seq_s, _, h = stem.partition("_")
    if not seq_s.isdigit() or not h:
        return None
    return int(seq_s), h


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[warn] unreadable json {path}: {e}", file=sys.stderr)
        return None


def _bucket(prob: float) -> str:
    for lo, hi, name in BUCKETS:
        if lo <= prob <= hi:
            return name
    return BUCKETS[-1][2]


def trial_summary(traj_path: Path) -> dict:
    """Aggregate one trial's trajectory.jsonl."""
    n_llm_calls = 0
    n_actions = 0
    kind_counts: Counter = Counter()
    outcome_classes: Counter = Counter()
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    status = "unknown"
    task_id = None
    model = None
    for line in traj_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        task_id = task_id or e.get("task_id")
        model = model or e.get("model")
        ev = e.get("event")
        if ev == "llm_response" and not e.get("error"):
            n_llm_calls += 1
        elif ev == "action" and (e.get("action") or {}).get("tool") == "bash":
            n_actions += 1
            kind_counts[e["action"].get("action_kind", "other")] += 1
        elif ev == "outcome":
            outcome_classes[e.get("classification") or "?"] += 1
        elif ev == "budget" and e.get("kind") == "final":
            status = e.get("status", status)
            usage = e.get("usage") or usage
    return {
        "task_id": task_id, "model": model, "status": status,
        "n_llm_calls": n_llm_calls, "n_actions": n_actions,
        "usage": usage, "action_kind_counts": dict(kind_counts),
        "outcome_class_counts": dict(outcome_classes),
    }


def analyze_trial(trial_dir: Path) -> dict:
    """Full analysis of one trial dir. Missing predictions/ degrades to
    trajectory summary only (pairs empty)."""
    trial_dir = Path(trial_dir)
    result = {"trial_dir": str(trial_dir), "pairs": [], "unpaired": {
        "predictions_without_outcome": [], "outcomes_without_prediction": []}}
    traj = trial_dir / "trajectory.jsonl"
    result["summary"] = trial_summary(traj) if traj.is_file() else None

    pred_dir = trial_dir / "predictions"
    out_dir = trial_dir / "outcomes"
    if not pred_dir.is_dir():
        result["note"] = "no predictions/ dir: trajectory summary only"
        return result

    preds = {}
    for f in sorted(pred_dir.glob("*.json")):
        key = _parse_pair_filename(f)
        if key is None:
            print(f"[warn] bad prediction filename, skipped: {f.name}",
                  file=sys.stderr)
            continue
        payload = _load_json(f)
        if payload is not None:
            preds[key] = (f.name, payload)
    outs = {}
    if out_dir.is_dir():
        for f in sorted(out_dir.glob("*.json")):
            key = _parse_pair_filename(f)
            if key is None:
                print(f"[warn] bad outcome filename, skipped: {f.name}",
                      file=sys.stderr)
                continue
            payload = _load_json(f)
            if payload is not None:
                outs[key] = (f.name, payload)

    for key in sorted(set(preds) | set(outs)):
        seq, ahash = key
        if key not in outs:
            result["unpaired"]["predictions_without_outcome"].append(preds[key][0])
            continue
        if key not in preds:
            result["unpaired"]["outcomes_without_prediction"].append(outs[key][0])
            continue
        pred_payload = preds[key][1]
        out_payload = outs[key][1]
        prediction = pred_payload.get("prediction") or {}
        outcome = (out_payload.get("outcome") or {})
        classification = outcome.get("classification") or (
            "ok" if outcome.get("return_code") == 0 else "nonzero_exit")
        success = classification == SUCCESS_CLASS
        prob = prediction.get("will_succeed_prob")
        unknown = bool(prediction.get("unknown")) or not isinstance(
            prob, (int, float))
        if unknown:
            hit = None
        else:
            predicted_success = float(prob) >= 0.5
            hit = predicted_success == success
        result["pairs"].append({
            "task_id": (result["summary"] or {}).get("task_id"),
            "seq": seq,
            "action_hash": ahash,
            "action_kind": (pred_payload.get("action") or {}).get("action_kind"),
            "will_succeed_prob": prob if isinstance(prob, (int, float)) else None,
            "likely_failure_modes": prediction.get("likely_failure_modes"),
            "unknown": unknown,
            "success": success,
            "classification": classification,
            "failure_type": None if success else classification,
            "hit": hit,
            "prediction_file": f"predictions/{preds[key][0]}",
            "outcome_file": f"outcomes/{outs[key][0]}",
        })
    return result


def aggregate(trials: list[dict]) -> dict:
    pairs = [p for t in trials for p in t["pairs"]]
    known = [p for p in pairs if not p["unknown"]
             and p["will_succeed_prob"] is not None]
    agg: dict = {
        "n_trials": len(trials),
        "n_pairs": len(pairs),
        "n_unknown": len(pairs) - len(known),
        "unknown_rate": (len(pairs) - len(known)) / len(pairs) if pairs else None,
        "calibration": [],
        "by_action_kind": [],
        "overall": None,
        "optimistic_but_failed": [],
        "pessimistic_but_succeeded": [],
    }
    if not pairs:
        return agg

    n_success = sum(1 for p in pairs if p["success"])
    hits = [p for p in known if p["hit"] is not None]
    agg["overall"] = {
        "actual_success_rate": n_success / len(pairs),
        "mean_predicted_prob": (sum(p["will_succeed_prob"] for p in known)
                                / len(known)) if known else None,
        "hit_rate": (sum(1 for p in hits if p["hit"]) / len(hits)) if hits else None,
    }

    for lo, hi, name in BUCKETS:
        group = [p for p in known if lo <= p["will_succeed_prob"] <= hi]
        if not group:
            continue
        agg["calibration"].append({
            "bucket": name,
            "n": len(group),
            "mean_predicted_prob": sum(p["will_succeed_prob"] for p in group) / len(group),
            "actual_success_rate": sum(1 for p in group if p["success"]) / len(group),
        })

    kinds = sorted({p["action_kind"] for p in pairs})
    for kind in kinds:
        group = [p for p in pairs if p["action_kind"] == kind]
        gk = [p for p in group if p["hit"] is not None]
        agg["by_action_kind"].append({
            "action_kind": kind,
            "n": len(group),
            "actual_success_rate": sum(1 for p in group if p["success"]) / len(group),
            "hit_rate": (sum(1 for p in gk if p["hit"]) / len(gk)) if gk else None,
        })

    # Selection-bias material: high-confidence misses in both directions.
    agg["optimistic_but_failed"] = [
        p for p in known if p["will_succeed_prob"] >= 0.67 and not p["success"]]
    agg["pessimistic_but_succeeded"] = [
        p for p in known if p["will_succeed_prob"] <= 0.33 and p["success"]]
    return agg


def _fmt_pct(x) -> str:
    return "  n/a " if x is None else f"{x * 100:5.1f}%"


def render_text(trials: list[dict], agg: dict) -> str:
    lines = []
    lines.append("=" * 72)
    lines.append("TRIAL SUMMARIES")
    lines.append("=" * 72)
    for t in trials:
        s = t.get("summary")
        if not s:
            lines.append(f"{t['trial_dir']}: no trajectory.jsonl")
            continue
        u = s["usage"]
        lines.append(
            f"{s['task_id']}  status={s['status']}  llm_calls={s['n_llm_calls']}  "
            f"actions={s['n_actions']}  tokens(p/c/t)="
            f"{u['prompt_tokens']}/{u['completion_tokens']}/{u['total_tokens']}")
        if s["action_kind_counts"]:
            kinds = " ".join(f"{k}:{v}" for k, v in sorted(s["action_kind_counts"].items()))
            lines.append(f"    action_kinds: {kinds}")
        if t.get("note"):
            lines.append(f"    [{t['note']}]")
        unpaired = t["unpaired"]
        for k, v in unpaired.items():
            if v:
                lines.append(f"    [warn] {k}: {len(v)} ({', '.join(v[:5])})")

    lines.append("")
    lines.append("=" * 72)
    lines.append(f"PREDICTION PAIRS ({agg['n_pairs']} paired, "
                 f"{agg['n_unknown']} unknown, unknown_rate="
                 f"{_fmt_pct(agg['unknown_rate']).strip()})")
    lines.append("=" * 72)
    if not agg["n_pairs"]:
        lines.append("(no prediction/outcome pairs found)")
        return "\n".join(lines)

    for t in trials:
        for p in t["pairs"]:
            prob = "unknown" if p["unknown"] else f"{p['will_succeed_prob']:.2f}"
            hit = "n/a" if p["hit"] is None else ("HIT" if p["hit"] else "MISS")
            fail = p["failure_type"] or "-"
            lines.append(
                f"{p['task_id']} seq={p['seq']:>3} kind={p['action_kind']:<8} "
                f"p={prob:<7} actual={'OK ' if p['success'] else 'FAIL':<4} "
                f"failure={fail:<13} {hit}")
            if p["likely_failure_modes"]:
                modes = "; ".join(str(m) for m in p["likely_failure_modes"][:3])
                lines.append(f"    predicted failure modes: {modes}")

    if agg["overall"]:
        o = agg["overall"]
        lines.append("")
        lines.append(f"OVERALL: actual_success_rate={_fmt_pct(o['actual_success_rate'])} "
                     f"mean_predicted_prob={_fmt_pct(o['mean_predicted_prob'])} "
                     f"hit_rate={_fmt_pct(o['hit_rate'])}")
    if agg["calibration"]:
        lines.append("")
        lines.append("CALIBRATION (predicted prob bucket -> actual success rate)")
        for c in agg["calibration"]:
            lines.append(f"  {c['bucket']}  n={c['n']:>3}  "
                         f"pred={_fmt_pct(c['mean_predicted_prob'])}  "
                         f"actual={_fmt_pct(c['actual_success_rate'])}")
    if agg["by_action_kind"]:
        lines.append("")
        lines.append("BY ACTION KIND")
        for r in agg["by_action_kind"]:
            lines.append(f"  {r['action_kind']:<9} n={r['n']:>3}  "
                         f"actual={_fmt_pct(r['actual_success_rate'])}  "
                         f"hit_rate={_fmt_pct(r['hit_rate'])}")
    for title, key in (("OPTIMISTIC BUT FAILED (p>=0.67, actual FAIL)",
                        "optimistic_but_failed"),
                       ("PESSIMISTIC BUT SUCCEEDED (p<=0.33, actual OK)",
                        "pessimistic_but_succeeded")):
        lines.append("")
        lines.append(f"{title}: {len(agg[key])}")
        for p in agg[key]:
            lines.append(f"  {p['task_id']} seq={p['seq']} kind={p['action_kind']} "
                         f"p={p['will_succeed_prob']:.2f} -> {p['classification']} "
                         f"({p['prediction_file']} / {p['outcome_file']})")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("trial_dirs", nargs="+",
                    help="trial ora dirs, or parent dirs to scan recursively")
    ap.add_argument("--out", help="write full JSON report to this path")
    args = ap.parse_args(argv)

    trial_dirs = find_trial_dirs(args.trial_dirs)
    if not trial_dirs:
        print("no trial dirs found", file=sys.stderr)
        return 1
    trials = [analyze_trial(d) for d in trial_dirs]
    agg = aggregate(trials)
    print(render_text(trials, agg))
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"trials": trials, "aggregate": agg},
                                       ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        print(f"\nJSON report written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

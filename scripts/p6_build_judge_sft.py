"""P6: assemble judge SFT v3 data from rejection-sampled reasoning traces.

Input : work/judge_data/rs_traces.jsonl  (from scripts/p5_judge_rs.py)
Output: work/judge_data/sft_v3/train_v3.jsonl  (+ stats_v3.json)

Record shape matches the J1 pipeline ({key, wrong, weight, system, user,
target}) so the existing remote training/eval tooling keeps working, with one
crucial difference: target is the full reasoning + VERDICT line produced by the
teacher (thinking ON), not a bare JSON verdict. J1/J1.1 trained verdict-only
targets and the verdict token collapsed out of distribution; here the model
learns to reason before it decides.

Only traces whose verdict matches the witness-derived label are kept
(rejection sampling). Records with zero matching traces surface in stats as
"unmatched" — they are the classes the teacher cannot yet see; do NOT
fabricate teacher-forced traces for them.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JUDGE_DATA = ROOT / "work" / "judge_data" / "judge_v2.jsonl"
TRACES = ROOT / "work" / "judge_data" / "rs_traces.jsonl"
SCENARIOS = ROOT / "data" / "m1_retailopt" / "f1f4_all100.jsonl"
OUT_DIR = ROOT / "work" / "judge_data" / "sft_v3"

# must stay byte-identical to the prompt used at sampling time
import sys
sys.path.insert(0, str(ROOT))
from scripts.p5_judge_rs import JUDGE_PROMPT  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-per-record", type=int, default=2)
    args = ap.parse_args()

    records = {(r["scenario_id"], r.get("mutant"), r.get("seed_tag")): r
               for r in map(json.loads, JUDGE_DATA.read_text().splitlines())}
    prompts = {json.loads(l)["scenario_id"]: json.loads(l).get("prompt_full") or ""
               for l in SCENARIOS.read_text().splitlines()}

    traces = [json.loads(l) for l in TRACES.read_text().splitlines()]
    matched = defaultdict(list)
    for t in traces:
        if t.get("verdict_match") and t.get("finish_reason") == "stop" and t.get("content"):
            matched[(t["scenario_id"], t.get("mutant"), t.get("seed_tag"))].append(t)

    out_rows = []
    for key, ts in matched.items():
        ts = sorted(ts, key=lambda t: len(t["content"]))[: args.keep_per_record]
        rec = records[key]
        user = JUDGE_PROMPT.format(
            prompt=prompts.get(rec["scenario_id"], "")[:4000],
            data_digest=json.dumps(rec["data_digest"], ensure_ascii=False),
            code=rec["code"][:4000],
            solution_digest=json.dumps(rec["solution_digest"], ensure_ascii=False))
        for i, t in enumerate(ts):
            out_rows.append({
                "key": "|".join(str(x) for x in key) + f"|rs{i}",
                "wrong": rec["label"] == "wrong",
                "weight": 1.0,
                "system": "",
                "user": user,
                "target": t["content"].strip(),
                "teacher_usage": t.get("usage") or {},
            })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "train_v3.jsonl", "w") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    per_class = Counter()
    unmatched = Counter()
    for key, rec in records.items():
        cls = (rec.get("mutant") or "correct", rec["label"])
        if key in matched:
            per_class[cls] += 1
        elif rec["split"] == "train":
            unmatched[cls] += 1
    stats = {
        "sft_rows": len(out_rows),
        "records_with_traces": {str(k): v for k, v in sorted(per_class.items())},
        "train_records_unmatched": {str(k): v for k, v in sorted(unmatched.items())},
        "target_len_chars_mean": (sum(len(r["target"]) for r in out_rows)
                                  / max(len(out_rows), 1)),
    }
    (OUT_DIR / "stats_v3.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()

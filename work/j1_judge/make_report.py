#!/usr/bin/env python3
"""J1 final report: aggregate train log + eval metrics into README §5 text.

Reads (local copies under work/j1_judge/):
  remote_ref/train_metrics.jsonl     (downloaded from remote logs/)
  remote_ref/eval_*.metrics.json     (downloaded eval outputs)
  remote_ref/eval_*.predictions.jsonl
Writes report_section.txt with training curve summary + comparison table.
"""
import json
import sys
from pathlib import Path

WD = Path("/home/hewj13/wm/ora/work/j1_judge/remote_ref")

BASELINES = [
    # name, AUC, det@0.5, fp@0.5, note
    ("Open-Jev off-the-shelf (P1')", "0.662", "1.6% (1/61)", "0.0% (0/179)",
     "AUC recomputed from runs/industryor/industryor_judge_openjev.jsonl"),
    ("D2 rule gate", "—", "9.8% (6/61)", "5.6% (10/177*)",
     "runs/d2_authoring/matrix.json; *2 cells had no rule (177 denom)"),
    ("A1 self-consistency", "—", "16.4% (10/61)", "5.0% (9/179)",
     "runs/d1_authoring/selfconsistency.json; 55/100 problems no-vote"),
]


def train_summary():
    rows = [json.loads(l) for l in (WD / "train_metrics.jsonl").open()]
    steps = [r for r in rows if r.get("event") == "step"]
    saves = [r for r in rows if r.get("event") == "adapter_saved"]
    done = [r for r in rows if r.get("event") == "done"]
    out = []
    out.append(f"steps total: {len(steps)}, epochs completed: {len(saves)}")
    if done:
        out.append(f"total train time: {done[0]['total_s'] / 3600:.2f} h; "
                   f"peak mem {done[0]['peak_mem_mb']}")
    for ep in sorted(set(s['epoch'] for s in steps)):
        ls = [s['loss'] for s in steps if s['epoch'] == ep]
        n = len(ls)
        seg = [(f"steps {i + 1}-{min(i + 40, n)}",
                round(sum(ls[i:i + 40]) / len(ls[i:i + 40]), 3))
               for i in range(0, n, 40)]
        out.append(f"epoch {ep + 1}: n={n}, mean loss by segment: " +
                   ", ".join(f"{a}={b}" for a, b in seg))
    st = [s['step_s'] for s in steps]
    out.append(f"step_s mean {sum(st) / len(st):.1f}")
    return "\n".join(out)


def eval_line(tag):
    m = json.load((WD / f"eval_{tag}.metrics.json").open())
    t = m["t05_score"]
    g = m["gen_verdict"]
    # NOTE: rates() in eval_j1.py has a duplicate "fp" key — the stored "fp"
    # is the raw COUNT, not the rate. Recompute rates here.
    t_fp_rate = t["fp"] / t["n_neg"]
    g_fp_rate = g["fp"] / g["n_neg"]
    return (m, f"J1 judge ({tag}): AUC {m['auc_pfail']} | "
               f"t=0.5 det {t['det'] * 100:.1f}% ({t['tp']}/{t['n_pos']}) "
               f"FP {t_fp_rate * 100:.1f}% ({t['fp']}/{t['n_neg']}) | "
               f"gen-parse det {g['det'] * 100:.1f}% FP {g_fp_rate * 100:.1f}% "
               f"unparsed {m['unparsed']}")


def main(tags):
    print("== training == ")
    print(train_summary())
    print()
    print("== IndustryOR 240 (61 phantom / 179 correct) ==")
    tbl = []
    for tag in tags:
        try:
            m, line = eval_line(tag)
            fp_rate = m["t05_score"]["fp"] / m["t05_score"]["n_neg"]
            tbl.append((f"J1 judge ({tag})",
                        f"{m['auc_pfail']}",
                        f"{m['t05_score']['det'] * 100:.1f}%",
                        f"{fp_rate * 100:.1f}%", ""))
            print(line)
            if "per_arm" in m:
                for arm, a in m["per_arm"].items():
                    print(f"    arm {arm}: n={a['n']} det={a['det']} fp={a['fp']} auc={a['auc']}")
        except FileNotFoundError:
            print(f"(missing eval_{tag}.metrics.json)")
    print()
    print("== comparison table (det/FP at t=0.5) ==")
    print(f"{'method':<34} {'AUC':<7} {'det':<14} {'FP':<14}")
    for name, auc, det, fp, _ in [tbl_row for tbl_row in tbl] + []:
        pass
    for name, auc, det, fp, note in [(t[0], t[1], t[2], t[3], t[4]) for t in tbl] + BASELINES:
        print(f"{name:<34} {auc:<7} {det:<14} {fp:<14} {note}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["test_ep1"])

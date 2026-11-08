#!/usr/bin/env python3
"""Fetch all judge-v3/v4 remote eval artifacts to local work/judge_data/.

Run after the remote chain (eval_gen.py -> train_j1_v4.py -> eval_chain_v4b.sh)
has finished. Missing remote files are skipped with a warning.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MF = "/home/hewj13/mf_tools/mf_download.py"
PY = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"

FILES = [
    ("hewj13/j3_judge/logs/gen_eval_industryor.jsonl",
     "work/judge_data/gen_eval_industryor.jsonl"),
    ("hewj13/j4_judge/logs/v4_eval_f5f8_ep1.jsonl",
     "work/judge_data/v4_eval_f5f8_ep1.jsonl"),
    ("hewj13/j4_judge/logs/v4_eval_f5f8_ep2.jsonl",
     "work/judge_data/v4_eval_f5f8_ep2.jsonl"),
    ("hewj13/j4_judge/logs/v4_eval_f5f8_ep3.jsonl",
     "work/judge_data/v4_eval_f5f8_ep3.jsonl"),
    ("hewj13/j4_judge/logs/v4_eval_ior.jsonl",
     "work/judge_data/v4_eval_ior.jsonl"),
    ("hewj13/j4_judge/logs/best_ep.txt",
     "work/judge_data/v4_logs/best_ep.txt"),
    ("hewj13/j4_judge/logs/eval_chain.log",
     "work/judge_data/v4_logs/eval_chain.log"),
    ("hewj13/j4_judge/logs/chain.log",
     "work/judge_data/v4_logs/chain.log"),
    ("hewj13/j4_judge/logs/train_v4.out",
     "work/judge_data/v4_logs/train_v4.out"),
]


def main() -> int:
    ok, fail = 0, 0
    for remote, local in FILES:
        dst = ROOT / local
        dst.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([PY, MF, remote, str(dst)],
                           capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            ok += 1
            print("OK ", remote)
        else:
            fail += 1
            print("MISS", remote, (r.stderr or r.stdout).strip().splitlines()[-1:]
                  if (r.stderr or r.stdout).strip() else "")
    print(f"\nfetched {ok}, missing {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

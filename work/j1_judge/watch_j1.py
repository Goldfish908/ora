#!/usr/bin/env python3
"""Watch remote J1 training until done/dead; poll every 5 min.

Uses a file-based status channel (mf_exec echo is unreliable):
remote writes logs/status.txt, we download it via j1_io and parse.
"""
import json
import os
import subprocess
import sys
import time

P = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"
ENV = {**os.environ, "MF_TERM": "6"}
MFT = "/home/hewj13/mf_tools"
WD = "/home/hewj13/wm/ora/work/j1_judge"
REMOTE_CMD = ("{ tail -1 /dfs/data/hewj13/j1_judge/logs/train_metrics.jsonl; "
              "pgrep -fc train_j1.py; "
              "ls /dfs/data/hewj13/j1_judge/ | grep adapter; "
              "} > /dfs/data/hewj13/j1_judge/logs/status.txt 2>&1")
t0 = time.time()

while True:
    try:
        subprocess.run([P, "mf_exec.py", REMOTE_CMD], cwd=MFT, env=ENV,
                       capture_output=True, text=True, timeout=120)
        subprocess.run([P, "j1_io.py", "download", "j1_judge/logs/status.txt",
                        f"{WD}/remote_ref/status.txt"], cwd=WD,
                       capture_output=True, text=True, timeout=120)
        lines = [l for l in open(f"{WD}/remote_ref/status.txt")
                 .read().splitlines() if l.strip()]
        last = lines[0] if lines else ""
        pid_cnt = lines[1].strip() if len(lines) > 1 else "0"
        adapters = ",".join(lines[2:])
        status = {"elapsed_min": round((time.time() - t0) / 60, 1),
                  "last": last[:300], "train_procs": pid_cnt,
                  "adapters": adapters}
        print(status, flush=True)
        with open(f"{WD}/watch_status.json", "w") as f:
            json.dump(status, f)
        if '"event": "done"' in last:
            print("TRAINING_DONE", flush=True)
            sys.exit(0)
        if pid_cnt == "0":
            print("TRAINING_PROCESS_GONE", flush=True)
            sys.exit(2)
    except Exception as e:
        print(f"poll error: {e}", flush=True)
    time.sleep(300)

#!/usr/bin/env python3
"""Wait for epoch-1 adapter_saved in remote train log, then stop the trainer.

Polls every 2 min via file channel. On adapter_saved(epoch=1): pkill trainer
(epoch 2 skipped: 316 samples, loss plateaued ~0.2; ep1 is in-spec), exit 0.
Exits 2 if trainer dies before ep1 save.
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
REMOTE_CMD = ("{ grep -c 'adapter_saved.*\"epoch\": 1' "
              "/dfs/data/hewj13/j1_judge/logs/train_metrics.jsonl; "
              "pgrep -fc train_j1.py; "
              "tail -1 /dfs/data/hewj13/j1_judge/logs/train_metrics.jsonl; "
              "} > /dfs/data/hewj13/j1_judge/logs/ep1_status.txt 2>&1")
t0 = time.time()

while True:
    try:
        subprocess.run([P, "mf_exec.py", REMOTE_CMD], cwd=MFT, env=ENV,
                       capture_output=True, text=True, timeout=120)
        subprocess.run([P, "j1_io.py", "download", "j1_judge/logs/ep1_status.txt",
                        f"{WD}/remote_ref/ep1_status.txt"], cwd=WD,
                       capture_output=True, text=True, timeout=120)
        lines = [l for l in open(f"{WD}/remote_ref/ep1_status.txt")
                 .read().splitlines() if l.strip()]
        saved = lines[0].strip() if lines else "0"
        procs = lines[1].strip() if len(lines) > 1 else "0"
        last = lines[2][:200] if len(lines) > 2 else ""
        print({"elapsed_min": round((time.time() - t0) / 60, 1),
               "ep1_saved": saved, "procs": procs, "last": last}, flush=True)
        if saved != "0":
            subprocess.run([P, "mf_exec.py", "pkill -f train_j1.py; sleep 2; "
                            "pgrep -fc train_j1.py; "
                            "ls /dfs/data/hewj13/j1_judge/adapter_ep1/"],
                           cwd=MFT, env=ENV, capture_output=True, text=True,
                           timeout=120)
            print("EP1_SAVED_TRAINER_STOPPED", flush=True)
            sys.exit(0)
        if procs == "0":
            print("TRAINER_GONE_BEFORE_EP1", flush=True)
            sys.exit(2)
    except Exception as e:
        print(f"poll error: {e}", flush=True)
    time.sleep(120)

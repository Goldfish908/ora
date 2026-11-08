#!/usr/bin/env python3
"""Eval pipeline driver: wait for adapter_ep1 + trainer exit, launch evals
remotely, wait for metrics files, download everything.

Remote runs (sequential, nohup):
  eval_j1.py --adapter adapter_ep1 --data test.jsonl       --out logs/eval_test_ep1
  eval_j1.py --adapter adapter_ep1 --data train_eval.jsonl --out logs/eval_train_ep1 --no-gen
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
J1 = "/dfs/data/hewj13/j1_judge"
t0 = time.time()


def remote(cmd, timeout=120):
    return subprocess.run([P, "mf_exec.py", cmd], cwd=MFT, env=ENV,
                          capture_output=True, text=True, timeout=timeout)


def dl(remote_rel, local):
    return subprocess.run([P, "j1_io.py", "download", remote_rel, local],
                          cwd=WD, capture_output=True, text=True, timeout=180)


def status_file(cmd, name):
    for attempt in range(4):
        remote(f"{{ {cmd} }} > {J1}/logs/{name} 2>&1")
        dl(f"j1_judge/logs/{name}", f"{WD}/remote_ref/{name}")
        try:
            return [l for l in open(f"{WD}/remote_ref/{name}").read().splitlines()
                    if l.strip()]
        except FileNotFoundError:
            time.sleep(10)
    raise RuntimeError(f"status channel broken for {name}")


# phase 1: wait for adapter_ep1 saved and trainer gone
while True:
    lines = status_file(
        f"test -f {J1}/adapter_ep1/adapter_model.safetensors && echo ADAPTER_OK; "
        f"pgrep -fc train_j1.py", "eval_status.txt")
    adapter_ok = any("ADAPTER_OK" in l for l in lines)
    procs = next((l.strip() for l in lines if l.strip().isdigit()), "?")
    print({"phase": 1, "elapsed_min": round((time.time() - t0) / 60, 1),
           "adapter": adapter_ok, "trainer_procs": procs}, flush=True)
    if adapter_ok and procs == "0":
        break
    if not adapter_ok and procs == "0":
        print("TRAINER_GONE_NO_ADAPTER", flush=True)
        sys.exit(2)
    time.sleep(120)

# phase 2: launch evals
remote(f"cd {J1} && nohup bash -c 'python3 eval_j1.py --adapter adapter_ep1 "
       f"--data test.jsonl --out logs/eval_test_ep1 && python3 eval_j1.py "
       f"--adapter adapter_ep1 --data train_eval.jsonl --out logs/eval_train_ep1 "
       f"--no-gen' > logs/eval_run.out 2>&1 & echo EVAL_LAUNCHED", timeout=60)
print("EVAL_LAUNCHED", flush=True)

# phase 3: wait for both metrics files (or eval process gone)
while True:
    lines = status_file(
        f"ls {J1}/logs/ | grep -c 'eval_.*metrics.json'; pgrep -fc eval_j1.py; "
        f"tail -2 {J1}/logs/eval_run.out", "eval_status.txt")
    n_metrics = next((int(l) for l in lines if l.strip().isdigit()), 0)
    procs = next((l.strip() for l in lines[1:] if l.strip().isdigit()), "?")
    print({"phase": 3, "elapsed_min": round((time.time() - t0) / 60, 1),
           "metrics_files": n_metrics, "eval_procs": procs,
           "tail": lines[-1][:160] if lines else ""}, flush=True)
    if n_metrics >= 2:
        break
    if procs == "0" and n_metrics < 2:
        print("EVAL_DIED", flush=True)
        sys.exit(3)
    time.sleep(180)

# phase 4: download artifacts
for f in ["logs/train_metrics.jsonl",
          "logs/eval_test_ep1.metrics.json", "logs/eval_test_ep1.predictions.jsonl",
          "logs/eval_test_ep1.log.jsonl",
          "logs/eval_train_ep1.metrics.json",
          "logs/eval_train_ep1.predictions.jsonl"]:
    r = dl(f"j1_judge/{f}", f"{WD}/remote_ref/{os.path.basename(f)}")
    print(r.stdout.strip() or r.stderr.strip()[:200], flush=True)
print("EVAL_ALL_DONE", flush=True)

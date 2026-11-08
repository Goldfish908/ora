#!/usr/bin/env python3
"""J1 supervisor v3 — single writer on terminal MF_TERM=7, self-healing.

- Every remote command is prefixed with Ctrl-C (clears wedged continuations).
- Decisions are based on REMOTE FILE EXISTENCE (adapter_ep1/adapter_model.safetensors),
  never on parsed log text; kill requires two consecutive ADAPTER_READY polls.
- After trainer kill: launch evals (test with generation, train score-only),
  wait for both metrics files, download artifacts, exit 0.
"""
import os
import subprocess
import sys
import time

P = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"
ENV = {**os.environ, "MF_TERM": "7"}
MFT = "/home/hewj13/mf_tools"
WD = "/home/hewj13/wm/ora/work/j1_judge"
J1 = "/dfs/data/hewj13/j1_judge"
t0 = time.time()


def remote(cmd, timeout=150):
    # Ctrl-C as a SEPARATE call first (tty flushes input after ^C, so a
    # combined write would eat the real command), then the command itself.
    subprocess.run([P, "mf_exec.py", "\x03"], cwd=MFT, env=ENV,
                   capture_output=True, text=True, timeout=30)
    time.sleep(1)
    r = subprocess.run([P, "mf_exec.py", cmd], cwd=MFT, env=ENV,
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode


def dl(remote_rel, local):
    r = subprocess.run([P, "j1_io.py", "download", remote_rel, local],
                       cwd=WD, capture_output=True, text=True, timeout=180)
    return r.returncode


def status(cmd, name):
    """Run remote cmd -> J1/logs/<name>, download, return lines or None."""
    for _ in range(3):
        remote(f"{{ {cmd} ; }} > {J1}/logs/{name} 2>&1")
        if dl(f"j1_judge/logs/{name}", f"{WD}/remote_ref/{name}") == 0:
            try:
                return [l for l in open(f"{WD}/remote_ref/{name}")
                        .read().splitlines() if l.strip()]
            except FileNotFoundError:
                pass
        time.sleep(15)
    return None


def log(d):
    d["elapsed_min"] = round((time.time() - t0) / 60, 1)
    print(d, flush=True)
    with open(f"{WD}/supervisor3.log", "a") as f:
        f.write(repr(d) + "\n")


ready_streak = 0
killed = False
eval_launched = False
while True:
    try:
        if not eval_launched:
            lines = status(f"test -f {J1}/adapter_ep1/adapter_model.safetensors && echo ADAPTER_READY; "
                           f"pgrep -fc train_j1.py; "
                           f"tail -n 1 {J1}/logs/train_metrics.jsonl",
                           "sup3.txt")
            if lines is None:
                log({"warn": "channel_fail"}); time.sleep(60); continue
            adapter_ready = "ADAPTER_READY" in lines
            procs = next((l for l in lines if l.isdigit()), "?")
            last = lines[-1][:200]
            log({"ph": "A", "adapter": adapter_ready, "procs": procs, "last": last})
            if adapter_ready and not killed:
                ready_streak += 1
                if ready_streak >= 2:
                    remote("pkill -f train_j1.py")
                    time.sleep(5)
                    chk = status(f"pgrep -fc train_j1.py; ls {J1}/adapter_ep1/", "sup3_kill.txt")
                    log({"ph": "A", "action": "kill", "chk": chk})
                    killed = True
                    remote(f"cd {J1} && nohup bash -c 'python3 eval_j1.py --adapter adapter_ep1 "
                           f"--data test.jsonl --out logs/eval_test_ep1 && python3 eval_j1.py "
                           f"--adapter adapter_ep1 --data train_eval.jsonl "
                           f"--out logs/eval_train_ep1 --no-gen' > logs/eval_run.out 2>&1 &")
                    eval_launched = True
                    time.sleep(30)
                    continue
            elif not adapter_ready:
                ready_streak = 0
                if procs == "0":
                    log({"err": "TRAINER_GONE_NO_ADAPTER"})
                    sys.exit(2)
            # if adapter ready but trainer already gone (edge), still proceed
            if adapter_ready and killed:
                eval_launched = True
            time.sleep(120 if not adapter_ready else 30)
        else:
            lines = status(f"ls {J1}/logs/eval_test_ep1.metrics.json {J1}/logs/eval_train_ep1.metrics.json; "
                           f"pgrep -fc eval_j1.py; "
                           f"tail -n 1 {J1}/logs/eval_run.out", "sup3_eval.txt")
            if lines is None:
                log({"warn": "channel_fail"}); time.sleep(90); continue
            have_test = any("eval_test_ep1.metrics.json" in l and "cannot" not in l for l in lines)
            have_train = any("eval_train_ep1.metrics.json" in l and "cannot" not in l for l in lines)
            procs = next((l for l in lines if l.isdigit()), "?")
            log({"ph": "B", "test": have_test, "train": have_train, "procs": procs,
                 "tail": lines[-1][:200]})
            if have_test and have_train:
                break
            if procs == "0" and not (have_test and have_train):
                log({"err": "EVAL_DIED"})
                sys.exit(3)
            time.sleep(150)
    except Exception as e:
        log({"err": str(e)[:300]})
        time.sleep(60)

for f in ["logs/train_metrics.jsonl",
          "logs/eval_test_ep1.metrics.json", "logs/eval_test_ep1.predictions.jsonl",
          "logs/eval_test_ep1.log.jsonl",
          "logs/eval_train_ep1.metrics.json", "logs/eval_train_ep1.predictions.jsonl",
          "logs/eval_run.out"]:
    rc = dl(f"j1_judge/{f}", f"{WD}/remote_ref/{os.path.basename(f)}")
    log({"dl": f, "rc": rc})
print("EVAL_ALL_DONE", flush=True)

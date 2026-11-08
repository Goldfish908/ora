#!/usr/bin/env python3
"""J1 supervisor — the ONLY user of terminal MF_TERM=7 (single-writer discipline).

Phase A: poll every 150s until adapter_ep1 saved (adapter_saved epoch 1 in log),
         then pkill the trainer (epoch 2 skipped, ep1 in-spec) and launch evals.
Phase B: poll every 180s until both metrics files exist, then download all
         artifacts and exit 0. Exit 2/3 on abnormal states.
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
    # leading Ctrl-C clears any wedged continuation line before the real command
    r = subprocess.run([P, "mf_exec.py", "\x03" + cmd], cwd=MFT, env=ENV,
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode


def dl(remote_rel, local):
    r = subprocess.run([P, "j1_io.py", "download", remote_rel, local],
                       cwd=WD, capture_output=True, text=True, timeout=180)
    return r.returncode


def status(cmd, name):
    for _ in range(4):
        remote(f"{{ {cmd} }} > {J1}/logs/{name} 2>&1")
        if dl(f"j1_judge/logs/{name}", f"{WD}/remote_ref/{name}") == 0:
            try:
                return [l for l in open(f"{WD}/remote_ref/{name}")
                        .read().splitlines() if l.strip()]
            except FileNotFoundError:
                pass
        time.sleep(15)
    raise RuntimeError(f"status channel broken: {name}")


def log(d):
    d["elapsed_min"] = round((time.time() - t0) / 60, 1)
    print(d, flush=True)
    with open(f"{WD}/supervisor.log", "a") as f:
        f.write(repr(d) + "\n")


phase = "A"
eval_launched = False
while True:
    try:
        if phase == "A":
            lines = status(f"grep -c 'adapter_saved.*\"epoch\": 1' {J1}/logs/train_metrics.jsonl; "
                           f"pgrep -fc train_j1.py; "
                           f"tail -1 {J1}/logs/train_metrics.jsonl",
                           "sup_status.txt")
            saved = lines[0].strip() if lines else "0"
            procs = lines[1].strip() if len(lines) > 1 else "?"
            last = lines[2][:220] if len(lines) > 2 else ""
            log({"phase": "A", "ep1_saved": saved, "procs": procs, "last": last})
            if saved != "0":
                remote("pkill -f train_j1.py")
                time.sleep(5)
                chk = status(f"pgrep -fc train_j1.py; ls {J1}/adapter_ep1/", "sup_kill.txt")
                log({"phase": "A", "action": "killed", "chk": chk})
                remote(f"cd {J1} && nohup bash -c 'python3 eval_j1.py --adapter adapter_ep1 "
                       f"--data test.jsonl --out logs/eval_test_ep1 && python3 eval_j1.py "
                       f"--adapter adapter_ep1 --data train_eval.jsonl "
                       f"--out logs/eval_train_ep1 --no-gen' > logs/eval_run.out 2>&1 &")
                eval_launched = True
                phase = "B"
                time.sleep(30)
                continue
            if procs == "0":
                log({"phase": "A", "error": "TRAINER_GONE_NO_ADAPTER"})
                sys.exit(2)
            time.sleep(150)
        else:
            lines = status(f"ls {J1}/logs/ | grep -c 'eval_.*metrics.json'; "
                           f"pgrep -fc eval_j1.py; "
                           f"tail -1 {J1}/logs/eval_run.out", "sup_eval.txt")
            n_metrics = int(lines[0]) if lines and lines[0].isdigit() else 0
            procs = lines[1].strip() if len(lines) > 1 else "?"
            log({"phase": "B", "metrics": n_metrics, "eval_procs": procs,
                 "tail": lines[-1][:200] if lines else ""})
            if n_metrics >= 2:
                break
            if procs == "0" and n_metrics < 2:
                log({"phase": "B", "error": "EVAL_DIED"})
                sys.exit(3)
            time.sleep(180)
    except Exception as e:
        log({"error": str(e)[:300]})
        time.sleep(60)

for f in ["logs/train_metrics.jsonl",
          "logs/eval_test_ep1.metrics.json", "logs/eval_test_ep1.predictions.jsonl",
          "logs/eval_test_ep1.log.jsonl",
          "logs/eval_train_ep1.metrics.json", "logs/eval_train_ep1.predictions.jsonl"]:
    rc = dl(f"j1_judge/{f}", f"{WD}/remote_ref/{os.path.basename(f)}")
    log({"dl": f, "rc": rc})
print("EVAL_ALL_DONE", flush=True)

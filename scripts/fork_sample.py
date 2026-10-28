#!/usr/bin/env python3
"""Fork sampling: execute K candidate actions from the same replayed state.

Stdlib only; never calls an LLM — candidate actions are supplied externally.

Given a real ora_agent trajectory, replay its first N bash actions inside a
fresh container of the task image to reach state S, docker-commit S as a
snapshot image, then fork one container per candidate action, execute the
candidate, and collect the real outcome (stdout/stderr/return_code/elapsed)
plus the resulting /app/submissions tree.

Usage:
    python3 scripts/fork_sample.py --task-dir ORAgentBench/harbor_tasks/<task> \
        --trajectory runs/<job>/<task>__<id>/agent/ora/trajectory.jsonl \
        --upto-seq 10 --candidates candidates.json --workdir runs/fork_<x>

Candidates JSON: a list of {"command": str, "action_kind": str,
"rationale": str, "timeout_sec"?: int}.

--dry-run validates inputs and prints the replay prefix + plan without
touching docker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_EXEC_TIMEOUT_SEC = 600


def log(msg: str) -> None:
    print(f"[fork_sample {datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}",
          flush=True)


# ---------------------------------------------------------------------------
# Input extraction (pure functions, unit-testable without docker)
# ---------------------------------------------------------------------------

def extract_replay_prefix(trajectory_path, upto_seq: int,
                          skip_patterns: list[str] | None = None) -> list[dict]:
    """Take bash actions with seq <= upto_seq from a trajectory.jsonl.

    finish actions and non-bash tools are skipped. Commands matching any
    skip pattern (regex) are skipped and reported. Returns a list of
    {seq, command, action_kind} in seq order.
    """
    patterns = [re.compile(p) for p in (skip_patterns or [])]
    prefix, skipped = [], []
    for line in Path(trajectory_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("event") != "action":
            continue
        action = e.get("action") or {}
        if action.get("tool") != "bash":
            continue
        seq = e.get("seq")
        if not isinstance(seq, int) or seq > upto_seq:
            continue
        command = action.get("command") or ""
        if any(p.search(command) for p in patterns):
            skipped.append({"seq": seq, "command": command[:120]})
            continue
        prefix.append({"seq": seq, "command": command,
                       "action_kind": action.get("action_kind", "other")})
    prefix.sort(key=lambda a: a["seq"])
    if skipped:
        log(f"skip-pattern filtered {len(skipped)} replay command(s): "
            f"{[s['seq'] for s in skipped]}")
    return prefix


def load_candidates(path) -> list[dict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("candidates file must be a non-empty JSON list")
    candidates = []
    for i, c in enumerate(raw):
        if not isinstance(c, dict) or not isinstance(c.get("command"), str) \
                or not c["command"].strip():
            raise ValueError(f"candidate #{i} must have a non-empty 'command' string")
        candidates.append({
            "command": c["command"],
            "action_kind": c.get("action_kind", "other"),
            "rationale": c.get("rationale", ""),
            "timeout_sec": int(c.get("timeout_sec") or DEFAULT_EXEC_TIMEOUT_SEC),
        })
    return candidates


def action_hash(command: str, action_kind: str) -> str:
    canonical = json.dumps({"command": command, "action_kind": action_kind},
                           sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Docker plumbing
# ---------------------------------------------------------------------------

def _run(cmd: list[str], *, timeout: int | None = None,
         check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          check=check)


def build_task_image(task_dir: Path, tag: str) -> str:
    """docker build the task environment. Proxy build args are passed through
    from the process environment because this host's docker build needs the
    local proxy (127.0.0.1:7893) for apt/pip."""
    env_dir = task_dir / "environment"
    if not env_dir.is_dir():
        raise RuntimeError(f"task environment dir not found: {env_dir}")
    cmd = ["docker", "build", "--network", "host", "-t", tag]
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        if os.environ.get(var):
            cmd += ["--build-arg", f"{var}={os.environ[var]}"]
    cmd.append(str(env_dir))
    log(f"building image: {' '.join(cmd[:6])} ... {env_dir}")
    proc = _run(cmd, timeout=3600)
    if proc.returncode != 0:
        reusable = _run(["docker", "images", "--format",
                         "{{.Repository}}:{{.Tag}}"]).stdout
        candidates = [l for l in reusable.splitlines()
                      if task_dir.name.split("__")[0] in l or "oragentbench" in l]
        hint = ("\nReusable local images that might match:\n  " + "\n  ".join(candidates)
                if candidates else "\nNo obviously reusable local image found.")
        raise RuntimeError(
            f"docker build failed (rc={proc.returncode}).\n"
            f"stderr tail:\n{proc.stderr[-2000:]}{hint}\n"
            f"If a harbor-built image for this task exists, retag it as {tag!r} "
            f"and re-run, or fix the Dockerfile/network first.")
    log(f"image built: {tag}")
    return tag


def _docker(*args: str, timeout: int | None = None) -> subprocess.CompletedProcess:
    return _run(["docker", *args], timeout=timeout)


def replay_to_snapshot(image: str, prefix: list[dict], snapshot_tag: str) -> dict:
    """Start a container, replay prefix commands, commit as snapshot image."""
    proc = _docker("run", "-d", image, "sleep", "infinity")
    if proc.returncode != 0:
        raise RuntimeError(f"docker run failed: {proc.stderr[-500:]}")
    cid = proc.stdout.strip()
    log(f"replay container started: {cid[:12]} ({len(prefix)} commands)")
    records = []
    try:
        for i, action in enumerate(prefix):
            started = time.monotonic()
            r = _docker("exec", cid, "bash", "-c", action["command"],
                        timeout=DEFAULT_EXEC_TIMEOUT_SEC)
            elapsed = time.monotonic() - started
            records.append({"seq": action["seq"], "return_code": r.returncode,
                            "elapsed_s": round(elapsed, 2)})
            # A failed replay command is still part of the real state: record
            # and continue, mirroring what the agent actually observed.
            log(f"  replay {i + 1}/{len(prefix)} seq={action['seq']} "
                f"rc={r.returncode} ({elapsed:.1f}s)")
        proc = _docker("commit", cid, snapshot_tag)
        if proc.returncode != 0:
            raise RuntimeError(f"docker commit failed: {proc.stderr[-500:]}")
        image_id = proc.stdout.strip()
        log(f"snapshot committed: {snapshot_tag} ({image_id[:19]})")
    finally:
        _docker("rm", "-f", cid)
        log(f"replay container removed: {cid[:12]}")
    return {"snapshot_image": snapshot_tag, "snapshot_image_id": image_id,
            "replay_records": records}


def run_fork(snapshot_image: str, candidate: dict, index: int,
             workdir: Path) -> dict:
    """Run one candidate action in a fresh container of the snapshot."""
    timeout = candidate["timeout_sec"]
    proc = _docker("run", "-d", snapshot_image, "sleep", "infinity")
    if proc.returncode != 0:
        raise RuntimeError(f"docker run (fork {index}) failed: {proc.stderr[-500:]}")
    cid = proc.stdout.strip()
    log(f"fork {index}: container {cid[:12]}, timeout={timeout}s")
    result: dict = {}
    try:
        started = time.monotonic()
        try:
            r = _docker("exec", cid, "bash", "-c", candidate["command"],
                        timeout=timeout)
            result = {"stdout": r.stdout, "stderr": r.stderr,
                      "return_code": r.returncode, "timed_out": False}
        except subprocess.TimeoutExpired as e:
            result = {"stdout": (e.stdout or "") if isinstance(e.stdout, str) else "",
                      "stderr": (e.stderr or "") if isinstance(e.stderr, str) else "",
                      "return_code": None, "timed_out": True}
        result["elapsed_s"] = round(time.monotonic() - started, 2)
        log(f"fork {index}: rc={result['return_code']} "
            f"timed_out={result['timed_out']} ({result['elapsed_s']}s)")

        fork_dir = workdir / f"fork_{index}"
        fork_dir.mkdir(parents=True, exist_ok=True)
        cp = _docker("cp", f"{cid}:/app/submissions",
                     str(fork_dir / "submissions"))
        result["submissions_copied"] = cp.returncode == 0
        if cp.returncode != 0:
            log(f"fork {index}: [warn] no /app/submissions copied: "
                f"{cp.stderr.strip()[:200]}")
    finally:
        _docker("rm", "-f", cid)
        log(f"fork {index}: container removed")
    return result


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--task-dir", required=True,
                    help="ORAgentBench harbor_tasks/<task> dir (read-only)")
    ap.add_argument("--trajectory", required=True,
                    help="trajectory.jsonl from a real ora_agent run")
    ap.add_argument("--upto-seq", type=int, required=True,
                    help="replay bash actions with seq <= this value")
    ap.add_argument("--candidates", required=True,
                    help="JSON file with K candidate actions")
    ap.add_argument("--workdir", required=True, help="output directory")
    ap.add_argument("--timeout", type=int, default=DEFAULT_EXEC_TIMEOUT_SEC,
                    help="per-candidate exec timeout (default 600s)")
    ap.add_argument("--skip-pattern", action="append", default=[],
                    help="regex; replay commands matching it are skipped "
                         "(repeatable, e.g. --skip-pattern 'sleep|interactive')")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate inputs and print the replay plan; no docker")
    args = ap.parse_args(argv)

    task_dir = Path(args.task_dir)
    if not task_dir.is_dir():
        print(f"task dir not found: {task_dir}", file=sys.stderr)
        return 1
    task_name = task_dir.name
    prefix = extract_replay_prefix(args.trajectory, args.upto_seq,
                                   args.skip_pattern)
    candidates = load_candidates(args.candidates)
    for c in candidates:
        c["timeout_sec"] = min(c["timeout_sec"], args.timeout) \
            if args.timeout else c["timeout_sec"]
        c["action_hash"] = action_hash(c["command"], c["action_kind"])

    log(f"task={task_name} replay_prefix={len(prefix)} commands "
        f"(seq<={args.upto_seq}), candidates={len(candidates)}")
    for a in prefix:
        log(f"  replay seq={a['seq']:>3} [{a['action_kind']}] {a['command'][:100]}")
    for i, c in enumerate(candidates):
        log(f"  candidate {i} [{c['action_kind']}] hash={c['action_hash']} "
            f"{c['command'][:100]}")

    if args.dry_run:
        log("dry-run: stopping before any docker call")
        return 0
    if not prefix:
        print("empty replay prefix; nothing to replay", file=sys.stderr)
        return 1

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz")
    image_tag = f"ora-fork-{task_name}-{ts}".lower()
    snapshot_tag = f"{image_tag}-snapshot"

    build_task_image(task_dir, image_tag)
    snap = replay_to_snapshot(image_tag, prefix, snapshot_tag)

    forks = []
    for i, c in enumerate(candidates):
        forks.append({"index": i, "candidate": c, "result": run_fork(
            snapshot_tag, c, i, workdir)})

    report = {
        "ts": ts,
        "task_name": task_name,
        "task_dir": str(task_dir),
        "trajectory": str(args.trajectory),
        "state": {"upto_seq": args.upto_seq, "n_replay_commands": len(prefix),
                  "skip_patterns": args.skip_pattern},
        "snapshot_image": snap["snapshot_image"],
        "snapshot_image_id": snap["snapshot_image_id"],
        "replay_records": snap["replay_records"],
        "forks": forks,
    }
    out = workdir / "fork_results.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    log(f"results written to {out}")
    log(f"snapshot image kept: {snapshot_tag} (remove manually when done)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

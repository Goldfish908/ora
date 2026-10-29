#!/usr/bin/env python3
"""Controlled-defect evaluation of the audit/repair workers (task book 2.5b).

Real LLM, real execution — no mocks. For every artifact under controlled/
(correct / mutants/* / equivalent/*) this driver:

  a. audit(focus="full semantic audit", mode=full) — worker extracts
     requirements + suspected findings with proposed_checks.
  b. executes the proposed_checks for real in a local sandbox (60s each).
  c. audit(focus="confirm", <real check outputs>) — worker upgrades/refutes
     findings (actual_test evidence).
  d. if a semantic/implementation finding is confirmed: repair(finding_id) ->
     apply patch_commands in the sandbox (original solve.py backed up first)
     -> copy the whole controlled/<problem>/ tree to a temp dir, swap in the
     patched solve.py, run the artifact's witness there -> audit(
     focus="verify_fix") classifies the RepairResult.

Input-control experiment (2.3): every mutant additionally gets a blind pass
(audit + real checks + confirm, all with mode="blind", no problem statement).

Discipline:
- labels.json is NEVER read here (scoring only, scripts/score_controlled_eval.py).
- controlled/ originals and witness scripts are never modified; patches apply
  to sandbox copies only.
- Worker-proposed commands run locally but are gated: they must reference
  /app (mapped into the sandbox) or /tmp, and must not match a blocklist.

Env: ORA_LLM_BASE_URL / ORA_LLM_API_KEY / ORA_LLM_MODEL (see ora_agent.llm).
Usage: python3 scripts/run_controlled_eval.py [--only tiny_assign/a_m1] [--resume]
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tokenize
from pathlib import Path

ORA_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ORA_ROOT))

from ora_agent import llm as llm_mod            # noqa: E402
from ora_agent.budget import BudgetTracker      # noqa: E402
from ora_agent.evidence import EvidenceStore    # noqa: E402
from ora_agent.trajectory import TrajectoryWriter  # noqa: E402
from ora_agent.workers import (                 # noqa: E402
    WorkerManager, _AUDIT_SYSTEM, _REPAIR_SYSTEM,
    _AUDIT_CONFIRM_ADDENDUM, _AUDIT_VERIFY_FIX_ADDENDUM, _AUDIT_BLIND_NOTE,
)

CONTROLLED = ORA_ROOT / "controlled"
WORK = ORA_ROOT / "work" / "controlled_eval"
RL_PY = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"

CHECK_TIMEOUT_SEC = 60
PATCH_TIMEOUT_SEC = 120
MAX_CHECKS_PER_ARTIFACT = 6

# Thinking disabled for worker calls: probed 2026-10-28 on the Aliyun MaaS
# endpoint — with reasoning on, one audit call took 508s (27k tokens, mostly
# reasoning); with "enable_thinking": false the same class of request returns
# in ~2s. Recorded in every result.json for provenance.
WORKER_LLM_EXTRA = {"enable_thinking": False}

# Cheap guard for worker-proposed commands running on the host.
_BLOCKED_RE = re.compile(
    r"rm\s+-[a-z]*r[a-z]*f|mkfs|:\(\)\s*\{|>\s*/dev/sd|shutdown|reboot",
    re.IGNORECASE)

PROMPT_VERSIONS = {
    name: hashlib.sha256(text.encode()).hexdigest()[:16]
    for name, text in {
        "audit_system": _AUDIT_SYSTEM,
        "audit_confirm_addendum": _AUDIT_CONFIRM_ADDENDUM,
        "audit_verify_fix_addendum": _AUDIT_VERIFY_FIX_ADDENDUM,
        "audit_blind_note": _AUDIT_BLIND_NOTE,
        "repair_system": _REPAIR_SYSTEM,
    }.items()
}


def log(msg: str) -> None:
    print(f"[run_controlled_eval {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def discover_artifacts() -> list[dict]:
    """From the directory layout only (labels.json is evaluation-side)."""
    artifacts = []
    for prob_dir in sorted(CONTROLLED.iterdir()):
        if not prob_dir.is_dir() or prob_dir.name.startswith("."):
            continue
        entries = [("correct", "correct", "correct/solve.py")]
        for sub in ("mutants", "equivalent"):
            d = prob_dir / sub
            if d.is_dir():
                for aid_dir in sorted(d.iterdir()):
                    if aid_dir.is_dir():
                        kind = "mutant" if sub == "mutants" else "equivalent"
                        entries.append((aid_dir.name, kind,
                                        f"{sub}/{aid_dir.name}/solve.py"))
        for aid, kind, rel in entries:
            if (prob_dir / rel).is_file():
                artifacts.append({"problem": prob_dir.name, "aid": aid,
                                  "kind": kind, "rel_solve": rel})
    return artifacts


def _sanitize_source(src: str) -> str:
    """Strip comments and docstrings by line/column surgery on the ORIGINAL
    text (no ast.unparse: its re-emitted f-strings can exceed the runtime
    Python's grammar, e.g. PEP 701 nested quotes)."""
    tree = ast.parse(src)  # raises SyntaxError — caller decides
    lines = src.splitlines(keepends=True)
    # docstring spans -> blank lines (or `pass` when it is the only statement)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (isinstance(body, list) and body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            d = body[0]
            if len(body) == 1:
                lines[d.lineno - 1] = " " * d.col_offset + "pass\n"
                for ln in range(d.lineno, d.end_lineno):
                    lines[ln] = "\n"
            else:
                for ln in range(d.lineno - 1, d.end_lineno):
                    lines[ln] = "\n"
    # comment char-ranges -> blank (comments never span lines)
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            ln, c0, c1 = tok.start[0] - 1, tok.start[1], tok.end[1]
            lines[ln] = lines[ln][:c0] + lines[ln][c1:]
    return "".join(lines)


def sanitize_blind_tree(app: Path) -> int:
    """E1.4 (taskbook 5195): de-leak blind mode. Strip comments AND docstrings
    from every .py the blind worker can read, so spec-revealing text (e.g.
    `# at least 20 pieces` next to a `<=` bug, or `precedence J1 -> J3` in a
    docstring) cannot answer the audit. Original formatting and semantics are
    preserved (line/column surgery, no re-emission). Returns file count."""
    n = 0
    for py in sorted(app.rglob("*.py")):
        src = py.read_text(encoding="utf-8")
        try:
            out = _sanitize_source(src)
        except (SyntaxError, tokenize.TokenError):
            continue
        py.write_text(out, encoding="utf-8")
        n += 1
    return n


def build_sandbox(sandbox: Path, problem: str, artifact: dict,
                  blind: bool = False) -> Path:
    """Create the worker-visible tree; returns the app dir (≡ /app).

    Layout:
      <sandbox>/app/PROBLEM_STATEMENT.md   (= controlled/<p>/problem.md)
      <sandbox>/app/data/                  (worker-facing copy)
      <sandbox>/app/submissions/solve.py   (the artifact under test)
      <sandbox>/data/                      (second copy: depth-2 artifacts use
                                            BASE.parent.parent/"data")
    """
    app = sandbox / "app"
    (app / "submissions").mkdir(parents=True, exist_ok=True)
    shutil.copy(CONTROLLED / problem / "problem.md",
                app / "PROBLEM_STATEMENT.md")
    shutil.copytree(CONTROLLED / problem / "data", app / "data")
    shutil.copytree(CONTROLLED / problem / "data", sandbox / "data")
    shutil.copy(CONTROLLED / problem / artifact["rel_solve"],
                app / "submissions" / "solve.py")
    if blind:
        sanitize_blind_tree(app)
    return app


def make_local_exec_fn(app: Path):
    """Local bash exec_fn: maps /app -> sandbox app dir, cwd=app dir, runs
    with the rl-env python on PATH (pyscipopt available)."""
    app_s = str(app)

    async def exec_fn(command: str, timeout_sec: int) -> dict:
        mapped = re.sub(r"/app\b", app_s, command)
        env = dict(os.environ)
        env["PATH"] = str(Path(RL_PY).parent) + ":" + env.get("PATH", "")
        try:
            proc = await asyncio.create_subprocess_shell(
                mapped, cwd=app_s, env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)
            try:
                out, err = await asyncio.wait_for(proc.communicate(),
                                                  timeout=timeout_sec)
                return {"stdout": out.decode(errors="replace"),
                        "stderr": err.decode(errors="replace"),
                        "return_code": proc.returncode}
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {"stdout": "", "stderr": "", "return_code": -1,
                        "timed_out": True,
                        "error": f"TimeoutError: exceeded {timeout_sec}s"}
        except Exception as e:
            return {"stdout": "", "stderr": "", "return_code": -1,
                    "error": f"{type(e).__name__}: {e}"}

    return exec_fn


def command_allowed(command: str) -> bool:
    if _BLOCKED_RE.search(command):
        return False
    return ("/app" in command) or ("/tmp" in command)


async def run_checks(commands: list[str], exec_fn) -> list[dict]:
    results = []
    for cmd in commands[:MAX_CHECKS_PER_ARTIFACT]:
        if not command_allowed(cmd):
            results.append({"command": cmd, "rejected": True,
                            "reason": "blocked by command guard"})
            log(f"    [guard] rejected check: {cmd[:100]}")
            continue
        r = await exec_fn(cmd, CHECK_TIMEOUT_SEC)
        results.append({
            "command": cmd, "return_code": r.get("return_code"),
            "timed_out": bool(r.get("timed_out")),
            "stdout_tail": (r.get("stdout") or "")[-1500:],
            "stderr_tail": (r.get("stderr") or "")[-500:],
        })
        log(f"    check rc={r.get('return_code')}: {cmd[:100]}")
    return results


def format_checks_for_confirm(checks: list[dict]) -> str:
    parts = ["The orchestrator executed the proposed checks for real. "
             "Observed outputs:"]
    for c in checks:
        if c.get("rejected"):
            parts.append(f"\n### check (rejected by guard): {c['command']}")
            continue
        parts.append(
            f"\n### check: {c['command']}\nreturn_code: {c['return_code']}\n"
            f"timed_out: {c['timed_out']}\nstdout tail:\n{c['stdout_tail']}\n"
            f"stderr tail:\n{c['stderr_tail']}")
    parts.append("\nRe-classify the findings based ONLY on these observations.")
    return "\n".join(parts)


def collect_proposed_checks(audit_summary: dict) -> list[str]:
    cmds = []
    for f in audit_summary.get("findings") or []:
        for c in f.get("proposed_checks") or []:
            if c not in cmds:
                cmds.append(c)
    return cmds


_JSON_RETRY_NOTE = (
    "FORMAT REMINDER: your previous reply was not valid JSON. Respond with a "
    "single valid JSON object only — no prose, no markdown fences, balanced "
    "brackets/braces.\n\n")


async def audit_json(manager: WorkerManager, *, focus: str, question: str,
                     mode: str) -> dict:
    """manager.audit + json.loads, with one format retry on unparseable
    output (observed on qwen3.8-27b: occasional stray trailing bracket)."""
    reply = await manager.audit(focus=focus, question=question, mode=mode)
    try:
        summary = json.loads(reply)
    except json.JSONDecodeError:
        return {"error": f"audit reply unparseable: {reply[:300]}"}
    if "unparseable" in str(summary.get("error", "")):
        log(f"    [retry] {focus} reply unparseable; retrying with format note")
        reply = await manager.audit(focus=focus,
                                    question=_JSON_RETRY_NOTE + question,
                                    mode=mode)
        try:
            summary = json.loads(reply)
        except json.JSONDecodeError:
            return {"error": f"audit reply unparseable: {reply[:300]}"}
    return summary


async def repair_json(manager: WorkerManager, *, finding_id: str,
                      guidance: str) -> dict:
    reply = await manager.repair(finding_id=finding_id, guidance=guidance)
    try:
        summary = json.loads(reply)
    except json.JSONDecodeError:
        return {"error": f"repair reply unparseable: {reply[:300]}"}
    if "unparseable" in str(summary.get("error", "")):
        log(f"    [retry] repair reply unparseable; retrying with format note")
        reply = await manager.repair(
            finding_id=finding_id, guidance=_JSON_RETRY_NOTE + guidance)
        try:
            summary = json.loads(reply)
        except json.JSONDecodeError:
            return {"error": f"repair reply unparseable: {reply[:300]}"}
    return summary


def confirmed_fixable_findings(store: EvidenceStore) -> list[dict]:
    return [f for f in store.open_findings()
            if f.get("status") == "confirmed"
            and f.get("problem_type") in ("semantic", "implementation")]


def run_witness_on_patched(problem: str, artifact: dict,
                           patched_solve: Path) -> dict:
    """Copy controlled/<problem>/ to a temp tree, swap in the patched
    solve.py at the artifact's original location, run the witness there.
    Originals under controlled/ are never touched."""
    tmp = Path(tempfile.mkdtemp(prefix=f"ora_witness_{problem}_"))
    try:
        tree = tmp / problem
        shutil.copytree(CONTROLLED / problem, tree)
        shutil.copy(patched_solve, tree / artifact["rel_solve"])
        witness = tree / "witness" / f"{artifact['aid']}.py"
        if not witness.is_file():
            return {"verdict": "ERROR", "error": f"witness missing: {witness}"}
        proc = subprocess.run([RL_PY, str(witness)], capture_output=True,
                              text=True, timeout=180)
        out = proc.stdout + proc.stderr
        return {"verdict": "PASS" if proc.returncode == 0 else "FAIL",
                "return_code": proc.returncode,
                "output_tail": out[-1500:]}
    except subprocess.TimeoutExpired:
        return {"verdict": "TIMEOUT"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def eval_one_pass(artifact: dict, mode: str, sandbox: Path,
                        tracker: BudgetTracker, llm_fn,
                        do_repair: bool) -> dict:
    """One full (or blind) audit->checks->confirm(->repair->witness->verify)
    pass over one artifact sandbox."""
    problem, aid = artifact["problem"], artifact["aid"]
    app = build_sandbox(sandbox, problem, artifact, blind=(mode == "blind"))
    exec_fn = make_local_exec_fn(app)
    store = EvidenceStore(sandbox / "evidence.jsonl")
    writer = TrajectoryWriter(sandbox / "trajectory.jsonl",
                              run_id=f"{problem}_{aid}_{mode}",
                              task_id=f"{problem}/{aid}", model="worker")
    manager = WorkerManager(llm_fn=llm_fn, exec_fn=exec_fn,
                            evidence_store=store, writer=writer,
                            tracker=tracker, max_tokens=4096, temperature=0.0,
                            llm_extra=WORKER_LLM_EXTRA)
    result: dict = {"problem": problem, "aid": aid, "kind": artifact["kind"],
                    "mode": mode, "sandbox": str(sandbox),
                    "prompt_versions": PROMPT_VERSIONS, "error": None}
    started = time.monotonic()
    usage_before = tracker.combined()
    try:
        # a. audit
        audit_summary = await audit_json(
            manager,
            focus="full semantic audit",
            question=("Audit this artifact for requirement omissions, semantic "
                      "and implementation errors against the problem statement "
                      "and data. Cover all five audit points."),
            mode=mode)
        if "error" in audit_summary and "findings" not in audit_summary:
            result["audit"] = audit_summary
            result["error"] = audit_summary["error"]
            return result
        result["audit"] = audit_summary

        # b. execute proposed checks for real
        checks = await run_checks(collect_proposed_checks(audit_summary),
                                  exec_fn)
        result["checks"] = checks

        # c. confirm with real evidence
        if checks:
            result["confirm"] = await audit_json(
                manager, focus="confirm",
                question=format_checks_for_confirm(checks), mode=mode)
        result["open_findings"] = store.open_findings()

        # d. repair the first confirmed semantic/implementation finding
        fixable = confirmed_fixable_findings(store)
        if do_repair and fixable:
            finding = fixable[0]
            fid = finding["finding_id"]
            log(f"    repairing {fid} ({finding['problem_type']}): "
                f"{finding['detail'][:80]}")
            repair: dict = {"finding_id": fid}
            repair["reply"] = await repair_json(
                manager, finding_id=fid,
                guidance="Minimal local fix; keep the output schema unchanged.")
            patch_cmds = (repair["reply"].get("patch_commands")
                          if isinstance(repair.get("reply"), dict) else None) or []
            solve_py = app / "submissions" / "solve.py"
            shutil.copy(solve_py, app / "submissions" / "solve.py.orig")
            patch_results = []
            ok = True
            for cmd in patch_cmds:
                if not command_allowed(cmd):
                    patch_results.append({"command": cmd, "rejected": True})
                    ok = False
                    continue
                r = await exec_fn(cmd, PATCH_TIMEOUT_SEC)
                patch_results.append({
                    "command": cmd, "return_code": r.get("return_code"),
                    "stderr_tail": (r.get("stderr") or "")[-300:]})
                if r.get("return_code") != 0:
                    ok = False
                log(f"    patch rc={r.get('return_code')}: {cmd[:100]}")
            repair["patch_results"] = patch_results
            repair["patch_applied"] = ok and bool(patch_cmds)

            if repair["patch_applied"]:
                repair["witness_after_patch"] = run_witness_on_patched(
                    problem, artifact, solve_py)
                log(f"    witness after patch: "
                    f"{repair['witness_after_patch'].get('verdict')}")
                repair["verify_fix"] = await audit_json(
                    manager, focus="verify_fix",
                    question=json.dumps({
                        "finding": finding,
                        "patch_commands": patch_cmds,
                        "patch_results": patch_results,
                        "witness_after_patch": repair["witness_after_patch"],
                    }, ensure_ascii=False)[:4000],
                    mode=mode)
            result["repair"] = repair
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    finally:
        usage_after = tracker.combined()
        result["usage"] = {
            k: usage_after[k] - usage_before[k]
            for k in ("calls", "prompt_tokens", "completion_tokens")}
        result["usage"]["latency_s"] = round(
            usage_after["latency_s"] - usage_before["latency_s"], 2)
        result["wall_time_s"] = round(time.monotonic() - started, 1)
        writer.close()
        store.close()
    return result


async def run_all(only: set[str] | None, resume: bool) -> None:
    cfg = llm_mod.load_config()
    log(f"model={cfg.model} base_url={cfg.base_url}")

    def llm_fn(messages, **kw):
        return llm_mod.chat(messages, config=cfg, **kw)

    tracker = BudgetTracker()
    artifacts = discover_artifacts()
    if only:
        artifacts = [a for a in artifacts
                     if f"{a['problem']}/{a['aid']}" in only]
    log(f"artifacts: {len(artifacts)}")

    for a in artifacts:
        tag = f"{a['problem']}/{a['aid']}"
        # full pass (audit + confirm + repair-if-confirmed)
        out = WORK / f"{a['problem']}_{a['aid']}"
        result_path = out / "result.json"
        if resume and result_path.is_file():
            log(f"{tag}: skip (result.json exists)")
        else:
            shutil.rmtree(out, ignore_errors=True)
            out.mkdir(parents=True, exist_ok=True)
            log(f"{tag}: full audit pass")
            result = await eval_one_pass(a, "full", out, tracker, llm_fn,
                                         do_repair=True)
            result_path.write_text(json.dumps(result, ensure_ascii=False,
                                              indent=2) + "\n")
            if result.get("error"):
                log(f"{tag}: ERROR {result['error']}")

        # blind pass (mutants only; audit + confirm, no repair)
        if a["kind"] == "mutant":
            out_b = WORK / f"{a['problem']}_{a['aid']}_blind"
            result_path_b = out_b / "result.json"
            if resume and result_path_b.is_file():
                log(f"{tag}: skip blind (exists)")
            else:
                shutil.rmtree(out_b, ignore_errors=True)
                out_b.mkdir(parents=True, exist_ok=True)
                log(f"{tag}: blind audit pass")
                result_b = await eval_one_pass(a, "blind", out_b, tracker,
                                               llm_fn, do_repair=False)
                result_path_b.write_text(json.dumps(result_b, ensure_ascii=False,
                                                    indent=2) + "\n")
                if result_b.get("error"):
                    log(f"{tag} blind: ERROR {result_b['error']}")

    totals = tracker.combined()
    (WORK / "run_totals.json").write_text(json.dumps(
        {"role_totals": tracker.role_totals(), "combined": totals},
        indent=2) + "\n")
    log(f"done. combined usage: {totals}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", action="append", default=None,
                    help="limit to problem/aid (repeatable)")
    ap.add_argument("--resume", action="store_true",
                    help="skip artifacts whose result.json already exists")
    args = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    asyncio.run(run_all(set(args.only) if args.only else None, args.resume))
    return 0


if __name__ == "__main__":
    sys.exit(main())

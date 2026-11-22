"""Decision-space repair using only public data and an agent-generated incumbent."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import sysconfig
from pathlib import Path

from . import llm as llm_mod
from .oragentbench import (
    TaskPacket,
    _call_artifact_tool,
    _docker,
    _undefined_solver_globals,
    apply_runtime_patch,
    prepare_workspace,
    write_json,
)

_BLOCKED_IMPORTS = {
    "pyscipopt", "numpy", "pandas", "scipy", "highspy", "ortools", "cvxpy", "pulp",
    "gurobipy", "subprocess", "socket", "urllib", "http", "ssl", "ftplib", "ctypes",
    "multiprocessing", "runpy", "code", "codeop",
}


_STDLIB_ROOT = Path(sysconfig.get_paths()["stdlib"]).resolve()


def _nonstandard_imports(roots: set[str]) -> set[str]:
    invalid = set()
    for root in roots:
        if root in _BLOCKED_IMPORTS:
            invalid.add(root)
            continue
        if root in sys.builtin_module_names:
            continue
        try:
            spec = importlib.util.find_spec(root)
        except (ImportError, ValueError):
            invalid.add(root)
            continue
        if spec is None or spec.origin is None:
            invalid.add(root)
            continue
        if spec.origin in {"built-in", "frozen"}:
            continue
        try:
            Path(spec.origin).resolve().relative_to(_STDLIB_ROOT)
        except (TypeError, ValueError):
            invalid.add(root)
    return invalid


def decision_artifact_path(workspace: Path) -> Path | None:
    for name in ("solution.csv", "solution.json"):
        path = workspace / "submissions" / name
        if path.exists():
            return path
    return None


def validate_decision_repair_code(code: str) -> None:
    if len(code.strip()) < 300:
        raise ValueError("incomplete_artifact: decision repair is too short")
    if "placeholder" in code.lower():
        raise ValueError("incomplete_artifact: placeholder marker found")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError("incomplete_artifact: decision repair is not valid Python") from exc
    if "solution_original" not in code or not any(name in code for name in ("solution.csv", "solution.json")):
        raise ValueError("incomplete_artifact: decision repair must read the incumbent and write the required solution")
    if not any(marker in code for marker in ("open(", ".write_text(", "json.dump", "csv.writer")):
        raise ValueError("incomplete_artifact: no decision output write")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and all(
                isinstance(statement, (ast.Pass, ast.Ellipsis)) for statement in node.body):
            raise ValueError("incomplete_artifact: empty function body found")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "compile", "__import__"}:
            raise ValueError("incomplete_artifact: dynamic code execution is not allowed")
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
            if _nonstandard_imports(roots):
                raise ValueError("incomplete_artifact: decision repair must use only the Python standard library")
        if isinstance(node, ast.ImportFrom):
            if _nonstandard_imports({(node.module or "").split(".")[0]}):
                raise ValueError("incomplete_artifact: decision repair must use only the Python standard library")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value.startswith("/") and not (node.value == "/app" or node.value.startswith("/app/")):
            raise ValueError("incomplete_artifact: decision repair may only access public sandbox files")
    unknown = _undefined_solver_globals(code, tree)
    if unknown:
        raise ValueError("incomplete_artifact: unresolved global names: " + ", ".join(unknown[:8]))


def generate_decision_repair(packet: TaskPacket, specification: str, config: llm_mod.LLMConfig,
                             outdir: Path, run_seed: int, repair: dict) -> dict:
    max_tokens = min(int(os.environ.get("ORA_CLEANROOM_MAX_TOKENS", "32768")), 8192)
    reasoning = os.environ.get("ORA_CLEANROOM_SOLVER_REASONING",
                               os.environ.get("ORA_CLEANROOM_REASONING", "medium"))
    disable = os.environ.get("ORA_CLEANROOM_SOLVER_DISABLE_THINKING",
                             os.environ.get("ORA_CLEANROOM_DISABLE_THINKING", "0")) == "1"
    incumbent = repair["decision_artifact"]
    request = {"solver_max_tokens": max_tokens, "solver_reasoning_effort": reasoning,
               "solver_disable_thinking": disable, "temperature": 0.6, "stream": False,
               "protocol": "decision_space_repair_v1",
               "parent_decision_sha256": hashlib.sha256(incumbent.encode()).hexdigest()}
    messages = packet.prompt(specification, repair, tool_name="submit_decision_repair")
    response = None
    try:
        prompt_hash = hashlib.sha256(json.dumps(messages).encode()).hexdigest()
        response, payload = _call_artifact_tool("decision_repair", messages, config, max_tokens,
                                               reasoning, run_seed ^ int(prompt_hash[:8], 16), disable)
        code = payload["repair_py"]
        validate_decision_repair_code(code)
        artifacts = {**repair["artifacts"], "repair_solution_py": code,
                     "repair_log_md": payload["repair_log_md"]}
        write_json(outdir / "decision_repair_generation.json", {
            "messages": messages, "response": response, "request": request})
        error = None
    except Exception as exc:
        response = getattr(exc, "response", None) or response or {
            "request_attempts": getattr(exc, "request_attempts", []), "usage": {}}
        error = f"{type(exc).__name__}: {exc}"
        write_json(outdir / "decision_repair_generation.json", {
            "messages": messages, "response": response, "request": request, "error": error})
    write_json(outdir / "generation.json", {
        "task": packet.name, "specification_sha256": hashlib.sha256(specification.encode()).hexdigest(),
        "repair": True, "request": request, "response": response, "error": error})
    if error:
        raise RuntimeError(error)
    write_json(outdir / "artifacts.json", artifacts)
    return artifacts


def localized_failure_context(code: str, stderr: str) -> dict | None:
    matches = list(re.finditer(r'File "([^"]*repair_solution\.py)", line (\d+)(?:, in ([^\n]+))?', stderr))
    if not matches:
        return None
    match = matches[-1]
    line = int(match.group(2))
    lines = code.splitlines()
    if not 1 <= line <= len(lines):
        return None
    start, end = max(1, line - 5), min(len(lines), line + 5)
    function_source = None
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == match.group(3):
            function_source = ast.get_source_segment(code, node)
            break
    return {"file": match.group(1), "line": line, "function": match.group(3),
            "exception": stderr.strip().splitlines()[-1] if stderr.strip() else "",
            "source_excerpt": "\n".join(f"{index}: {lines[index - 1]}"
                                         for index in range(start, end + 1)),
            "function_source": function_source}


def generate_decision_code_patch(packet: TaskPacket, specification: str, config: llm_mod.LLMConfig,
                                 outdir: Path, run_seed: int, repair: dict) -> dict:
    max_tokens = min(int(os.environ.get("ORA_CLEANROOM_MAX_TOKENS", "32768")), 8192)
    reasoning = os.environ.get("ORA_CLEANROOM_SOLVER_REASONING",
                               os.environ.get("ORA_CLEANROOM_REASONING", "medium"))
    disable = os.environ.get("ORA_CLEANROOM_SOLVER_DISABLE_THINKING",
                             os.environ.get("ORA_CLEANROOM_DISABLE_THINKING", "0")) == "1"
    code = repair["artifacts"]["repair_solution_py"]
    request = {"solver_max_tokens": max_tokens, "solver_reasoning_effort": reasoning,
               "solver_disable_thinking": disable, "temperature": 0.6, "stream": False,
               "protocol": "decision_runtime_patch_v1",
               "parent_repair_code_sha256": hashlib.sha256(code.encode()).hexdigest()}
    prompt_repair = {**repair, "artifacts": {**repair["artifacts"], "solve_py": code}}
    execution = repair["evidence"].get("execution", {})
    context = localized_failure_context(code, execution.get("stderr") or execution.get("stderr_tail") or "")
    if context:
        prompt_repair["evidence"] = {**repair["evidence"], "failure_context": context}
    messages = packet.prompt(specification, prompt_repair, tool_name="submit_runtime_patch")
    response = None
    try:
        prompt_hash = hashlib.sha256(json.dumps(messages).encode()).hexdigest()
        response, patch = _call_artifact_tool("runtime_patch", messages, config, max_tokens,
                                             reasoning, run_seed ^ int(prompt_hash[:8], 16), disable)
        artifacts = {**repair["artifacts"],
                     "repair_solution_py": apply_runtime_patch(
                         code, patch.get("edits"), validator=validate_decision_repair_code)}
        write_json(outdir / "runtime_patch_generation.json", {
            "messages": messages, "response": response, "request": request})
        error = None
    except Exception as exc:
        response = getattr(exc, "response", None) or response or {
            "request_attempts": getattr(exc, "request_attempts", []), "usage": {}}
        error = f"{type(exc).__name__}: {exc}"
        write_json(outdir / "runtime_patch_generation.json", {
            "messages": messages, "response": response, "request": request, "error": error})
    write_json(outdir / "generation.json", {
        "task": packet.name, "specification_sha256": hashlib.sha256(specification.encode()).hexdigest(),
        "repair": True, "request": request, "response": response, "error": error})
    if error:
        raise RuntimeError(error)
    write_json(outdir / "artifacts.json", artifacts)
    return artifacts


def prepare_decision_repair_workspace(packet: TaskPacket, workspace: Path, artifacts: dict,
                                      original_workspace: Path, api_guard: bool = False) -> None:
    prepare_workspace(packet, workspace, artifacts, api_guard=api_guard, validate=False)
    original = decision_artifact_path(original_workspace)
    if original is None:
        for name in ("solution_original.csv", "solution_original.json"):
            candidate = original_workspace / "submissions" / name
            if candidate.exists():
                original = candidate
                break
    if original is None:
        raise ValueError("decision repair requires an agent-generated incumbent")
    destination = workspace / "submissions" / f"solution_original{original.suffix}"
    shutil.copy2(original, destination)
    code = artifacts["repair_solution_py"]
    validate_decision_repair_code(code)
    (workspace / "submissions/repair_solution.py").write_text(code)
    (workspace / "submissions/repair_log.md").write_text(artifacts["repair_log_md"])


def execute_decision_repair(workspace: Path, outdir: Path, timeout: int = 120) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    result = _docker("decision-repair", [(workspace, "/app", False)],
                     ["python", "/app/submissions/repair_solution.py"], timeout)
    (outdir / "stdout.txt").write_text(result["stdout"])
    (outdir / "stderr.txt").write_text(result["stderr"])
    write_json(outdir / "execution.json", {**result, "stdout": None, "stderr": None,
                                          "stdout_file": "stdout.txt", "stderr_file": "stderr.txt"})
    return result


def decision_artifact_sha256(workspace: Path) -> str | None:
    path = decision_artifact_path(workspace)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path else None

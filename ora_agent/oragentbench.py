"""Clean-room ORAgentBench public packets, artifact generation and isolated execution."""
from __future__ import annotations

import ast
import builtins
import hashlib
import json
import os
import shutil
import subprocess
import symtable
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import llm as llm_mod
from .api_guard import repair_known_api_errors, repair_public_output_contract

BASE_IMAGE = "oragentbench-base:py311-scip"
SUBMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_artifacts",
        "description": "Submit a complete OR modeling document and executable PySCIPOpt solver.",
        "parameters": {
            "type": "object",
            "properties": {
                "model_md": {"type": "string", "description": "Complete mathematical model in Markdown."},
                "solve_py": {"type": "string", "description": "Complete executable Python/PySCIPOpt solver."},
                "solve_log_md": {"type": "string", "description": "Honest execution and validation log template."},
            },
            "required": ["model_md", "solve_py", "solve_log_md"],
        },
    },
}


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


@dataclass(frozen=True)
class TaskPacket:
    root: Path
    name: str
    domain: str
    split: str
    instruction: str
    problem_statement: str
    public_files: dict[str, str]

    @property
    def app_dir(self) -> Path:
        return self.root / "environment/app"

    @property
    def scope(self) -> dict:
        return {"dataset": "oragentbench", "domain": self.domain}

    @classmethod
    def load(cls, root: Path, domain: str, split: str, max_public_chars: int = 180_000) -> "TaskPacket":
        root = root.resolve()
        app = root / "environment/app"
        instruction = (root / "instruction.md").read_text()
        problem = (app / "PROBLEM_STATEMENT.md").read_text()
        public = {}
        total = 0
        for path in sorted(app.rglob("*")):
            if not path.is_file():
                continue
            relative = str(path.relative_to(app))
            text = path.read_text()
            total += len(text)
            if total > max_public_chars:
                raise ValueError(f"public task packet exceeds {max_public_chars} characters: {root.name}")
            public[relative] = text
        return cls(root, root.name, domain, split, instruction, problem, public)

    def prompt(self, specification: str, repair: dict | None = None,
               tool_name: str = "submit_artifacts") -> list[dict]:
        packet = "\n\n".join(f"### PUBLIC FILE: {name}\n{content}"
                             for name, content in self.public_files.items())
        system = (
            f"You are an expert operations-research modeler. Use exactly one {tool_name} tool call. "
            "Produce a complete mathematical model and a complete executable PySCIPOpt solver. "
            "Use only the public task packet and the supplied specification. Do not use the internet, "
            "hidden evaluators, reference solutions, package registries, or external files. "
            "The solver must run from scratch as `python /app/submissions/solve.py`, read the public data, "
            "use SCIP gap 0.0005, respect ORCLAW_SOLVE_TIME_LIMIT_SECONDS when set, and write the required "
            "decision artifact with the exact public schema. Do not fabricate solver results. "
            "Use module-level quicksum imported from pyscipopt, never model.quicksum. Set objective "
            "coefficients through addVar(obj=...) or setObjective with a valid expression. "
            "Do not return placeholders, TODOs, abbreviated code, or comments about writing the rest later."
        )
        if tool_name == "submit_runtime_patch":
            system = (
                "You are an expert PySCIPOpt debugger. Use exactly one submit_runtime_patch tool call. "
                "Repair only the observed runtime failure with exact source replacements. Every old_string "
                "must be a unique, contiguous span copied verbatim from the supplied previous solver. "
                "Preserve all other source bytes. Do not return a rewritten solver, placeholders or fabricated "
                "results. Construct solver expressions from Python term lists and check for an incumbent "
                "before reading its objective. The patched solver must remain complete and executable."
            )
        if repair is not None and tool_name == "submit_runtime_patch" \
                and repair["evidence"].get("search_guidance", {}).get("repair_kind") == "decision_runtime_patch":
            system = (
                "You are an operations-research decision-repair debugger. Use exactly one "
                "submit_runtime_patch tool call. Repair only the observed failure in the supplied "
                "repair_solution.py with exact source replacements. Every old_string must occur exactly "
                "once and be copied verbatim. Preserve all other code and the original solver. Use only "
                "public data and the agent-generated incumbent, preserve the output schema and all hard "
                "requirements, and do not fabricate a solution or invoke another solver. Use the supplied "
                "failure_context exception and source_excerpt to repair the reported statement and its "
                "direct dependencies first. Do not modify unrelated output, validation or model sections "
                "while the failing statement has not been addressed. When function_source is present, "
                "old_string must be that complete function and new_string must be its complete corrected "
                "replacement, not a fragment from another section."
            )
        if tool_name == "submit_decision_repair":
            system = (
                "You are an operations-research decision-repair engineer. Use exactly one "
                "submit_decision_repair tool call. Write a complete Python standard-library script "
                "that reads the agent-generated incumbent from `/app/submissions/solution_original.csv` "
                "or `solution_original.json`, repairs its decisions, and writes the exact public output "
                "schema to `solution.csv` or `solution.json`. Use only public task data and the supplied "
                "incumbent; never read reference solutions, hidden evaluators or external files. Do not "
                "rewrite or invoke the solver. Preserve unrelated correct decisions and every hard "
                "requirement. Recompute public constraints and the objective from the emitted decisions. "
                "Do not delete required service, change IDs to hide violations, or fabricate validation "
                "results. The script must run as `python /app/submissions/repair_solution.py`."
            )
        if specification.strip():
            system += "\n\nSHARED MODELING SPECIFICATION:\n" + specification.strip()
        if repair is not None:
            evidence = repair["evidence"]
            regenerate = evidence.get("search_guidance", {}).get("regenerate_from_evidence", False)
            decision_code_patch = tool_name == "submit_runtime_patch" and \
                evidence.get("search_guidance", {}).get("repair_kind") == "decision_runtime_patch"
            if tool_name == "submit_decision_repair":
                pass
            elif decision_code_patch:
                packet += "\n\n### PREVIOUS ARTIFACTS\n" + json.dumps(repair["artifacts"], ensure_ascii=False)
            elif regenerate:
                system += (
                    "\n\nEVIDENCE-GUIDED REGENERATION: build a new model from the public task and observed "
                    "evidence instead of editing previous code. Cover every public business requirement and "
                    "explicitly verify every demand, service, route and output coordinate."
                )
            else:
                system += (
                    "\n\nTARGETED REPAIR: revise the previous artifacts to address the target while preserving "
                    "all unrelated business requirements. Do not merely describe changes; return complete files."
                )
                if evidence.get("execution", {}).get("return_code") != 0:
                    system += (
                        "\n\nRUNTIME REPAIR CONTRACT: locate and fix the observed failure in the current solver "
                        "rather than replacing working logic. Construct PySCIPOpt expressions from ordinary "
                        "Python term lists: test `if terms:` before `quicksum(terms)`, never use `!=`, `<`, or "
                        "`>` to test whether an expression is empty. Use quicksum instead of mixing Python "
                        "numeric accumulation with solver terms. Check `getBestSol()` or `getNSols()` before "
                        "reading a solution or objective. Do not hide an exception or fabricate a decision file."
                    )
                packet += "\n\n### PREVIOUS ARTIFACTS\n" + json.dumps(repair["artifacts"], ensure_ascii=False)
            findings = evidence.get("semantic_findings") or []
            if findings and tool_name != "submit_decision_repair" and not decision_code_patch:
                variables = sorted({finding["variable"] for finding in findings})
                system += (
                    "\n\nREQUIRED ACTIVATION CONTRACT:\n"
                    "The following required activation variables are missing or omitted: "
                    + ", ".join(variables)
                    + ". Define each as a binary decision variable. For every lane, link positive shipment "
                      "to its activation variable with BOTH flow <= capacity * activation AND "
                      "flow >= min_shipment * activation. Write every activation variable to the decision "
                      "artifact. Do not merely rename existing flows. Address all reported business errors, "
                      "including CO2 budget violations."
                )
            packet += "\n\n### OBSERVED EVIDENCE\n" + json.dumps(evidence, ensure_ascii=False)
            if tool_name == "submit_decision_repair" or decision_code_patch:
                packet += "\n\n### AGENT-GENERATED INCUMBENT\n" + repair["decision_artifact"]
            if tool_name == "submit_decision_repair" and repair["artifacts"].get("repair_solution_py"):
                packet += "\n\n### PREVIOUS DECISION REPAIR CODE\n" + repair["artifacts"]["repair_solution_py"]
        return [{"role": "system", "content": system},
                {"role": "user", "content": f"Task: {self.name}\n\n{self.instruction}\n\n{packet}"}]


def parse_artifacts(response: dict) -> dict:
    if response.get("finish_reason") in {"length", "max_tokens"}:
        raise ValueError("artifact generation was truncated")
    calls = response.get("tool_calls") or []
    if len(calls) != 1 or calls[0]["function"]["name"] != "submit_artifacts":
        raise ValueError("expected exactly one submit_artifacts tool call")
    artifacts = json.loads(calls[0]["function"]["arguments"])
    for key in ("model_md", "solve_py", "solve_log_md"):
        if not isinstance(artifacts.get(key), str) or not artifacts[key].strip():
            raise ValueError(f"missing artifact: {key}")
    return artifacts


def _undefined_solver_globals(code: str, tree: ast.AST) -> list[str]:
    if any(isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names)
           for node in ast.walk(tree)):
        return []
    if any(isinstance(node, ast.Name) and node.id in {"eval", "exec", "globals", "locals"}
           for node in ast.walk(tree)):
        return []
    module = symtable.symtable(code, "solve.py", "exec")
    bound = {symbol.get_name() for symbol in module.get_symbols()
             if symbol.is_assigned() or symbol.is_imported()}
    unknown = set()

    def visit(scope):
        for symbol in scope.get_symbols():
            name = symbol.get_name()
            if symbol.is_global() and symbol.is_referenced() and name not in bound \
                    and not hasattr(builtins, name) and not (name.startswith("__") and name.endswith("__")):
                unknown.add(name)
        for child in scope.get_children():
            visit(child)

    visit(module)
    return sorted(unknown)


def validate_solver_code(code: str) -> None:
    if len(code.strip()) < 500:
        raise ValueError("incomplete_artifact: solver is too short to be a complete model")
    if "placeholder" in code.lower():
        raise ValueError("incomplete_artifact: placeholder marker found")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError("incomplete_artifact: solver is not valid Python") from exc
    empty_functions = [node for node in ast.walk(tree)
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and all(isinstance(statement, (ast.Pass, ast.Ellipsis))
                               for statement in node.body)]
    if empty_functions:
        raise ValueError("incomplete_artifact: empty function body found")
    if "optimize(" not in code:
        raise ValueError("incomplete_artifact: no solver optimize call")
    if not any(marker in code for marker in ("solution.csv", "solution.json", "solution_path", "sol_path")):
        raise ValueError("incomplete_artifact: no decision artifact output")
    unknown = _undefined_solver_globals(code, tree)
    if unknown:
        raise ValueError("incomplete_artifact: unresolved global names: " + ", ".join(unknown[:8]))


def _phase_tool(phase: str) -> dict:
    if phase == "model":
        name = "submit_model"
        properties = {"model_md": {"type": "string", "description": "Concise complete mathematical model in Markdown."}}
        required = ["model_md"]
    elif phase == "runtime_patch":
        name = "submit_runtime_patch"
        properties = {"edits": {"type": "array", "items": {"type": "object", "properties": {
            "old_string": {"type": "string", "description": "Unique verbatim source span to replace."},
            "new_string": {"type": "string", "description": "Complete replacement for that source span."},
        }, "required": ["old_string", "new_string"]}}}
        required = ["edits"]
    elif phase == "decision_repair":
        name = "submit_decision_repair"
        properties = {
            "repair_py": {"type": "string", "description": "Complete standard-library decision repair script."},
            "repair_log_md": {"type": "string", "description": "Honest repair and validation log template."},
        }
        required = ["repair_py", "repair_log_md"]
    else:
        name = "submit_solver"
        properties = {
            "solve_py": {"type": "string", "description": "Complete executable Python/PySCIPOpt solver."},
            "solve_log_md": {"type": "string", "description": "Honest execution and validation log template."},
        }
        required = ["solve_py", "solve_log_md"]
    return {"type": "function", "function": {"name": name,
            "description": f"Submit the {phase} artifacts.", "parameters": {
                "type": "object", "properties": properties, "required": required}}}


def _call_artifact_tool(phase: str, messages: list[dict], config: llm_mod.LLMConfig,
                        max_tokens: int, reasoning: str, seed: int,
                        disable_thinking: bool) -> tuple[dict, dict]:
    tool = _phase_tool(phase)
    name = tool["function"]["name"]
    extra = {"reasoning_effort": reasoning, "seed": seed, "tools": [tool],
             "tool_choice": {"type": "function", "function": {"name": name}}}
    if disable_thinking:
        extra["chat_template_kwargs"] = {"enable_thinking": False}
    response = None
    try:
        response = llm_mod.chat(messages, max_tokens=max_tokens, temperature=0.6,
                                extra=extra, config=config)
        if response.get("model") != config.model:
            raise ValueError("returned model differs from requested model")
        if response.get("finish_reason") in {"length", "max_tokens"}:
            raise ValueError(f"{phase} generation was truncated")
        calls = response.get("tool_calls") or []
        if len(calls) != 1 or calls[0]["function"]["name"] != name:
            raise ValueError(f"expected exactly one {name} tool call")
        return response, json.loads(calls[0]["function"]["arguments"])
    except Exception as exc:
        if response is not None:
            exc.response = response
        raise


def apply_runtime_patch(code: str, edits: list[dict], *, validator=validate_solver_code) -> str:
    if not isinstance(edits, list) or not 1 <= len(edits) <= 16:
        raise ValueError("runtime patch must contain between one and sixteen edits")
    patched = code
    for edit in edits:
        if not isinstance(edit, dict):
            raise ValueError("runtime patch edit must be an object")
        old, new = edit.get("old_string"), edit.get("new_string")
        if not isinstance(old, str) or not old or not isinstance(new, str):
            raise ValueError("runtime patch requires nonempty old_string and string new_string")
        if patched.count(old) != 1:
            raise ValueError("runtime patch old_string must match exactly once")
        patched = patched.replace(old, new, 1)
    validator(patched)
    before_tree, after_tree = ast.parse(code), ast.parse(patched)
    before_bindings = {node.id for node in ast.walk(before_tree)
                       if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
    after_bindings = {node.id for node in ast.walk(after_tree)
                      if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
    after_loads = {node.id for node in ast.walk(after_tree)
                   if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    removed_bindings = before_bindings - after_bindings
    missing = sorted(removed_bindings & after_loads)
    if missing:
        raise ValueError("runtime patch removes bindings that remain referenced: " + ", ".join(missing))
    dropped_semantic = sorted(name for name in removed_bindings
                              if any(token in name.lower() for token in ("cost", "objective", "obj")))
    if dropped_semantic:
        raise ValueError("runtime patch removes objective or cost bindings: " + ", ".join(dropped_semantic))
    return patched


def _generate_runtime_patch(packet: TaskPacket, specification: str, config: llm_mod.LLMConfig,
                            outdir: Path, run_seed: int, repair: dict) -> dict:
    max_tokens = min(int(os.environ.get("ORA_CLEANROOM_MAX_TOKENS", "32768")), 8192)
    reasoning = os.environ.get("ORA_CLEANROOM_SOLVER_REASONING",
                               os.environ.get("ORA_CLEANROOM_REASONING", "medium"))
    disable = os.environ.get("ORA_CLEANROOM_SOLVER_DISABLE_THINKING",
                             os.environ.get("ORA_CLEANROOM_DISABLE_THINKING", "0")) == "1"
    parent = repair["artifacts"]["solve_py"]
    request = {"solver_max_tokens": max_tokens, "solver_reasoning_effort": reasoning,
               "solver_disable_thinking": disable, "temperature": 0.6, "stream": False,
               "protocol": "unique_exact_runtime_patch_v1",
               "parent_solver_sha256": hashlib.sha256(parent.encode()).hexdigest()}
    messages = packet.prompt(specification, repair, tool_name="submit_runtime_patch")
    response = None
    try:
        prompt_hash = hashlib.sha256(json.dumps(messages).encode()).hexdigest()
        response, patch = _call_artifact_tool("runtime_patch", messages, config, max_tokens,
                                             reasoning, run_seed ^ int(prompt_hash[:8], 16), disable)
        artifacts = {"model_md": repair["artifacts"]["model_md"],
                     "solve_py": apply_runtime_patch(parent, patch.get("edits")),
                     "solve_log_md": repair["artifacts"]["solve_log_md"]}
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


def generate_artifacts(packet: TaskPacket, specification: str, config: llm_mod.LLMConfig,
                       outdir: Path, run_seed: int = 0, repair: dict | None = None) -> dict:
    if repair is not None and repair.get("evidence", {}).get("search_guidance", {}).get(
            "repair_kind") == "runtime_patch":
        return _generate_runtime_patch(packet, specification, config, outdir, run_seed, repair)
    response = None
    phase = "model"
    max_tokens = int(os.environ.get("ORA_CLEANROOM_MAX_TOKENS", "32768"))
    model_tokens = int(os.environ.get("ORA_CLEANROOM_MODEL_TOKENS", "4096"))
    reasoning = os.environ.get("ORA_CLEANROOM_REASONING", "medium")
    model_reasoning = os.environ.get("ORA_CLEANROOM_MODEL_REASONING", reasoning)
    solver_reasoning = os.environ.get("ORA_CLEANROOM_SOLVER_REASONING", reasoning)
    default_disable = os.environ.get("ORA_CLEANROOM_DISABLE_THINKING") == "1"
    model_disable = os.environ.get("ORA_CLEANROOM_MODEL_DISABLE_THINKING",
                                   "1" if default_disable else "0") == "1"
    solver_disable = os.environ.get("ORA_CLEANROOM_SOLVER_DISABLE_THINKING",
                                    "1" if default_disable else "0") == "1"
    model_words = os.environ.get("ORA_CLEANROOM_MODEL_WORDS", "1800")
    request = {"solver_max_tokens": max_tokens, "model_max_tokens": model_tokens,
               "model_reasoning_effort": model_reasoning, "solver_reasoning_effort": solver_reasoning,
               "model_disable_thinking": model_disable, "solver_disable_thinking": solver_disable,
               "model_max_words": int(model_words), "temperature": 0.6, "stream": False,
               "protocol": "two_phase_model_then_solver_v1"}
    try:
        model_messages = packet.prompt(specification, repair, tool_name="submit_model")
        model_messages[0]["content"] += f"\nKeep model.md concise (at most {model_words} words); do not include solver code."
        prompt_hash = hashlib.sha256(json.dumps(model_messages).encode()).hexdigest()
        response, model = _call_artifact_tool("model", model_messages, config, model_tokens,
                                              model_reasoning, run_seed ^ int(prompt_hash[:8], 16),
                                              model_disable)
        write_json(outdir / "model_generation.json", {"messages": model_messages,
                   "response": response, "request": request})
        if not model.get("model_md", "").strip():
            raise ValueError("missing artifact: model_md")

        phase = "solver"
        solver_messages = packet.prompt(specification, repair, tool_name="submit_solver")
        solver_messages.append({"role": "assistant", "content": (
            "Implement the following mathematical model; return only the solver artifacts now.\n\n"
            + model["model_md"])})
        prompt_hash = hashlib.sha256(json.dumps(solver_messages).encode()).hexdigest()
        response, solver = _call_artifact_tool("solver", solver_messages, config, max_tokens,
                                               solver_reasoning, (run_seed + 1) ^ int(prompt_hash[:8], 16),
                                               solver_disable)
        for key in ("solve_py", "solve_log_md"):
            if not solver.get(key, "").strip():
                raise ValueError(f"missing artifact: {key}")
        write_json(outdir / "solver_generation.json", {"messages": solver_messages,
                   "response": response, "request": request})
        artifacts = {"model_md": model["model_md"], **solver}
        error = None
    except Exception as exc:
        response = getattr(exc, "response", None) or response or {
            "request_attempts": getattr(exc, "request_attempts", []), "usage": {}}
        artifacts = None
        error = f"{type(exc).__name__}: {exc}"
        write_json(outdir / f"{phase}_generation.json", {"response": response,
                   "request": request, "error": error})
    write_json(outdir / "generation.json", {
        "task": packet.name, "specification_sha256": hashlib.sha256(specification.encode()).hexdigest(),
        "repair": repair is not None, "request": request, "response": response, "error": error})
    if error:
        raise RuntimeError(error)
    write_json(outdir / "artifacts.json", artifacts)
    return artifacts


def prepare_workspace(packet: TaskPacket, workspace: Path, artifacts: dict,
                      api_guard: bool = False, validate: bool = True) -> None:
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError(f"workspace is not empty: {workspace}")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(packet.app_dir, workspace, dirs_exist_ok=True)
    submissions = workspace / "submissions"
    submissions.mkdir(exist_ok=True)
    (submissions / "model.md").write_text(artifacts["model_md"])
    solve_py = artifacts["solve_py"]
    if api_guard:
        solve_py, repairs = repair_known_api_errors(solve_py)
        solve_py, contract_repairs = repair_public_output_contract(
            solve_py, packet.name, packet.instruction + "\n" + packet.problem_statement)
        if repairs or contract_repairs:
            write_json(workspace / "api_guard.json", {
                "repairs": repairs, "public_contract_repairs": contract_repairs,
                "original_sha256": hashlib.sha256(artifacts["solve_py"].encode()).hexdigest(),
                "repaired_sha256": hashlib.sha256(solve_py.encode()).hexdigest()})
    if validate:
        validate_solver_code(solve_py)
    (submissions / "solve.py").write_text(solve_py)
    (submissions / "solve_log.md").write_text(artifacts["solve_log_md"])


def _docker(name: str, mounts: list[tuple[Path, str, bool]], command: list[str],
            timeout: int, workdir: str = "/app") -> dict:
    container = f"cleanroom-{name}-{uuid.uuid4().hex[:10]}"
    args = ["docker", "run", "--rm", "--network", "none", "--name", container,
            "--user", f"{os.getuid()}:{os.getgid()}", "--cpus", "4", "--memory", "8g",
            "-w", workdir, "-e", "ORCLAW_SOLVE_TIME_LIMIT_SECONDS=300", "-e", "ORCLAW_SCIP_GAP=0.0005"]
    for host, target, readonly in mounts:
        args += ["-v", f"{host.resolve()}:{target}{':ro' if readonly else ''}"]
    args += [BASE_IMAGE, *command]
    started = time.monotonic()
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, text=True, timeout=30)
        stdout, stderr = process.communicate(timeout=30)
    return {"return_code": process.returncode, "stdout": stdout, "stderr": stderr,
            "timed_out": timed_out, "wall_seconds": round(time.monotonic() - started, 6),
            "command": command}


def execute_solver(workspace: Path, outdir: Path, timeout: int = 330) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    result = _docker("solve", [(workspace, "/app", False)],
                     ["python", "/app/submissions/solve.py"], timeout)
    (outdir / "stdout.txt").write_text(result["stdout"])
    (outdir / "stderr.txt").write_text(result["stderr"])
    write_json(outdir / "execution.json", {**result, "stdout": None, "stderr": None,
                                          "stdout_file": "stdout.txt", "stderr_file": "stderr.txt"})
    return result


def official_evaluate(packet: TaskPacket, workspace: Path, outdir: Path, timeout: int = 400) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    logs = outdir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    result = _docker("verify", [(workspace, "/app", False), (packet.root / "tests", "/tests", True),
                                (logs, "/logs", False)], ["bash", "/tests/test.sh"], timeout)
    verifier = logs / "verifier"
    evaluation = read_json(verifier / "evaluation.json") if (verifier / "evaluation.json").exists() else {
        "feasible": False, "errors": ["official evaluator did not produce evaluation.json"]}
    reward = read_json(verifier / "reward.json") if (verifier / "reward.json").exists() else {
        "feasibility": 0.0, "quality": 0.0}
    details = read_json(verifier / "reward_details.json") if (verifier / "reward_details.json").exists() else {}
    payload = {"evaluation": evaluation, "reward": reward, "reward_details": details,
               "runner": {key: result[key] for key in ("return_code", "timed_out", "wall_seconds")}}
    write_json(outdir / "official_evaluation.json", payload)
    return payload


def official_objective(evaluation: dict) -> float | None:
    payload = evaluation["evaluation"]
    for key in ("objective", "profit", "score", "total_cost"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def evaluation_unknown(evaluation: dict) -> bool:
    if not evaluation or (evaluation.get("runner") or {}).get("return_code") not in {0, None}:
        return True
    errors = (evaluation.get("evaluation") or {}).get("errors") or []
    return any("official evaluator did not produce" in str(error) for error in errors)


def official_metrics(evaluation: dict) -> dict:
    reward = evaluation["reward"]
    feasible = bool(reward.get("feasibility", 0.0))
    quality = float(reward.get("quality", 0.0) or 0.0)
    return {"feasible": feasible, "quality": quality,
            "true_correct": feasible and quality > 0.4,
            "objective": official_objective(evaluation),
            "evaluation_unknown": evaluation_unknown(evaluation)}


def proxy_match(packet: TaskPacket, evaluation: dict) -> bool | None:
    reference_path = packet.root / "tests/reference_metrics.json"
    if not reference_path.exists():
        return None
    reference = read_json(reference_path)
    target = reference.get("reference_objective")
    objective = official_metrics(evaluation)["objective"]
    if target is None or objective is None:
        return False
    tolerance = abs(float(target)) * 0.001
    if reference.get("objective_sense", "minimize") == "maximize":
        return objective >= float(target) - tolerance
    return objective <= float(target) + tolerance


def probe_pyscipopt_api(outdir: Path) -> dict:
    code = ("from pyscipopt import Model, quicksum; import inspect, pyscipopt\n"
            "print('PySCIPOpt version', pyscipopt.__version__)\n"
            "def show(name):\n"
            " try: print(name, inspect.signature(getattr(Model, name)))\n"
            " except Exception as exc: print(name, type(exc).__name__)\n"
            "names=['addVar','addCons','setObjective','setMinimize','setRealParam','setParam',"
            "'getBestSol','getSols','getSolTime','getObjVal','getObjval','getStatus',"
            "'getOrigStatus','getOrigTime','getVarVal','getNSols','getNsolns','getVal','free',"
            "'getNvars','getNVars','getNconss','getNCons','getNConss',"
            "'setUb','setLb','chgVarUb','chgVarLb','getUbGlobal','getLbGlobal',"
            "'quicksum','changeCoeff','chgCoefLinear','chgVarObj','setObjCoeff']; "
            "[show(name) for name in names]; print('module quicksum', inspect.signature(quicksum)); "
            "print('module SCIP present', hasattr(pyscipopt, 'SCIP')); "
            "from pyscipopt import Variable; "
            "print('Variable.getUbGlobal', inspect.signature(Variable.getUbGlobal)); "
            "print('Variable.getLbGlobal', inspect.signature(Variable.getLbGlobal))")
    result = _docker("api-probe", [], ["python", "-c", code], timeout=60)
    write_json(outdir / "api_probe.json", result)
    return result


def run_oracle(packet: TaskPacket, workspace: Path, timeout: int = 400) -> dict:
    prepare_workspace(packet, workspace, {"model_md": "oracle", "solve_py": "oracle", "solve_log_md": "oracle"}, validate=False)
    result = _docker("oracle", [(workspace, "/app", False), (packet.root / "solution", "/solution", True)],
                     ["bash", "/solution/solve.sh"], timeout)
    evaluation = official_evaluate(packet, workspace, workspace / "oracle_evaluation")
    return {"runner": {key: result[key] for key in ("return_code", "timed_out", "stdout", "stderr")},
            "official": evaluation, "metrics": official_metrics(evaluation)}

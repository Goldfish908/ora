#!/usr/bin/env python3
"""Adapt official AlphaOPT to RetailOpt, Qwen and independent SCIP/witness artifacts."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALPHAOPT = Path("/home/hewj13/wm/ext/alphaopt")
RL_PYTHON = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"
ALPHAOPT_COMMIT = "159ea58da557dbfe77f4d33afd78fd3a52d38ce4"
PROTOCOL = ROOT / "docs/paper/verification_amplification_protocol_v0.1.md"
CONTEXT = threading.local()
EXECUTION_LOCK = threading.Lock()
EXECUTION_COUNTER = 0
GOVERNOR = None
AUDIT_MANIFEST = None
RULE_MODE = "none"
ATTEMPT_HISTORY = {}
RAW_OUTDIR = None
LLM_COUNTER = 0

SCIP_FOOTER = r'''

status_value = model.getStatus()
print(f"status: {status_value}")
if model.getNSols() > 0:
    objective_value = float(model.getObjVal())
    print(f"objective: {objective_value}")
    print("Optimal value:", objective_value)
    def _alphaopt_key(key):
        return "|".join(str(part) for part in (key if isinstance(key, tuple) else (key,)))
    def _alphaopt_values(table):
        return {_alphaopt_key(key): float(model.getVal(var))
                for key, var in table.items() if abs(model.getVal(var)) > 1e-9}
    import json as _alphaopt_json
    _alphaopt_solution = {"objective": objective_value}
    for _alphaopt_name in ("Q", "sales", "I", "W", "lost", "sub", "X"):
        _alphaopt_solution[_alphaopt_name] = _alphaopt_values(globals().get(_alphaopt_name, {}))
    with open("solution.json", "w") as _alphaopt_file:
        _alphaopt_json.dump(_alphaopt_solution, _alphaopt_file)
'''

PROGRAM_PROMPT = r'''
You are an expert in Industrial Engineering and Operations Research. Translate the mathematical model into a complete executable PySCIPOpt program.

### Problem description
{problem_description}

### Mathematical model
{mathematical_model}

### Insights
{insights}

Requirements:
- Use `from pyscipopt import Model, quicksum` and `model = Model()`.
- The `data` variable is pre-loaded by the execution harness. Do not read files or redefine `data`.
- Define decision-variable dictionaries named exactly Q, sales, I, W, lost, sub, X. Use empty dictionaries for inactive tables.
- Keys must be tuples: Q/W/lost use (product, location, period); sales/I use (product, location, period, remaining_life); sub uses (from_product, to_product, location, period); X uses (product, source_location, destination_location, period).
- Call `model.optimize()` at top level. Do not define a main guard and do not append reporting code after optimize.
- Output ONLY one fenced Python code block.
'''

FORMULATION_PROMPT = r'''
You are an expert in Industrial Engineering and Operations Research. Build a concise, complete mathematical model.

### Problem description
{problem_description}

### Optional insights
{insights}

Return ONLY one plain-text fenced block with exactly these four sections:
## Parameters:
## Variables:
## Objective:
## Constraints:

Rules:
- Define sets, parameters, decision variables and their domains, the objective, and every constraint.
- Use the problem data and applicable insights; do not invent requirements or insight IDs.
- Be concise. Do not repeat any sentence, section, or phrase.
- Do not include explanations outside the four sections.
- Always close the final ``` fence.
'''

SELF_EXPLORE_PROMPT = r'''
Repair the failed PySCIPOpt optimization program so it reaches the stated objective.

### Problem description
{problem_description}

### Failed attempts and execution feedback
{failed_attempts}

### Proxy objective value
{ground_truth}

The `data` variable is pre-loaded. Do not read files or redefine it. Return ONLY one complete fenced Python code block using `from pyscipopt import Model, quicksum` and `model = Model()`.
Define dictionaries Q, sales, I, W, lost, sub, X with tuple keys and call `model.optimize()` at top level. Do not repeat text or include explanations.
'''

DEBUG_PROGRAM_PROMPT = r'''
Diagnose and repair this PySCIPOpt program using the execution error.

### Failed program
{failed_program}

### Execution feedback
{feedback}

Return ONLY one complete fenced Python code block. Keep valid business logic, use `from pyscipopt import Model, quicksum` and `model = Model()`, and call `model.optimize()` at top level.
The `data` variable is pre-loaded. Define dictionaries Q, sales, I, W, lost, sub, X with tuple keys. Do not read files or include explanations.
'''

DATA_PRELUDE = "import json\ndata = json.loads(open('data.json').read())\n\n"
REQUIRED_TABLES = {"Q", "sales", "I", "W", "lost", "sub", "X"}


def validate_program(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except (SyntaxError, TypeError, ValueError) as exc:
        return [f"invalid_python:{type(exc).__name__}:{exc}"]
    errors = []
    assigned = set()
    optimize_calls = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            assigned.add(node.id)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Name) \
                and node in tree.body and not isinstance(node.value, ast.Str):
            errors.append(f"placeholder_expression:{node.value.id}")
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "optimize":
            optimize_calls += 1
    missing = sorted(REQUIRED_TABLES - assigned)
    if missing:
        errors.append("missing_tables:" + ",".join(missing))
    if optimize_calls != 1:
        errors.append(f"optimize_calls:{optimize_calls}")
    if "gurobipy" in code or "gp.Model" in code:
        errors.append("gurobi_residual")
    if "placeholder" in code.casefold():
        errors.append("draft_placeholder")
    return errors


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n")


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def retail_rows(path: Path, limit: int) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return rows[:limit] if limit else rows


def convert_tasks(rows: list[dict], destination: Path) -> None:
    tasks = []
    for row in rows:
        description = row["prompt_schema"].split("[OUTPUT FORMAT]", 1)[0]
        tasks.append({"task_id": row["scenario_id"], "description": description,
                      "ground_truth": row["reference_objective"], "correct_program": None,
                      "tag": row["scenario_id"].split("_")[1], "cluster": row["scenario_id"].rsplit("_", 1)[0]})
    write_json(destination, tasks)


def current_execution(code: str, timeout_sec: int = 620):
    global EXECUTION_COUNTER
    task = CONTEXT.task
    row = CONTEXT.row
    iteration = CONTEXT.iteration
    output_path = Path(CONTEXT.output_path)
    if "model.optimize" in code and "solution.json" not in code:
        code = code.rstrip() + SCIP_FOOTER
    if "json.loads(open('data.json').read())" not in code and 'json.loads(open("data.json").read())' not in code:
        code = DATA_PRELUDE + code
    with EXECUTION_LOCK:
        EXECUTION_COUNTER += 1
        execution_id = EXECUTION_COUNTER
    digest = digest_text(code)
    sandbox = output_path / "executions" / f"iter_{iteration}" / f"{execution_id:05d}_{digest[:12]}"
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "gen.py").write_text(code)
    contract_errors = validate_program(code)
    if contract_errors:
        record = {"task_id": task.id, "iteration": iteration, "code_sha256": digest,
                  "exec_status": "invalid_program", "solver_status": None, "objective": None,
                  "executable": False, "proxy_match": False, "true_correct": False,
                  "phantom": False, "phantom_proxy": False, "grade": "invalid_program",
                  "witness": "no_solution", "check_verdicts": {"L1_execution": "fail",
                  "L2_retail_witness": "unknown", "L2_initial_inventory": "unknown",
                  "L2_demand_balance": "unknown"}, "contract_errors": contract_errors,
                  "wall_seconds": 0.0}
        CONTEXT.last_record = record
        write_json(sandbox / "alphaopt_execution.json", record)
        return "Invalid program: " + ";".join(contract_errors)
    row_path = sandbox / "row.json"
    write_json(row_path, row)
    started = time.monotonic()
    try:
        completed = subprocess.run([RL_PYTHON, str(ROOT / "scripts/retailopt_rollout_worker.py"),
                                    "--row", str(row_path), "--sandbox", str(sandbox)],
                                   cwd=ROOT, capture_output=True, text=True, timeout=timeout_sec + 80)
    except subprocess.TimeoutExpired:
        return subprocess.TimeoutExpired(cmd="alphaopt_retailopt", timeout=timeout_sec)
    rollout_path = sandbox / "rollout.json"
    if rollout_path.exists():
        record = json.loads(rollout_path.read_text())
    else:
        record = {"executable": False, "proxy_match": False, "true_correct": False,
                  "phantom": False, "phantom_proxy": False,
                  "exec_status": "runner_error", "solver_status": None, "objective": None,
                  "grade": "runner_error", "witness": "runner_error",
                  "check_verdicts": {"L1_execution": "fail", "L2_retail_witness": "unknown"},
                  "worker_stderr": completed.stderr[-1000:]}
    reference = row.get("reference_objective")
    objective = record.get("objective")
    official_optimal = bool(isinstance(objective, (int, float)) and reference is not None
                            and abs(objective - reference) <= 0.1)
    record["proxy_match"] = official_optimal
    record["true_correct"] = record.get("witness") == "feasible" and official_optimal
    record["phantom_proxy"] = record.get("witness") == "infeasible" and official_optimal
    record.update(task_id=task.id, iteration=iteration, code_sha256=digest,
                  wall_seconds=round(time.monotonic() - started, 3))
    CONTEXT.last_record = record
    rejection_reasons = []
    if GOVERNOR is not None:
        verdicts = record.get("check_verdicts") or {}
        if RULE_MODE in {"r2", "both"} and task.id in ATTEMPT_HISTORY:
            allowed, reasons = GOVERNOR.repair_allowed(0, ATTEMPT_HISTORY[task.id], verdicts)
            rejection_reasons.extend(reasons)
        accepted, final_reasons = GOVERNOR.final_accept(verdicts)
        rejection_reasons.extend(final_reasons)
        record["governance_rejected"] = rejection_reasons
        if not rejection_reasons:
            ATTEMPT_HISTORY[task.id] = verdicts
            if RULE_MODE in {"r1", "both"} and "C-DEMAND" in (record.get("witness_rules") or []) \
                    and "L2_demand_balance" not in GOVERNOR.checks:
                from ora_agent.verification_governance import CheckAsset, verbatim_source
                from scripts.retailopt_governance import demand_balance_eval, trusted_cases
                source = verbatim_source("Demand fulfillment equation:", row["prompt_schema"])
                GOVERNOR.register(CheckAsset("L2_demand_balance", 2, demand_balance_eval, source))
                GOVERNOR.promote("L2_demand_balance", trusted_cases(AUDIT_MANIFEST, "demand"))
    write_json(sandbox / "alphaopt_execution.json", record)
    print(f"[{task.id}][iter={iteration}] proxy={record['proxy_match']} "
          f"true={record['true_correct']} phantom={record['phantom']} "
          f"veto={bool(rejection_reasons)}", flush=True)
    if rejection_reasons:
        return "Governance rejected: " + ";".join(rejection_reasons)
    if record.get("exec_status") == "timeout":
        return subprocess.TimeoutExpired(cmd="alphaopt_retailopt", timeout=timeout_sec)
    objective = record.get("objective")
    if isinstance(objective, (int, float)):
        return objective
    stdout = sandbox / "stdout.txt"
    stderr = sandbox / "stderr.txt"
    return (stdout.read_text() if stdout.exists() else "") + (stderr.read_text() if stderr.exists() else "")


def configure_official(outdir: Path, train_path: Path, iterations: int, max_verify: int,
                       start_iter: int = 0) -> None:
    config = {
        "base_model": "Qwen3_8-27B", "advanced_model": "Qwen3_8-27B",
        "base_service": None, "advanced_service": None, "verbose": False,
        "start_iter": start_iter, "data_slice": None,
        "api_keys": {"OPEN_ROUTER_KEY": None, "GEMINI_API_KEY": None, "OPENAI_API_KEY": None},
        "params": {"num_iterations": iterations, "batch_size": 12, "tolerance": 0.1,
                   "max_solution_attempts": 1, "max_verify_attempts": max_verify, "variant_num": 2},
        "dataset": "retailopt", "output_folder": "official_alphaopt",
        "file_paths": {"train_data_path": str(train_path),
                       "train_output_dir": str(outdir / "learning"),
                       "lib_dir": str(outdir / "library"),
                       "metrics_log_path": str(outdir / "learning" / "iteration_metrics.json")},
        "ablation": {"taxonomy": True, "rewrite": False, "include_example": True,
                     "include_program_insight": True, "max_debug_retry": 1},
        "pricing": {},
    }
    import yaml
    (outdir / "train_config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))


def patch_official(rule_mode: str = "none", audit_manifest: dict | None = None) -> None:
    global GOVERNOR, AUDIT_MANIFEST, RULE_MODE
    RULE_MODE = rule_mode
    AUDIT_MANIFEST = audit_manifest
    ATTEMPT_HISTORY.clear()
    if rule_mode != "none":
        from scripts.retailopt_governance import build_governor
        GOVERNOR = build_governor(audit_manifest, include_demand=False)
    import httpx
    from openai import OpenAI
    import src.utils as utils
    import src.llm_programmer as programmer
    import src.llm_diagnostic as diagnostic
    import src.train_eval_utils as train_utils
    import main as official_main
    from scripts.m1_pilot import extract_code

    def qwen_client(model: str, service: str):
        client = OpenAI(api_key=os.environ["ORA_LLM_API_KEY"],
                        base_url=os.environ["ORA_LLM_BASE_URL"], timeout=180.0, max_retries=1,
                        http_client=httpx.Client(verify=False, trust_env=False))
        original_create = client.chat.completions.create

        def create_with_budget(**kwargs):
            global LLM_COUNTER
            kwargs.setdefault("max_tokens", 16384)
            kwargs["frequency_penalty"] = 0.0
            kwargs.setdefault("extra_body", {"reasoning_effort": "medium"})
            response = original_create(**kwargs)
            with EXECUTION_LOCK:
                LLM_COUNTER += 1
                request_id = LLM_COUNTER
            if RAW_OUTDIR is not None:
                write_json(RAW_OUTDIR / "llm_raw" / f"request_{request_id:05d}.json",
                           json.loads(response.model_dump_json()))
            return response

        client.chat.completions.create = create_with_budget
        return "openai", client

    class RetailProgramGenerator(programmer.ProgramGenerator):
        def generate_program(self, iter=None, task=None, retrieved_insights=None, formulation=None,
                             abl_params=False, verbose=False, save_data=False, output_path="learning"):
            CONTEXT.task = task
            CONTEXT.row = CONTEXT_ROWS[task.id]
            CONTEXT.iteration = iter
            CONTEXT.output_path = output_path
            fields = ["insight_id", "explanation"]
            if abl_params.include_example:
                fields.append("example")
            insights = [{key: value for key, value in insight.items() if key in fields}
                        for insight in retrieved_insights]
            base_prompt = PROGRAM_PROMPT.format(problem_description=task.desc,
                                                mathematical_model=formulation,
                                                insights=json.dumps(insights, indent=2, ensure_ascii=False))
            feedback_prompt = base_prompt
            for attempt in range(1, 6):
                program = utils.call_llm_and_parse_with_retry(
                    model=self.model, service=self.service, prompt=feedback_prompt,
                    parse_fn=self.extract_code, temperature=self.temp, max_retry=1,
                    sleep_sec=0.5, verbose=verbose,
                    log_header=f"\n[Program generation task {task.id}, attempt {attempt}]\n",
                    error_message=f"Task {task.id} failed to generate a valid program")
                if not program:
                    continue
                errors = validate_program(program)
                if errors:
                    print(f"[{task.id}] invalid program attempt {attempt}: {errors}", flush=True)
                    if save_data:
                        invalid_path = Path(output_path) / f"invalid_program_iter_{iter}_attempt_{attempt}.py"
                        invalid_path.parent.mkdir(parents=True, exist_ok=True)
                        invalid_path.write_text(program)
                    feedback_prompt = (base_prompt + "\n\n[PREVIOUS INVALID DRAFT]\n" + program[:12000]
                                       + "\n\n[VALIDATION ERRORS]\n" + json.dumps(errors, ensure_ascii=False)
                                       + "\nRewrite the COMPLETE final program. Fix every listed error, remove all draft commentary and placeholders, and close the code fence.")
                    continue
                if save_data:
                    destination = Path(output_path) / f"program_iter_{iter}.py"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(program)
                output = self.execute_code(program)
                record = getattr(CONTEXT, "last_record", {})
                return program, output, record.get("exec_status") in {"ok", "timeout"}, \
                    record.get("exec_status") == "timeout"
            return None, None, None, None

        def extract_code(self, text: str, formatted_output: str = None) -> str:
            return extract_code(text)

        def execute_code(self, code_str, timeout_sec=620):
            return current_execution(code_str, timeout_sec)

    class RetailProgramDiagnostic(__import__("src.llm_diagnostic", fromlist=["ProgramDiagnostic"]).ProgramDiagnostic):
        def debug_program(self, *args, **kwargs):
            CONTEXT.task = kwargs["task"]
            CONTEXT.row = CONTEXT_ROWS[CONTEXT.task.id]
            CONTEXT.iteration = kwargs.get("iter", 0)
            CONTEXT.output_path = kwargs.get("output_path", "learning")
            return super().debug_program(*args, **kwargs)

        def execute_code(self, file_path, timeout_sec=620):
            return current_execution(Path(file_path).read_text(), timeout_sec)

    utils._build_client = qwen_client
    programmer.PROMPT_GENERATE_FORMU = FORMULATION_PROMPT
    programmer.PROMPT_GENERATE_PROGRAM = PROGRAM_PROMPT
    programmer.PROMPT_SELF_EXPLORE = SELF_EXPLORE_PROMPT
    diagnostic.PROMPT_PROGRAM_DIAG = DEBUG_PROGRAM_PROMPT
    train_utils.execute_code = current_execution
    official_main.ProgramGenerator = RetailProgramGenerator
    official_main.ProgramDiagnostic = RetailProgramDiagnostic


def summarize_execution_records(outdir: Path) -> dict:
    records = []
    for path in outdir.glob("learning/**/executions/iter_*/**/alphaopt_execution.json"):
        record = json.loads(path.read_text())
        record["artifact"] = str(path.relative_to(outdir))
        records.append(record)
    iterations = {}
    for record in records:
        iterations.setdefault(record["iteration"], []).append(record)
    curves = []
    for iteration, group in sorted(iterations.items()):
        curves.append({"iteration": iteration, "n": len(group),
                       "executable": sum(record["executable"] for record in group),
                       "proxy_match": sum(record["proxy_match"] for record in group),
                       "true_correct": sum(record["true_correct"] for record in group),
                       "phantom": sum(record["phantom"] for record in group),
                       "phantom_proxy": sum(record["phantom_proxy"] for record in group),
                       "governance_rejected": sum(bool(record.get("governance_rejected")) for record in group)})
    return {"curves": curves, "n_rollouts": len(records), "rollouts": records,
            "official_check_optimality": "numeric objective vs ground_truth; optional governance prefilter",
            "witness_used_for_optimality": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--task-id")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--max-verify-attempts", type=int, default=1)
    parser.add_argument("--rule-mode", choices=("none", "r1", "r2", "both"), default="none")
    parser.add_argument("--governance-cases", default="work/retailopt_governance_smoke_v0.2/cases.json")
    parser.add_argument("--start-iter", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    global CONTEXT_ROWS, RAW_OUTDIR, EXECUTION_COUNTER, LLM_COUNTER
    outdir = (ROOT / args.run_dir).resolve()
    if outdir.exists() and any(outdir.iterdir()) and not args.resume:
        raise ValueError("run directory must be empty")
    if args.resume and args.start_iter <= 0:
        raise ValueError("--resume requires --start-iter > 0")
    if args.start_iter > args.iterations:
        raise ValueError("start_iter exceeds total iterations")
    if args.start_iter > 0:
        required = [outdir / "learning" / f"train_tasks_record_diag_iter{args.start_iter - 1}.json",
                    outdir / "library" / f"library_refine_iter{args.start_iter - 1}.json",
                    outdir / "library" / f"latest_taxonomy_diag_iter{args.start_iter - 1}.json",
                    outdir / "learning" / "iteration_metrics.json"]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise ValueError("missing checkpoint artifacts: " + ", ".join(missing))
    RAW_OUTDIR = outdir
    EXECUTION_COUNTER = len(list(outdir.glob("learning/**/alphaopt_execution.json")))
    LLM_COUNTER = len(list(outdir.glob("llm_raw/request_*.json")))
    (outdir / "learning").mkdir(parents=True, exist_ok=True)
    (outdir / "library").mkdir(parents=True, exist_ok=True)
    rows = retail_rows(ROOT / "data/m1_retailopt/dev40_f1f4.jsonl", args.limit)
    if args.task_id:
        rows = [row for row in rows if row["scenario_id"] == args.task_id]
        if len(rows) != 1:
            raise ValueError(f"unknown or non-unique task id: {args.task_id}")
    CONTEXT_ROWS = {row["scenario_id"]: row for row in rows}
    train_path = outdir / "retailopt_tasks.json"
    convert_tasks(rows, train_path)
    configure_official(outdir, train_path, args.iterations, args.max_verify_attempts, args.start_iter)
    audit_manifest = (json.loads((ROOT / args.governance_cases).read_text())
                      if args.rule_mode != "none" else None)
    write_json(outdir / "manifest.json", {"official_alphaopt_commit": ALPHAOPT_COMMIT,
                                          "protocol_sha256": digest_text(PROTOCOL.read_text()),
                                          "train_ids": list(CONTEXT_ROWS), "rule_mode": args.rule_mode,
                                          "start_iter": args.start_iter,
                                          "official_check_optimality": "objective-only",
                                          "witness_used_for_optimality": False})
    if not (outdir / "data").exists():
        (outdir / "data").symlink_to(ALPHAOPT / "data", target_is_directory=True)
    os.chdir(outdir)
    sys.path.insert(0, str(ALPHAOPT))
    sys.path.insert(0, str(ROOT))
    patch_official(args.rule_mode, audit_manifest)
    import main as official_main
    official_main.main()
    if GOVERNOR is not None:
        GOVERNOR.freeze()
        write_json(outdir / "governor.json", GOVERNOR.public_state())
    analysis = summarize_execution_records(outdir)
    analysis["rule_mode"] = args.rule_mode
    write_json(outdir / "analysis.json", analysis)
    print(json.dumps({key: value for key, value in analysis.items() if key != "rollouts"}, indent=1))


if __name__ == "__main__":
    main()

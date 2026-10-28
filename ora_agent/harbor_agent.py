"""Harbor BaseAgent subclass wiring ora_agent's loop into Harbor trials.

Run with:
    PYTHONPATH=/home/hewj13/wm/ora harbor run -p <task_dir> \
        -a ora_agent.harbor_agent:OrAgent -m qwen3.8-27b

LLM credentials come from the process environment (ORA_LLM_BASE_URL /
ORA_LLM_API_KEY / ORA_LLM_MODEL), optionally overridden per-agent via the
job yaml's agents[].env block (harbor resolves ${VAR} templates there).
Keys are never written to logs or trajectories.

Agent kwargs (job yaml agents[].kwargs or --ak key=value):
    max_steps, token_budget, temperature, max_tokens, exec_timeout_sec,
    predict_mode (off|shadow|active; env ORA_PREDICT_MODE as fallback).

Outputs land under <trial logs_dir>/ora/: trajectory.jsonl, predictions/,
outcomes/, env_info.json.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.agents.capabilities import AgentCapabilities
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from . import __version__, llm as llm_mod
from .loop import LoopConfig, run_loop
from .predict import PredictionRecorder, make_predictor
from .trajectory import TrajectoryWriter

SYSTEM_PROMPT = """\
You are an expert operations-research agent solving one ORAgentBench task inside a Linux container.

You act through tools. Exactly ONE action per turn: either one `bash` call or one `finish` call.

Tools:
- bash(command, action_kind, rationale, timeout_sec?): run a bash command in the container (working directory /app).
  - action_kind must be one of: recon (reading problem/data), model (writing model.md), code (writing solve.py), solve (running the solver), validate (checking outputs against the required schema), repair (fixing failures), other.
  - rationale: 1-3 sentences on why this action now.
  - timeout_sec: optional per-command timeout (default 360s, max 600s). Each solver run must internally respect a 300s time limit (ORCLAW_SOLVE_TIME_LIMIT_SECONDS).
- finish(summary): call only when all required artifacts exist and have been validated.

Workflow (the task instruction below is authoritative; this is the expected shape):
1. recon: read /app/PROBLEM_STATEMENT.md and every file under /app/data/ before doing anything else.
2. model: write the complete mathematical model to /app/submissions/model.md BEFORE finalizing code. Choose the formulation deliberately (assignment / flow / set partitioning / time-indexed / scheduling / routing / decomposition ...) instead of defaulting to a naive one.
3. code: implement /app/submissions/solve.py (PySCIPOpt is available; also pyomo, numpy, pandas, scipy, networkx). It must solve from scratch via `python /app/submissions/solve.py`.
4. solve: run it with SCIP relative gap 0.0005 and a per-attempt time limit of at most 300s.
5. validate: verify the solution file under /app/submissions/ matches the task schema (solution.csv or solution.json) and that the solution is feasible by actually checking it.
6. repair: fix issues and iterate. Guarantee feasibility and schema correctness first; only then improve objective quality. Prefer targeted refinements over repeated full solves.
7. Keep /app/submissions/solve_log.md up to date with commands run, solver status, observed objective/score, and validation checks.

Required artifacts (all under /app/submissions/): model.md, solve.py, solve_log.md, and solution.csv or solution.json per the task schema.

Hard rules:
- Never fabricate results: only report solver statuses, objectives, and validation outcomes you actually observed in command output. Never invent numbers for solve_log.md or solution files.
- Reusable OR skills (modeling patterns, solver repair, PySCIPOpt guidance) are mounted under /skills; read the relevant SKILL.md files early (e.g. `ls /skills; cat /skills/*/SKILL.md`) and apply them.
- Do not use the internet, package registries, or any remote data.
- Work only inside /app. Do not search for, read, or execute anything outside /app (in particular no hidden evaluator, tests, or reference solution files).
- First make the submission feasible and schema-correct and reproducible from scratch; then improve quality within the remaining budget.
- When done, call finish(summary) with an honest summary: what was produced, observed objective/status, and known limitations.
"""


def _coerce_int(value, default: int) -> int:
    if value is None:
        return default
    return int(value)


def _coerce_float(value, default: float) -> float:
    if value is None:
        return default
    return float(value)


class OrAgent(BaseAgent):
    """End-to-end OR agent: Qwen LLM + single bash tool + shadow predictor."""

    # Task packages mount reusable OR skills at /skills in the container;
    # our agent discovers them through the prompt and reads them via bash.
    capabilities = AgentCapabilities(skills=True)

    def __init__(self, *args, max_steps=None, token_budget=None, temperature=None,
                 predict_mode=None, max_tokens=None, exec_timeout_sec=None, **kwargs):
        self._ora_max_steps = _coerce_int(max_steps, LoopConfig.max_steps)
        self._ora_token_budget = _coerce_int(token_budget, LoopConfig.token_budget)
        self._ora_temperature = _coerce_float(temperature, LoopConfig.temperature)
        self._ora_max_tokens = _coerce_int(max_tokens, LoopConfig.max_tokens)
        self._ora_exec_timeout = _coerce_int(exec_timeout_sec, LoopConfig.exec_timeout_sec)
        # Guard against YAML 1.1 parsing bare `off` as boolean False.
        if predict_mode in (None, False):
            self._ora_predict_mode = None
        else:
            self._ora_predict_mode = str(predict_mode)
        super().__init__(*args, **kwargs)

    @staticmethod
    def name() -> str:
        return "ora-agent"

    def version(self) -> str | None:
        return __version__

    async def setup(self, environment: BaseEnvironment) -> None:
        """No installation needed; just record environment facts for the trail."""
        info: dict = {"agent": self.name(), "version": self.version()}
        try:
            r = await environment.exec(
                "python --version 2>&1; echo ---; ls /app 2>&1; echo ---; "
                "echo ORCLAW_SOLVE_TIME_LIMIT_SECONDS=$ORCLAW_SOLVE_TIME_LIMIT_SECONDS",
                timeout_sec=60,
            )
            info["recon"] = {
                "return_code": r.return_code,
                "stdout": (r.stdout or "")[:2000],
                "stderr": (r.stderr or "")[:1000],
            }
        except Exception as e:
            info["recon_error"] = f"{type(e).__name__}: {e}"
        out_dir = Path(self.logs_dir) / "ora"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "env_info.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    async def run(self, instruction: str, environment: BaseEnvironment,
                  context: AgentContext) -> None:
        out_dir = Path(self.logs_dir) / "ora"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Agent env (job yaml agents[].env, ${VAR}-resolved by harbor) takes
        # precedence over the process environment.
        env = {**os.environ, **self._extra_env}
        llm_config = llm_mod.load_config(env)  # clear error if env is missing
        model = self.model_name or llm_config.model
        if "/" in model:  # harbor convention provider/model; our endpoint wants the bare id
            model = model.split("/", 1)[1]
        llm_config = llm_config.with_model(model)

        session = self.session_id or f"ora-{uuid.uuid4().hex[:12]}"
        task_id = session.split("__")[0] if "__" in session else session
        run_id = session

        def llm_fn(messages, **kw):
            return llm_mod.chat(messages, config=llm_config, **kw)

        predict_mode = self._ora_predict_mode or env.get("ORA_PREDICT_MODE", "off")
        predictor = make_predictor(predict_mode, llm_fn)

        async def exec_fn(command: str, timeout_sec: int) -> dict:
            r = await environment.exec(command=command, cwd="/app",
                                       timeout_sec=timeout_sec)
            return {"stdout": r.stdout or "", "stderr": r.stderr or "",
                    "return_code": r.return_code}

        with TrajectoryWriter(out_dir / "trajectory.jsonl", run_id=run_id,
                              task_id=task_id, model=model) as writer:
            recorder = PredictionRecorder(out_dir, writer=writer, predictor=predictor)
            config = LoopConfig(
                max_steps=self._ora_max_steps,
                token_budget=self._ora_token_budget,
                temperature=self._ora_temperature,
                max_tokens=self._ora_max_tokens,
                exec_timeout_sec=self._ora_exec_timeout,
            )
            result = await run_loop(
                system_prompt=SYSTEM_PROMPT,
                instruction=instruction,
                config=config,
                llm_fn=llm_fn,
                exec_fn=exec_fn,
                writer=writer,
                recorder=recorder,
                model=model,
            )

        context.n_input_tokens = result.usage["prompt_tokens"]
        context.n_output_tokens = result.usage["completion_tokens"]
        context.metadata = {
            "ora_agent": {
                "version": __version__,
                "status": result.status,
                "n_steps": result.n_steps,
                "n_llm_calls": result.n_llm_calls,
                "finish_summary": result.finish_summary,
                "usage": dict(result.usage),
                "predict_mode": predictor.mode,
                "model": model,
                "trajectory": str(out_dir / "trajectory.jsonl"),
            }
        }

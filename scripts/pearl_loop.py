#!/usr/bin/env python3
"""pearl_loop.py — PEARL-4B native solver-in-the-loop runner.

Replicates the exact GRPO training protocol recovered from way2m's
smoke_train.log (2026-09-18): system prompt verbatim, <code> ->
<interpreter> feedback, <answer> final block, Pyomo+GLPK contract.

The runner is model-agnostic: any OpenAI-compatible endpoint serving a
PEARL-style checkpoint works (pearl-qwen3-4b-instruct-2507, fancc3, ...).

Usage (inside workspace, proxy @8340):
  python3 scripts/pearl_loop.py --data data/m1_retailopt/f5f8_heldout90.jsonl \
      --base-url http://127.0.0.1:8340/v1 --model pearl-qwen3-4b-instruct-2507 \
      --limit 2 --out work/pearl_pilot/run1.jsonl
"""
import argparse, hashlib, json, os, re, ssl, subprocess, sys, tempfile, time, urllib.request, urllib.error

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

SYSTEM_PROMPT = """You are an optimization modeling agent.

Goal:
- Convert the user problem statement into a correct optimization model and a runnable Python implementation.
- Use Python tool calls to compute, sanity-check, and verify your formulation when needed.

- The final code must be verified runnable, and you must validate the optimal value/solution against the problem statement: check all constraints are satisfied and no requirement is violated.

Modeling notes:
- Check variable meaning: if x is a quantity (integer/continuous), do NOT use binary-only logic like x_i + x_j <= 1.
- For logical constraints about whether a product is produced (x_i > 0), introduce indicator y_i in {0,1}.
- Link quantity and indicator with tight bounds: x_i <= M_i * y_i; add x_i >= y_i only if selecting implies x_i >= 1.
- Encode implications with indicators: (A => B) becomes y_A <= y_B; (A => not B) becomes y_A + y_B <= 1.
- Choose M_i as small as possible using known bounds (e.g., from resource constraints) to keep the MIP stable.
- Carefully distinguish variable types. Common nouns -> types: amount/production/flow/distance/time/cost = nonnegative continuous; counts (trips/machines/workers/vehicles/orders/batches) = nonnegative integer; yes/no decisions (select/open/visit/build) = binary; assignment/matching/edge-used (i->j) = binary; sequence/rank = integer (with subtour-elimination / uniqueness constraints).
- Keep units consistent across constraints (e.g., hours vs. units, kg vs. g); unit mistakes often cause 10x/1000x objective gaps.
- Implementation sanity: check solver termination is optimal before reading values; access indexed vars as model.x[i] (not getattr).
Implementation requirement:
- Use Pyomo to implement and solve the optimization model. Your code should follow this skeleton:
from pyomo.environ import *

model = ConcreteModel()

# Solve
You may use SolverFactory('glpk') for linear/MIP problems.
You may use SolverFactory('ipopt') for nonlinear programming (NLP).
solver = SolverFactory('ipopt')
results = solver.solve(model)

Tool calling:
- When you need to run Python, output exactly:
<code>
...python code...
</code>
- After a tool call, you will receive the execution result inside:
<interpreter>
...tool output...
</interpreter>
- You may call the tool multiple times.

Final answer:
- When you are done, output exactly one final block:
<answer>
# Modeling: 
define decision variables, objective, constraints (clear and complete).
# Implementation: 
include runnable code wrapped as:
```python
...python code...
```
</answer>
"""

CONTRACT_NOTE = """# Note:
- The Code must include:```python

import pyomo.environ as pyo
```
- Make sure the model variable is named `model`.
- Build the model with Pyomo and solve it with GLPK: `pyo.SolverFactory('glpk')`. gurobipy is NOT available in the execution environment.
- Avoid using "<" and ">" in constraints; instead, use "<=" or ">=" as appropriate.
- Carefully determine whether the variable is an integer or a continuous variable."""


def chat(base_url, model, messages, max_tokens=8192, temperature=0.0, timeout=600,
         api_key=None):
    body = json.dumps({
        "model": model, "messages": messages,
        "max_tokens": max_tokens, "temperature": temperature,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:500]
        raise RuntimeError(f"HTTP {e.code}: {detail}") from e
    return out["choices"][0]["message"]["content"] or ""


CODE_RE = re.compile(r"<code>\s*(.*?)\s*</code>", re.S)
ANSWER_RE = re.compile(r"<answer>\s*(.*?)\s*</answer>", re.S)
FENCE_RE = re.compile(r"```python\s*\n(.*?)```", re.S)


def extract_code(text):
    m = CODE_RE.search(text)
    return m.group(1) if m else None


def extract_answer_code(answer_block):
    m = FENCE_RE.search(answer_block)
    return m.group(1) if m else None


OBJ_PATTERNS = [
    re.compile(r"__SLIME_OPTIMAL_VALUE__\s*=\s*([0-9.eE+-]+)"),
    re.compile(r"[Oo]bjective(?:\s+value)?[^\n]{0,40}?[:=]\s*(-?[0-9][0-9,]*(?:\.[0-9]+)?(?:[eE][+-]?\d+)?)"),
    re.compile(r"[Tt]otal\s+cost[^\n]{0,30}?[:=]\s*\$?\s*(-?[0-9][0-9,]*(?:\.[0-9]+)?(?:[eE][+-]?\d+)?)"),
]


def parse_exec(result):
    """Extract solver status and objective from an exec result string."""
    status = None
    low = result.lower()
    if "termination condition: optimal" in low or "status: optimal" in low \
            or "termination_condition: optimal" in low:
        status = "optimal"
    elif "infeasible" in low:
        status = "infeasible"
    elif "timed out" in low:
        status = "timeout"
    elif "error" in low or "traceback" in low:
        status = "error"
    obj = None
    for pat in OBJ_PATTERNS:
        m = pat.search(result)
        if m:
            try:
                obj = float(m.group(1).replace(",", ""))
            except ValueError:
                pass
            break
    return status, obj


def run_code(code, python_bin, timeout_s=600, extra_files=None):
    workdir = tempfile.mkdtemp()
    path = os.path.join(workdir, "code.py")
    with open(path, "w") as f:
        f.write(code)
    for name, content in (extra_files or {}).items():
        with open(os.path.join(workdir, name), "w") as f:
            f.write(content)
    try:
        p = subprocess.run([python_bin, "code.py"], capture_output=True,
                           text=True, timeout=timeout_s, cwd=workdir)
        out = p.stdout.strip()
        if p.returncode != 0:
            err = p.stderr.strip()
            return f"Output:\n{out}\nError: Process exited with code {p.returncode}\n{err}"[:6000]
        return f"Output:\n{out}"[:6000]
    except subprocess.TimeoutExpired:
        return f"Error: Code execution timed out after {timeout_s} seconds"
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


DATAFILE_NOTE = ("\n- The instance data is also stored as a JSON file at "
                 "'data.json' (relative path, already in the working "
                 "directory). PREFER loading it with "
                 "`data = json.load(open('data.json'))` instead of retyping "
                 "numeric values from the problem statement.")

DATAFILE_NOTE_MANDATORY = (
    "\n- The instance data is NOT included in this prompt. It is ONLY "
    "available as a JSON file at 'data.json' (relative path, already in "
    "the working directory). You MUST load it with "
    "`data = json.load(open('data.json'))`. Do NOT invent or retype any "
    "numeric parameters.")

DATA_BLOCK_RE = re.compile(r"\[DATA\].*?(?=\[OUTPUT FORMAT\])", re.S)


def strip_data_block(prompt_full, data_record):
    """Remove the embedded [DATA] JSON block; data.json becomes the only source."""
    keys = ", ".join(data_record.keys())
    replacement = ("[DATA]\nThe instance data is provided as 'data.json' in "
                   "the working directory. Load it with "
                   "`json.load(open('data.json'))`. Top-level keys: "
                   + keys + "\n\n")
    return DATA_BLOCK_RE.sub(replacement, prompt_full)


def pearl_loop(problem_text, base_url, model, python_bin,
               max_turns=6, timeout_s=600, max_tokens=8192, api_key=None,
               data_record=None, data_mandatory=False):
    contract = CONTRACT_NOTE
    extra_files = None
    if data_record is not None:
        contract += DATAFILE_NOTE_MANDATORY if data_mandatory else DATAFILE_NOTE
        extra_files = {"data.json": json.dumps(data_record)}
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "# Question:" + problem_text + "\n\n" + contract},
    ]
    transcript, seen_codes = [], set()
    final_answer, final_code, stop_reason = None, None, "max_turns"
    last_status, last_obj = None, None
    for turn in range(1, max_turns + 1):
        t0 = time.time()
        reply = chat(base_url, model, messages, max_tokens=max_tokens,
                     api_key=api_key)
        messages.append({"role": "assistant", "content": reply})
        ans = ANSWER_RE.search(reply)
        code = extract_code(reply)
        transcript.append({"turn": turn, "reply_len": len(reply),
                           "has_code": bool(code), "has_answer": bool(ans),
                           "latency_s": round(time.time() - t0, 1)})
        if ans:
            final_answer = ans.group(1)
            final_code = extract_answer_code(final_answer)
            stop_reason = "answer"
            if final_code:
                result = run_code(final_code, python_bin, timeout_s,
                                  extra_files)
                last_status, last_obj = parse_exec(result)
                transcript[-1]["final_exec"] = result[:3000]
                transcript[-1]["exec_status"] = last_status
                transcript[-1]["objective"] = last_obj
            break
        if not code:
            stop_reason = "no_code_no_answer"
            break
        h = hashlib.md5(code.encode()).hexdigest()
        if h in seen_codes:
            stop_reason = "repeat_circuit_break"
            break
        seen_codes.add(h)
        result = run_code(code, python_bin, timeout_s, extra_files)
        st, ob = parse_exec(result)
        if st:
            last_status, last_obj = st, ob if ob is not None else last_obj
        transcript[-1]["exec"] = result[:3000]
        transcript[-1]["exec_status"] = st
        transcript[-1]["objective"] = ob
        messages.append({"role": "user",
                         "content": f"<interpreter>\n{result}\n</interpreter>"})
    return {"stop_reason": stop_reason, "turns": len(transcript),
            "final_answer": final_answer, "final_code": final_code,
            "last_exec_status": last_status, "last_objective": last_obj,
            "transcript": transcript, "messages": messages}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base-url", default="http://127.0.0.1:8340/v1")
    ap.add_argument("--model", default="pearl-qwen3-4b-instruct-2507")
    ap.add_argument("--python-bin", default="/dfs/share-groups/letrain/hewenji/envs/pearl-slime/bin/python")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-turns", type=int, default=6)
    ap.add_argument("--timeout-s", type=int, default=600)
    ap.add_argument("--api-key", default=os.environ.get("PEARL_API_KEY"))
    ap.add_argument("--data-file", action="store_true",
                    help="provision data.json in sandbox cwd and prefer it")
    ap.add_argument("--strip-data", action="store_true",
                    help="remove embedded [DATA] block; data.json is the only source")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.data)]
    if args.limit:
        rows = rows[: args.limit]
    done = set()
    if os.path.exists(args.out):
        done = {json.loads(l)["scenario_id"] for l in open(args.out)}
        rows = [r for r in rows if r["scenario_id"] not in done]
        print(f"resume: {len(done)} done, {len(rows)} to go", flush=True)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    lock = __import__("threading").Lock()

    def work(r):
        sid = r["scenario_id"]
        prompt = r.get("prompt_full") or r.get("prompt_schema")
        data_rec = None
        mandatory = False
        if args.data_file or args.strip_data:
            d = r.get("data")
            data_rec = json.loads(d) if isinstance(d, str) else d
        if args.strip_data:
            prompt = strip_data_block(prompt, data_rec)
            mandatory = True
        t0 = time.time()
        try:
            res = pearl_loop(prompt, args.base_url, args.model,
                             args.python_bin, args.max_turns, args.timeout_s,
                             api_key=args.api_key, data_record=data_rec,
                             data_mandatory=mandatory)
        except Exception as e:
            res = {"stop_reason": f"runner_error: {e}", "turns": 0}
        rec = {"scenario_id": sid, "model": args.model,
               "stop_reason": res["stop_reason"], "turns": res.get("turns"),
               "final_answer": res.get("final_answer"),
               "final_code": res.get("final_code"),
               "last_exec_status": res.get("last_exec_status"),
               "last_objective": res.get("last_objective"),
               "transcript": res.get("transcript"),
               "reference_objective": r.get("reference_objective"),
               "reference_status": r.get("reference_status"),
               "wall_s": round(time.time() - t0, 1)}
        with lock:
            with open(args.out, "a") as fout:
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{sid}] {rec['stop_reason']} turns={rec['turns']} "
              f"status={rec['last_exec_status']} obj={rec['last_objective']} "
              f"wall={rec['wall_s']}s", flush=True)

    if args.workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(work, rows))
    else:
        for r in rows:
            work(r)


if __name__ == "__main__":
    main()

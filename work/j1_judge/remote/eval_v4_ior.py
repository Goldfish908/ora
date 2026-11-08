import os, json, time, glob, argparse, re, subprocess, sys, tempfile

os.environ.setdefault("HF_HOME", "/dfs/data/hewj13/.cache/huggingface")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

# v4 generative eval on IndustryOR cells (instrumented form): same active loop
# as eval_v4.py but with the IndustryOR templates from p13 (constants come from
# the problem text; only solution.json exists, no data.json).
#
# cells file: {key, wrong, prompt, code, objective}
# artifacts dir: ior_sandbox/<key>/solution.json
# prompts file: {"planner":..., "decider":...} (exported from p13)

ap = argparse.ArgumentParser()
ap.add_argument("--adapter", required=True)
ap.add_argument("--cells", required=True)
ap.add_argument("--artifacts", required=True)
ap.add_argument("--prompts", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--batch", type=int, default=4)
ap.add_argument("--max-new-planner", type=int, default=6000)
ap.add_argument("--max-new-decider", type=int, default=4000)
ap.add_argument("--limit", type=int, default=0)
args = ap.parse_args()

SNAP = sorted(glob.glob("/dfs/data/hewj13/.cache/huggingface/hub/models--Qwen--Qwen3.8-27B/snapshots/*/"))[0]
T0 = time.time()


def log(d):
    d["t"] = round(time.time() - T0, 1)
    print(json.dumps(d, ensure_ascii=False), flush=True)


tok = AutoTokenizer.from_pretrained(SNAP)
tok.padding_side = "left"
if tok.pad_token is None:
    tok.pad_token = tok.eos_token

try:
    model = AutoModelForCausalLM.from_pretrained(
        SNAP, dtype=torch.bfloat16, device_map="balanced", attn_implementation="flash_attention_2")
except Exception:
    model = AutoModelForCausalLM.from_pretrained(
        SNAP, dtype=torch.bfloat16, device_map="balanced", attn_implementation="sdpa")
model = PeftModel.from_pretrained(model, args.adapter)
model.eval()
log({"event": "model_ready", "adapter": args.adapter})

PROMPTS = json.load(open(args.prompts))
cells = [json.loads(l) for l in open(args.cells)]
if args.limit:
    cells = cells[: args.limit]


def chat_text(prompt):
    return tok.apply_chat_template(
        [{"role": "system", "content": ""}, {"role": "user", "content": prompt}],
        tokenize=False, add_generation_prompt=True, enable_thinking=False)


@torch.no_grad()
def gen(prompts, max_new):
    outs = []
    for lo in range(0, len(prompts), args.batch):
        texts = [chat_text(p) for p in prompts[lo:lo + args.batch]]
        enc = tok(texts, return_tensors="pt", padding=True,
                  add_special_tokens=False).to(model.device)
        out = model.generate(**enc, max_new_tokens=max_new, do_sample=False,
                             pad_token_id=tok.eos_token_id)
        for i in range(len(texts)):
            outs.append(tok.decode(out[i][enc["input_ids"].shape[1]:],
                                   skip_special_tokens=True))
        log({"event": "gen_batch", "done": lo + len(texts), "of": len(prompts),
             "max_new": max_new})
    return outs


def extract_code(text):
    m = re.findall(r"```python\s*\n(.*?)```", text or "", re.S)
    return m[-1] if m else None


def run_check(script, cell_dir, timeout=30):
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(cell_dir, "solution.json")) as f:
            src = f.read()
        with open(os.path.join(td, "solution.json"), "w") as f:
            f.write(src)
        with open(os.path.join(td, "check.py"), "w") as f:
            f.write(script)
        try:
            p = subprocess.run([sys.executable, "check.py"], cwd=td,
                               capture_output=True, text=True, timeout=timeout)
            out = ((p.stdout or "")
                   + ("\n[stderr]\n" + p.stderr[-600:] if p.returncode else "")).strip()
            return (out or "(no output)")[:4000]
        except subprocess.TimeoutExpired:
            return "[TIMEOUT]"
        except Exception as e:
            return "[EXEC ERROR] %s" % e


def parse_verdict(text):
    m = re.findall(r"VERDICT:\s*(VALID|INVALID)", text or "")
    return m[-1] if m else None


# ---- stage 1: planner ----
planner_prompts, metas = [], []
for c in cells:
    cdir = os.path.join(args.artifacts, c["key"])
    sol_p = os.path.join(cdir, "solution.json")
    if not os.path.exists(sol_p):
        continue
    sol = json.load(open(sol_p))
    varnames = list((sol.get("vars") or {}).keys())
    planner_prompts.append(PROMPTS["planner"].format(
        prompt=c["prompt"], code=c["code"],
        nvar=len(varnames), sample_vars=", ".join(varnames[:8])))
    metas.append(c)
planner_outs = gen(planner_prompts, args.max_new_planner)

# ---- stage 2: sandbox ----
results, decider_prompts = [], []
for c, p_out in zip(metas, planner_outs):
    cdir = os.path.join(args.artifacts, c["key"])
    script = extract_code(p_out)
    rec = {"key": c["key"], "wrong": bool(c["wrong"]),
           "planner_full": p_out, "script": script}
    if not script:
        rec.update({"verdict": None, "error": "no_script"})
        results.append(rec)
        continue
    output = run_check(script, cdir)
    rec["check_output"] = output
    decider_prompts.append(PROMPTS["decider"].format(
        prompt=c["prompt"], code=c["code"], objective=c.get("objective"),
        script=script, output=output))
    rec["_di"] = len(decider_prompts) - 1
    results.append(rec)

# ---- stage 3: decider ----
decider_outs = gen(decider_prompts, args.max_new_decider)
for rec in results:
    di = rec.pop("_di", None)
    if di is None:
        continue
    rec["decider_full"] = decider_outs[di]
    rec["verdict"] = parse_verdict(decider_outs[di])

with open(args.out, "w") as f:
    for r in results:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

tp = sum(1 for r in results if r["wrong"] and r.get("verdict") == "INVALID")
fn = sum(1 for r in results if r["wrong"] and r.get("verdict") != "INVALID")
fp = sum(1 for r in results if not r["wrong"] and r.get("verdict") == "INVALID")
tn = sum(1 for r in results if not r["wrong"] and r.get("verdict") != "INVALID")
log({"event": "summary", "n": len(results), "tp": tp, "fn": fn, "fp": fp, "tn": tn,
     "detection": round(tp / max(tp + fn, 1), 4),
     "false_positive": round(fp / max(fp + tn, 1), 4)})

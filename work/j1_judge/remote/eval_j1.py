import os, json, time, glob, argparse, re

os.environ.setdefault("HF_HOME", "/dfs/data/hewj13/.cache/huggingface")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

ap = argparse.ArgumentParser()
ap.add_argument("--adapter", required=True)
ap.add_argument("--data", required=True)
ap.add_argument("--out", required=True, help="output prefix: <out>.predictions.jsonl / <out>.metrics.json")
ap.add_argument("--batch", type=int, default=4)
ap.add_argument("--max-new", type=int, default=160)
ap.add_argument("--no-gen", action="store_true", help="score-only (skip generation)")
args = ap.parse_args()

SNAP = sorted(glob.glob("/dfs/data/hewj13/.cache/huggingface/hub/models--Qwen--Qwen3.8-27B/snapshots/*/"))[0]
LOG = args.out + ".log.jsonl"
T0 = time.time()


def log(d):
    d["t"] = round(time.time() - T0, 1)
    with open(LOG, "a") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(json.dumps(d, ensure_ascii=False), flush=True)


def mem():
    return {f"gpu{i}": round(torch.cuda.max_memory_allocated(i) / 2**20) for i in range(torch.cuda.device_count())}


tok = AutoTokenizer.from_pretrained(SNAP)
tok.padding_side = "left"
if tok.pad_token is None:
    tok.pad_token = tok.eos_token

t = time.time()
try:
    model = AutoModelForCausalLM.from_pretrained(
        SNAP, dtype=torch.bfloat16, device_map="balanced", attn_implementation="flash_attention_2")
    attn = "flash_attention_2"
except Exception as e:
    print("FA2 failed, fallback sdpa:", repr(e), flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        SNAP, dtype=torch.bfloat16, device_map="balanced", attn_implementation="sdpa")
    attn = "sdpa"
model = PeftModel.from_pretrained(model, args.adapter)
model.eval()
log({"event": "model_loaded", "seconds": round(time.time() - t, 1), "attn": attn,
     "adapter": args.adapter, "mem_mb": mem()})

FAIL_IDS = tok.encode("fail", add_special_tokens=False)
PASS_IDS = tok.encode("pass", add_special_tokens=False)
assert len(FAIL_IDS) == 1 and len(PASS_IDS) == 1, (FAIL_IDS, PASS_IDS)
FAIL_ID, PASS_ID = FAIL_IDS[0], PASS_IDS[0]
SCORE_SUFFIX = "\n</think>\n\n{\"verdict\": \""

rows = [json.loads(l) for l in open(args.data)]
log({"event": "data_ready", "n": len(rows), "data": args.data})


def prompt_of(r):
    msgs = [{"role": "system", "content": r["system"]},
            {"role": "user", "content": r["user"]}]
    return tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)


def auc_rank(labels, scores):
    n_pos = sum(1 for l in labels if l)
    n_neg = len(labels) - n_pos
    if not n_pos or not n_neg:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    pos_rank_sum = sum(ranks[i] for i in range(len(labels)) if labels[i])
    return (pos_rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


preds = []
bs = args.batch
for lo in range(0, len(rows), bs):
    chunk = rows[lo:lo + bs]
    prompts = [prompt_of(r) for r in chunk]

    # --- score: P(fail) vs P(pass) at the forced verdict position ---
    sp = [p + SCORE_SUFFIX for p in prompts]
    enc = tok(sp, return_tensors="pt", padding=True, add_special_tokens=False).to(model.device)
    try:
        with torch.no_grad():
            logits = model(**enc, logits_to_keep=1).logits[:, -1, :]
    except TypeError:
        with torch.no_grad():
            logits = model(**enc).logits[:, -1, :]
    lf = logits[:, FAIL_ID].float()
    lp = logits[:, PASS_ID].float()
    p_fail = torch.softmax(torch.stack([lf, lp], dim=-1), dim=-1)[:, 0].tolist()

    # --- greedy generation for the verdict string + reason ---
    if args.no_gen:
        for i, r in enumerate(chunk):
            preds.append({"key": r["key"], "wrong": r["wrong"],
                          "p_fail": round(p_fail[i], 6),
                          "verdict_gen": None, "raw": ""})
        log({"event": "batch", "done": min(lo + bs, len(rows)), "of": len(rows)})
        continue
    enc2 = tok(prompts, return_tensors="pt", padding=True, add_special_tokens=False).to(model.device)
    with torch.no_grad():
        gen = model.generate(**enc2, max_new_tokens=args.max_new, do_sample=False,
                             eos_token_id=tok.eos_token_id,
                             pad_token_id=tok.pad_token_id)
    for i, r in enumerate(chunk):
        new = gen[i][enc2["input_ids"].shape[1]:]
        text = tok.decode(new, skip_special_tokens=True)
        m = re.search(r'"verdict"\s*:\s*"(pass|fail)"', text)
        preds.append({"key": r["key"], "wrong": r["wrong"],
                      "p_fail": round(p_fail[i], 6),
                      "verdict_gen": m.group(1) if m else None,
                      "raw": text[:400]})
    log({"event": "batch", "done": min(lo + bs, len(rows)), "of": len(rows), "mem_mb": mem()})

pred_path = args.out + ".predictions.jsonl"
with open(pred_path, "w") as f:
    for p in preds:
        f.write(json.dumps(p, ensure_ascii=False) + "\n")

labels = [bool(p["wrong"]) for p in preds]
scores = [p["p_fail"] for p in preds]
n_pos, n_neg = sum(labels), len(labels) - sum(labels)


def rates(mask):
    tp = sum(1 for p, m in zip(preds, mask) if m and p["wrong"])
    fp = sum(1 for p, m in zip(preds, mask) if m and not p["wrong"])
    return {"det": round(tp / n_pos, 4), "fp": round(fp / n_neg, 4),
            "tp": tp, "fp": fp, "n_pos": n_pos, "n_neg": n_neg}


metrics = {
    "adapter": args.adapter, "data": args.data, "n": len(preds),
    "n_wrong": n_pos, "n_pass": n_neg,
    "auc_pfail": round(auc_rank(labels, scores), 4),
    "t05_score": rates([s >= 0.5 for s in scores]),
    "gen_verdict": rates([p["verdict_gen"] == "fail" for p in preds]),
    "unparsed": sum(1 for p in preds if p["verdict_gen"] is None),
}
# per-arm breakdown at t=0.5 on the score
arms = {}
for p in preds:
    arm = next(r["arm"] for r in rows if r["key"] == p["key"]) if "arm" in rows[0] else "?"
    arms.setdefault(arm, []).append(p)
for arm, ps in sorted(arms.items()):
    ap_ = sum(1 for p in ps if p["wrong"])
    an_ = len(ps) - ap_
    tp = sum(1 for p in ps if p["p_fail"] >= 0.5 and p["wrong"])
    fp = sum(1 for p in ps if p["p_fail"] >= 0.5 and not p["wrong"])
    metrics.setdefault("per_arm", {})[arm] = {
        "n": len(ps), "n_wrong": ap_,
        "det": round(tp / ap_, 4) if ap_ else None,
        "fp": round(fp / an_, 4) if an_ else None,
        "auc": round(auc_rank([bool(p["wrong"]) for p in ps],
                              [p["p_fail"] for p in ps]), 4) if ap_ and an_ else None,
    }

with open(args.out + ".metrics.json", "w") as f:
    json.dump(metrics, f, indent=1)
log({"event": "done", "total_s": round(time.time() - T0, 1), "metrics": metrics})

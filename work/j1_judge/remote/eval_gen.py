import os, json, time, glob, re, sys

os.environ.setdefault("HF_HOME", "/dfs/data/hewj13/.cache/huggingface")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

EVAL_FILE = os.environ["EVAL_FILE"]
ADAPTER = os.environ["ADAPTER"]
OUT = os.environ["OUT"]
N = int(os.environ.get("N", "0"))
MAX_NEW = int(os.environ.get("MAX_NEW", "1600"))
BASE = "/dfs/data/hewj13/j3_judge"

SNAP = sorted(glob.glob("/dfs/data/hewj13/.cache/huggingface/hub/models--Qwen--Qwen3.8-27B/snapshots/*/"))[0]
T0 = time.time()


def log(d):
    d["t"] = round(time.time() - T0, 1)
    print(json.dumps(d, ensure_ascii=False), flush=True)


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


log({"event": "start", "eval_file": EVAL_FILE, "adapter": ADAPTER, "n": N})

tok = AutoTokenizer.from_pretrained(SNAP)
if tok.pad_token is None:
    tok.pad_token = tok.eos_token
try:
    model = AutoModelForCausalLM.from_pretrained(
        SNAP, dtype=torch.bfloat16, device_map="balanced",
        attn_implementation="flash_attention_2")
except Exception as e:
    print("FA2 failed, fallback sdpa:", repr(e), flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        SNAP, dtype=torch.bfloat16, device_map="balanced",
        attn_implementation="sdpa")
if ADAPTER and ADAPTER != "none":
    model = PeftModel.from_pretrained(model, ADAPTER)
model.eval()
model.config.use_cache = True
dev = "cuda:0"
log({"event": "model_loaded", "seconds": round(time.time() - T0, 1)})

erows = [json.loads(l) for l in open(EVAL_FILE)]
if N:
    erows = erows[:N]
res = []
tok.padding_side = "left"
with torch.no_grad():
    for lo in range(0, len(erows), 2):
        chunk = erows[lo:lo + 2]
        ps = []
        for r in chunk:
            msgs = ([{"role": "system", "content": r["system"]}] if r.get("system")
                    else []) + [{"role": "user", "content": r["user"]}]
            ps.append(tok.apply_chat_template(msgs, tokenize=False,
                                              add_generation_prompt=True))
        enc = tok(ps, return_tensors="pt", padding=True,
                  add_special_tokens=False).to(dev)
        out = model.generate(**enc, max_new_tokens=MAX_NEW, do_sample=False,
                             pad_token_id=tok.pad_token_id)
        for j, r in enumerate(chunk):
            gen = tok.decode(out[j][enc["input_ids"].shape[1]:],
                             skip_special_tokens=True)
            hits = re.findall(r"VERDICT:\s*(VALID|INVALID)", gen)
            res.append({"key": r["key"], "wrong": bool(r["wrong"]),
                        "verdict": hits[-1] if hits else None,
                        "gen_tail": gen[-300:]})
        log({"event": "batch", "done": min(lo + 2, len(erows)), "of": len(erows)})

with open(OUT, "w") as f:
    for r in res:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

n = len(res)
acc = sum(1 for r in res
          if r["verdict"] and (r["verdict"] == "INVALID") == r["wrong"]) / max(n, 1)
unparsed = sum(1 for r in res if r["verdict"] is None)
tp = sum(1 for r in res if r["wrong"] and r["verdict"] == "INVALID")
fn = sum(1 for r in res if r["wrong"] and r["verdict"] != "INVALID")
fp = sum(1 for r in res if not r["wrong"] and r["verdict"] == "INVALID")
tn = sum(1 for r in res if not r["wrong"] and r["verdict"] != "INVALID")
scores = [1.0 if r["verdict"] == "INVALID" else 0.0 for r in res]
labels = [r["wrong"] for r in res]
log({"event": "summary", "n": n, "acc": round(acc, 4), "unparsed": unparsed,
     "tp": tp, "fn": fn, "fp": fp, "tn": tn,
     "detection": round(tp / max(tp + fn, 1), 4),
     "false_positive": round(fp / max(fp + tn, 1), 4),
     "auc_hard": auc_rank(labels, scores),
     "seconds": round(time.time() - T0, 1)})
log({"event": "done"})

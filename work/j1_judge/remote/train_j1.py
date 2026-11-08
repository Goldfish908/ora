import os, json, time, glob, random

os.environ.setdefault("HF_HOME", "/dfs/data/hewj13/.cache/huggingface")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
import torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model

SNAP = sorted(glob.glob("/dfs/data/hewj13/.cache/huggingface/hub/models--Qwen--Qwen3.8-27B/snapshots/*/"))[0]
BASE = "/dfs/data/hewj13/j1_judge"
DATA = f"{BASE}/train.jsonl"
LOG = f"{BASE}/logs/train_metrics.jsonl"
MAXLEN = 6656
EPOCHS = int(os.environ.get("EPOCHS", "2"))
LR = 1e-4
LIMIT = int(os.environ.get("LIMIT", "0"))  # >0: stop after LIMIT steps, no save


def log(d):
    d["t"] = round(time.time() - T0, 1)
    with open(LOG, "a") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(json.dumps(d, ensure_ascii=False), flush=True)


def mem():
    return {f"gpu{i}": round(torch.cuda.max_memory_allocated(i) / 2**20) for i in range(torch.cuda.device_count())}


T0 = time.time()
log({"event": "start", "snap": SNAP, "data": DATA, "maxlen": MAXLEN, "lr": LR, "epochs": EPOCHS})

t = time.time()
tok = AutoTokenizer.from_pretrained(SNAP)
if tok.pad_token is None:
    tok.pad_token = tok.eos_token

try:
    model = AutoModelForCausalLM.from_pretrained(
        SNAP, dtype=torch.bfloat16, device_map="balanced", attn_implementation="flash_attention_2"
    )
    attn = "flash_attention_2"
except Exception as e:
    print("FA2 failed, fallback sdpa:", repr(e), flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        SNAP, dtype=torch.bfloat16, device_map="balanced", attn_implementation="sdpa"
    )
    attn = "sdpa"
log({"event": "model_loaded", "seconds": round(time.time() - t, 1), "attn": attn, "mem_mb": mem()})

model.config.use_cache = False
model.gradient_checkpointing_enable()
lconf = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.0, target_modules="all-linear",
                   task_type="CAUSAL_LM", bias="none")
model = get_peft_model(model, lconf)
model.print_trainable_parameters()
trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
log({"event": "lora_wrapped", "trainable_params": trainable, "mem_mb": mem()})

rows = [json.loads(l) for l in open(DATA)]
samples = []
n_trunc = 0
for r in rows:
    msgs = [{"role": "system", "content": r["system"]},
            {"role": "user", "content": r["user"]}]
    p = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    full = tok.apply_chat_template(msgs + [{"role": "assistant", "content": r["target"]}],
                                   tokenize=False)
    assert full.startswith(p), "chat template prefix mismatch"
    c = full[len(p):]
    p_ids = tok(p, add_special_tokens=False)["input_ids"]
    c_ids = tok(c, add_special_tokens=False)["input_ids"]
    ids = (p_ids + c_ids)[:MAXLEN]
    labels = ([-100] * len(p_ids) + c_ids)[:MAXLEN]
    n_sup = sum(1 for x in labels if x != -100)
    if n_sup < len(c_ids):
        n_trunc += 1
    if n_sup < 3:
        continue
    samples.append((ids, labels, float(r.get("weight", 1.0))))
lens = [len(s[0]) for s in samples]
sup = [sum(1 for x in s[1] if x != -100) for s in samples]
log({"event": "data_ready", "n": len(samples), "n_with_trunc": n_trunc,
     "tok_len_min": min(lens), "tok_len_max": max(lens),
     "tok_len_mean": round(sum(lens) / len(lens)),
     "sup_len_mean": round(sum(sup) / len(sup)),
     "sample_tail": tok.decode(samples[0][0][-30:])})

opt = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=LR)
dev = model.device
model.train()
step = 0
losses = []
use_ltk = True  # logits_to_keep support flag
for ep in range(EPOCHS):
    random.seed(100 + ep)
    random.shuffle(samples)
    for ids, labels, w in samples:
        t = time.time()
        input_ids = torch.tensor([ids], device=dev)
        n_sup = sum(1 for x in labels if x != -100)
        if use_ltk:
            try:
                out = model(input_ids=input_ids, logits_to_keep=n_sup + 1)
                logits = out.logits[0, :-1, :]
                tgt = input_ids[0, -n_sup:]
                loss = F.cross_entropy(logits.float(), tgt)
            except TypeError:
                use_ltk = False
        if not use_ltk:
            lab = torch.tensor([labels], device=dev)
            out = model(input_ids=input_ids, labels=lab)
            loss = out.loss
        (loss * w).backward()
        opt.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        losses.append(loss.item())
        rec = {"event": "step", "step": step, "epoch": ep,
               "loss": round(loss.item(), 4),
               "loss_ma10": round(sum(losses[-10:]) / len(losses[-10:]), 4),
               "step_s": round(time.time() - t, 2),
               "ltk": use_ltk}
        if step % 10 == 0 or step <= 5:
            rec["mem_mb"] = mem()
        log(rec)
        if LIMIT and step >= LIMIT:
            log({"event": "limit_reached", "step": step, "peak_mem_mb": mem()})
            import sys
            sys.exit(0)
    t = time.time()
    outdir = f"{BASE}/adapter_ep{ep + 1}"
    model.save_pretrained(outdir)
    tok.save_pretrained(outdir)
    log({"event": "adapter_saved", "epoch": ep + 1, "seconds": round(time.time() - t, 1),
         "out": outdir, "mem_mb": mem()})

log({"event": "done", "total_s": round(time.time() - T0, 1), "peak_mem_mb": mem()})

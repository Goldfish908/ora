import os, json, time, glob, random

os.environ.setdefault("HF_HOME", "/dfs/data/hewj13/.cache/huggingface")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model

SNAP = sorted(glob.glob("/dfs/data/hewj13/.cache/huggingface/hub/models--Qwen--Qwen3.8-27B/snapshots/*/"))[0]
DATA = "/dfs/data/hewj13/lora_smoke/fake_sft.jsonl"
OUT = "/dfs/data/hewj13/lora_smoke/adapter"
LOG = "/dfs/data/hewj13/lora_smoke/logs/train_metrics.jsonl"
MAXLEN = 1024
EPOCHS = 2
LR = 1e-4

def log(d):
    d["t"] = round(time.time() - T0, 1)
    with open(LOG, "a") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(json.dumps(d, ensure_ascii=False), flush=True)

def mem():
    return {f"gpu{i}": round(torch.cuda.max_memory_allocated(i) / 2**20) for i in range(torch.cuda.device_count())}

T0 = time.time()
log({"event": "start", "snap": SNAP})

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
for r in rows:
    p_ids = tok(r["prompt"], add_special_tokens=False)["input_ids"]
    c_ids = tok(r["completion"], add_special_tokens=False)["input_ids"] + [tok.eos_token_id]
    ids = (p_ids + c_ids)[:MAXLEN]
    labels = ([-100] * len(p_ids) + c_ids)[:MAXLEN]
    samples.append((ids, labels))
lens = [len(s[0]) for s in samples]
log({"event": "data_ready", "n": len(samples), "tok_len_min": min(lens), "tok_len_max": max(lens),
     "tok_len_mean": round(sum(lens) / len(lens))})

opt = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=LR)
dev = model.device
model.train()
step = 0
for ep in range(EPOCHS):
    random.seed(100 + ep)
    random.shuffle(samples)
    for ids, labels in samples:
        t = time.time()
        input_ids = torch.tensor([ids], device=dev)
        lab = torch.tensor([labels], device=dev)
        out = model(input_ids=input_ids, labels=lab)
        out.loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        log({"event": "step", "step": step, "epoch": ep, "loss": round(out.loss.item(), 4),
             "step_s": round(time.time() - t, 2), "mem_mb": mem()})

t = time.time()
model.save_pretrained(OUT)
tok.save_pretrained(OUT)
log({"event": "adapter_saved", "seconds": round(time.time() - t, 1), "out": OUT})
log({"event": "done", "total_s": round(time.time() - T0, 1), "peak_mem_mb": mem()})


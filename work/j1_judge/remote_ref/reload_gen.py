import os, json, time, glob

os.environ.setdefault("HF_HOME", "/dfs/data/hewj13/.cache/huggingface")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

SNAP = sorted(glob.glob("/dfs/data/hewj13/.cache/huggingface/hub/models--Qwen--Qwen3.8-27B/snapshots/*/"))[0]
ADAPTER = "/dfs/data/hewj13/lora_smoke/adapter"
LOG = "/dfs/data/hewj13/lora_smoke/logs/reload_metrics.jsonl"

T0 = time.time()

def log(d):
    d["t"] = round(time.time() - T0, 1)
    with open(LOG, "a") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(json.dumps(d, ensure_ascii=False), flush=True)

def mem():
    return {f"gpu{i}": round(torch.cuda.max_memory_allocated(i) / 2**20) for i in range(torch.cuda.device_count())}

t = time.time()
tok = AutoTokenizer.from_pretrained(SNAP)
model = AutoModelForCausalLM.from_pretrained(SNAP, dtype=torch.bfloat16, device_map="balanced")
base_load_s = round(time.time() - t, 1)
log({"event": "base_loaded", "seconds": base_load_s, "mem_mb": mem()})

t = time.time()
model = PeftModel.from_pretrained(model, ADAPTER)
model.eval()
log({"event": "adapter_loaded", "seconds": round(time.time() - t, 1), "mem_mb": mem()})

prompt = "问题：某工厂要安排下周的生产计划，产能有限、订单有交期。请说明如何把它建模为一个数学优化问题？"
ids = tok(prompt, return_tensors="pt").to(model.device)
t = time.time()
with torch.no_grad():
    out = model.generate(**ids, max_new_tokens=80, do_sample=False)
gen_s = round(time.time() - t, 1)
text = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
log({"event": "generated", "gen_seconds": gen_s, "new_tokens": out.shape[1] - ids["input_ids"].shape[1],
     "text": text, "mem_mb": mem()})
log({"event": "done", "total_s": round(time.time() - T0, 1)})


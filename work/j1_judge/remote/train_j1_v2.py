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
DATA = f"{BASE}/train_v2.jsonl"
EVAL_DATA = f"{BASE}/train_eval_v2.jsonl"
LOG = f"{BASE}/logs/train_v2_metrics.jsonl"
MAXLEN = 6656
EPOCHS = int(os.environ.get("EPOCHS", "3"))
MIN_EPOCHS = int(os.environ.get("MIN_EPOCHS", "2"))
AUC_STOP = float(os.environ.get("AUC_STOP", "0.985"))
VTOK_W = float(os.environ.get("VTOK_W", "40"))       # verdict-token loss weight
SELFEVAL_N = int(os.environ.get("SELFEVAL_N", "128"))
SMOKE_EVAL = int(os.environ.get("SMOKE_EVAL", "0"))  # >0: run self-eval on N cells before training
LR = 1e-4
LIMIT = int(os.environ.get("LIMIT", "0"))  # >0: stop after LIMIT steps, no save


def log(d):
    d["t"] = round(time.time() - T0, 1)
    with open(LOG, "a") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(json.dumps(d, ensure_ascii=False), flush=True)


def mem():
    return {f"gpu{i}": round(torch.cuda.max_memory_allocated(i) / 2**20) for i in range(torch.cuda.device_count())}


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


T0 = time.time()
log({"event": "start", "snap": SNAP, "data": DATA, "maxlen": MAXLEN, "lr": LR,
     "epochs": EPOCHS, "min_epochs": MIN_EPOCHS, "auc_stop": AUC_STOP,
     "vtok_w": VTOK_W, "selfeval_n": SELFEVAL_N})

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

FAIL_IDS = tok.encode("fail", add_special_tokens=False)
PASS_IDS = tok.encode("pass", add_special_tokens=False)
assert len(FAIL_IDS) == 1 and len(PASS_IDS) == 1, (FAIL_IDS, PASS_IDS)
FAIL_ID, PASS_ID = FAIL_IDS[0], PASS_IDS[0]
SCORE_SUFFIX = "\n</think>\n\n{\"verdict\": \""

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
vpos_found = vpos_missed = 0
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
    # verdict token position (index into ids/labels): first occurrence of the
    # expected verdict token inside the completion span; reason text follows it.
    expected = FAIL_ID if '"fail"' in r["target"].split('"reason"')[0] else PASS_ID
    vpos = None
    for i in range(len(p_ids), min(len(ids), len(p_ids) + 40)):
        if ids[i] == expected:
            vpos = i
            break
    if vpos is None:
        vpos_missed += 1
    else:
        vpos_found += 1
    samples.append((ids, labels, float(r.get("weight", 1.0)), vpos))
lens = [len(s[0]) for s in samples]
sup = [sum(1 for x in s[1] if x != -100) for s in samples]
vpositions = [s[3] - (len(s[0]) - sum(1 for x in s[1] if x != -100))
              for s in samples if s[3] is not None]
log({"event": "data_ready", "n": len(samples), "n_with_trunc": n_trunc,
     "tok_len_min": min(lens), "tok_len_max": max(lens),
     "tok_len_mean": round(sum(lens) / len(lens)),
     "sup_len_mean": round(sum(sup) / len(sup)),
     "vpos_found": vpos_found, "vpos_missed": vpos_missed,
     "vpos_in_sup_min": min(vpositions), "vpos_in_sup_max": max(vpositions),
     "sample_tail": tok.decode(samples[0][0][-30:])})

dev = model.device


def indist_auc(n_cells):
    """Score-only in-distribution AUC on a deterministic subset of EVAL_DATA."""
    erows = [json.loads(l) for l in open(EVAL_DATA)]
    erows = erows[:]  # keep file order, then deterministic shuffle
    random.Random(7).shuffle(erows)
    erows = erows[:n_cells]
    scores, labels = [], []
    tok.padding_side = "left"
    model.eval()
    with torch.no_grad():
        for lo in range(0, len(erows), 4):
            chunk = erows[lo:lo + 4]
            ps = []
            for r in chunk:
                msgs = [{"role": "system", "content": r["system"]},
                        {"role": "user", "content": r["user"]}]
                ps.append(tok.apply_chat_template(msgs, tokenize=False,
                                                  add_generation_prompt=True) + SCORE_SUFFIX)
            enc = tok(ps, return_tensors="pt", padding=True,
                      add_special_tokens=False).to(dev)
            out = model(**enc, logits_to_keep=1)
            lg = out.logits[:, -1, :].float()
            pf = torch.softmax(torch.stack([lg[:, FAIL_ID], lg[:, PASS_ID]], dim=-1),
                               dim=-1)[:, 0].tolist()
            scores.extend(pf)
            labels.extend(bool(r["wrong"]) for r in chunk)
    tok.padding_side = "right"
    model.train()
    return auc_rank(labels, scores), len(erows)


if SMOKE_EVAL:
    t = time.time()
    a, n = indist_auc(SMOKE_EVAL)
    log({"event": "smoke_selfeval", "n": n, "auc": a,
         "seconds": round(time.time() - t, 1), "mem_mb": mem()})

opt = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=LR)
model.train()
step = 0
losses = []
use_ltk = True  # logits_to_keep support flag
for ep in range(EPOCHS):
    random.seed(100 + ep)
    random.shuffle(samples)
    for ids, labels, w, vpos in samples:
        t = time.time()
        input_ids = torch.tensor([ids], device=dev)
        n_sup = sum(1 for x in labels if x != -100)
        if use_ltk:
            try:
                out = model(input_ids=input_ids, logits_to_keep=n_sup + 1)
                logits = out.logits[0, :-1, :]
                tgt = input_ids[0, -n_sup:]
                ce = F.cross_entropy(logits.float(), tgt, reduction="none")
                sup_start = len(ids) - n_sup
                if vpos is not None and sup_start <= vpos < len(ids):
                    wpos = torch.ones(n_sup, device=dev)
                    wpos[vpos - sup_start] = VTOK_W
                    loss = (ce * wpos).sum() / wpos.sum()
                else:
                    loss = ce.mean()
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
    outdir = f"{BASE}/adapter_v2_ep{ep + 1}"
    model.save_pretrained(outdir)
    tok.save_pretrained(outdir)
    log({"event": "adapter_saved", "epoch": ep + 1, "seconds": round(time.time() - t, 1),
         "out": outdir, "mem_mb": mem()})
    t = time.time()
    a, n = indist_auc(SELFEVAL_N)
    log({"event": "epoch_auc", "epoch": ep + 1, "auc": None if a is None else round(a, 4),
         "n": n, "seconds": round(time.time() - t, 1), "mem_mb": mem()})
    if ep + 1 >= MIN_EPOCHS and a is not None and a >= AUC_STOP:
        log({"event": "early_stop", "epoch": ep + 1, "auc": round(a, 4)})
        break

log({"event": "done", "total_s": round(time.time() - T0, 1), "peak_mem_mb": mem()})

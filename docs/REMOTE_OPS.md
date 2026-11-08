# 远端 workspace 运维备忘(j4_judge 训练事故,2026-11-08)

## vLLM 复活陷阱(两次训练 OOM 的根因)

pearl 实验时代留下的三件套会抢占 GPU 并自动复活:

1. **vLLM 服务**:`vllm serve pearl4b@8350`(gpu-mem 0.45)和
   `vllm serve pearl-fancc3@8351`(gpu-mem 0.4),合计每卡 ~37GB。
2. **复活代理**:pid 由 `proxy_server:app --port 8340` 担任——杀 vLLM 后端后
   ~30-60 秒内自动重新拉起。**必须先杀代理,再杀 vLLM**。
3. **GPU 保活**:`scripts/gpu_keepalive.py`,29.5s/30s 占空比烧算力,
   显存仅 528MB/卡但拖慢训练。训练期间可杀(训练本身就是保活)。

## 训练前检查单

```bash
# 1. 看卡上是否有非训练进程
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader
# 2. 找复活代理(存在则先杀)
pgrep -af "proxy_server:app"
# 3. 杀干净后等 90s 确认无复活,再启动训练
```

## 训练启动纪律

- `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`(样本最长 12k token,
  反向传播瞬时分配大,碎片化会假性 OOM);
- 27B + LoRA(device_map=balanced 双卡)稳态 ~40GB/卡,余量充足,
  但**不能**与任何 vLLM 实例共存。

## 链条结构(j4_judge)

train_j1_v4.py(每 epoch 存 adapter_v4_ep{1,2,3},结束打印 `"event": "done"`)
→ eval_chain_v4b.sh(守 done 标记;F5-F8 三 epoch 评测 → best_ep.txt 选优
→ IndustryOR 终验 v4_eval_ior.jsonl;全程记 logs/eval_chain.log)
→ 本地 `scripts/p20_finalize_v4.sh` 一键收尾。

## 终端通道冲突(2026-11-08 补)

mf_exec 的 MF_TERM 对应 workspace jupyter 的持久终端,多人/多会话共用同一
TERM 会互相串输入(曾在 TERM=2 看到他人探测 j3_judge 的命令混入我的输出)。
- 独占通道:用 jupyter API 新建终端:
  `POST /app-workspace-1178-1789462142492/api/terminals {"name":"3"}`
  (带 aimaster-token-header cookie + token 参数),然后 MF_TERM=3。
- 查看现有终端:GET 同路径。
- 工作区重启后 pearl 的 vLLM(39664/39671,~35GB/卡)与 gpu_keepalive.py
  会自启,与训练共存时显存 ~80GB/卡偏紧;eval 链启动前若 OOM 再按上文处置。

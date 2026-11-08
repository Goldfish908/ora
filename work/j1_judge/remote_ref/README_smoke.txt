LoRA SFT 冒烟报告 — workspace app-workspace-1178-1789462142492 (2x A800-80G)
日期: 2026-11-04
================================================================

1. 环境考古结论
----------------
训练用 python: 系统默认 /usr/bin/python (Python 3.12.3)
  - torch        2.8.0a0+5228986c39.nv25.05 (NVIDIA 构建)
  - transformers 5.10.2
  - peft         0.19.1
  - accelerate   1.13.0
  - flash_attn   2.7.3 (本次冒烟用了 flash_attention_2, 工作正常)
  - datasets     5.0.0 (冒烟未用到)
  以上 peft/accelerate/datasets 来自昨天 pip install -e '.[train]' (Open-Jev),
  见 /dfs/data/hewj13/pip_jev.log。本次冒烟没有新装任何训练包。

serving (vllm):
  - 系统默认 python 没有 vllm, 我们的任何目录下也找不到 vllm。
  - 昨天看到的 VLLM::EngineCore 进程实际是另一用户 way2m 的 serving:
      /dfs/data/way2m/venvs/pearl/bin/vllm serve ... (端口 8350/8351,
      gpu-memory-utilization 0.45/0.4, 占 GPU0 ~38.8G / GPU1 ~34.7G)
    该 venv 里 vllm==0.29.0 + torch==2.13.0 + transformers 5.17.0 (无 ray 依赖)。
  - Open-Jev 的 pyproject train extras 只有 torch/transformers/peft/accelerate/
    datasets/safetensors, 不含 vllm; pip_jev.log 全文无 vllm。即昨天我们从未装过 vllm,
    python -m jev.server 是 Open-Jev 自己的 server, 与 vllm 无关。
  - 本次按"不用别人环境"的要求, 自建 /dfs/data/hewj13/lora_smoke/venv_vllm (7.3G),
    离线装成 vllm==0.29.0 (与 way2m 验证过的同版本):
      PIP_CONSTRAINT= ./venv_vllm/bin/pip install --no-index \
        --find-links /dfs/data/way2m/wheelhouse 'vllm==0.29.0'
    两个坑: (1) 全局环境变量 PIP_CONSTRAINT=/etc/pip/constraint.txt (NGC 容器,
    pin 了 protobuf==4.24.4 等) 不清空会 ResolutionImpossible, 必须前置 PIP_CONSTRAINT= ;
    (2) 外网 pip 只有 ~100kB/s, 必须走 way2m 的 wheelhouse (208 个 wheel) 离线安装。
    注意只复用了他们的 wheel 文件, 未动其 venv 与进程。

GPU 占用实况 (重要, 与"GPU 已清空"的预期不符):
  - way2m 两个 vllm serve + 一个 gpu_keepalive.py 常驻, 占 GPU0 ~39.3G, GPU1 ~35.3G。
  - 未动它们的进程。我们训练时两卡各只剩 ~42G/~46G 可用。

2. LoRA 冒烟结果 (核心交付) — 全部通过
----------------------------------------
基座: Qwen/Qwen3.8-27B (HF cache snapshot 1d4bf0f2, HF_HUB_OFFLINE=1)
数据: fake_sft.jsonl, 20 条优化建模问答 (prompt/completion), token 长 240-288 (mean 272)
配置: BF16 + LoRA(r=16, alpha=32, target all-linear, 可训练 116,727,808 = 0.43%)
      + gradient checkpointing, device_map="balanced" 双卡, batch=1, maxlen=1024,
      AdamW lr=1e-4, 2 epochs = 40 steps

指标 (logs/train_metrics.jsonl):
  - 模型加载: 16.7 s (FA2)
  - 权重显存: GPU0 23478 MiB / GPU1 27822 MiB
  - 训练峰值: GPU0 24870 MiB / GPU1 29529 MiB (约为权重的 1.06x, 激活+LoRA 优化器 ~2-3G)
  - step 耗时: mean 4.53 s/step; loss 3.32 -> 0.024 (40 steps 正常下降)
  - adapter 保存: 1.7 s -> /dfs/data/hewj13/lora_smoke/adapter/
  - 训练全程: 202 s

重载验证 (logs/reload_metrics.jsonl):
  - 基座重载 15.9 s + PeftModel.from_pretrained 挂 adapter 4.0 s
  - 生成 80 tokens 16.2 s, 输出连贯中文建模回答 (符合训练数据风格)
  - 显存: GPU0 24138 / GPU1 28151 MiB

结论: 管道 (加载->LoRA 训练->保存->重载->生成) 端到端可行。

2b. vllm serving 验证 (venv_vllm, vllm 0.29.0) — 通过
------------------------------------------------------
  - 第一次 serve 失败: 该模型是 Mamba/attention 混合架构, CUDA graph 捕获报
    ValueError: max_num_seqs (1024) exceeds available Mamba cache blocks (109)。
  - 第二次加 --gpu-memory-utilization 0.40 --max-model-len 8192 --max-num-seqs 64 成功。
    启动 17:49:15 -> Application startup complete 17:57:40, 共 ~8m25s
    (其中 engine init 360.7s, 含编译 62.6s)。启动期 shm_broadcast 60s 警告属正常噪音。
  - curl /v1/models 正常返回模型 id; /v1/chat/completions 生成验证通过
    (59 prompt tokens -> 64 completion tokens, 中文 MIP 解释连贯, logs/curl_chat.txt)。
  - 验证完已 pkill, 显存回落到 way2m 基线 (GPU0 39343 / GPU1 35285 MiB),
    我方占用清零 (logs/gpu_final.txt)。

3. 复现命令
-----------
远程:
  cd /dfs/data/hewj13/lora_smoke
  HF_HOME=/dfs/data/hewj13/.cache/huggingface HF_HUB_OFFLINE=1 python train_lora_smoke.py
  HF_HOME=/dfs/data/hewj13/.cache/huggingface HF_HUB_OFFLINE=1 python reload_gen.py
serving (venv 装好后):
  HF_HOME=/dfs/data/hewj13/.cache/huggingface HF_HUB_OFFLINE=1 \
    ./venv_vllm/bin/vllm serve /dfs/data/hewj13/.cache/huggingface/hub/models--Qwen--Qwen3.8-27B/snapshots/1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0 \
    --tensor-parallel-size 2 --dtype bfloat16 --port 8000 \
    --gpu-memory-utilization 0.40 --max-model-len 8192 --max-num-seqs 64
  curl 127.0.0.1:8000/v1/models
  (验证完记得 pkill -f 'lora_smoke/venv_vllm' 释放显存)

4. 文件清单 (/dfs/data/hewj13/lora_smoke/)
------------------------------------------
  make_data.py / fake_sft.jsonl   假数据生成与数据本体
  train_lora_smoke.py             训练脚本
  reload_gen.py                   adapter 重载+生成验证
  adapter/                        LoRA adapter (safetensors)
  logs/train.log, train_metrics.jsonl, reload.log, reload_metrics.jsonl
  logs/vllm_install5.log, vllm_serve.log (首次失败), vllm_serve2.log (成功),
      curl_models.txt, curl_chat.txt, gpu_final.txt
  logs/gpu_apps.txt, probe2.txt, probe3.txt, way2m_versions.txt, jev_pyproject.txt 等考古记录
  venv_vllm/                      vllm 独立环境 (见 serving 结论)

5. 风险
-------
  - way2m 任务与我们共卡, 显存余量每卡只有 ~42-46G; 27B 全量微调/更大 batch 会 OOM,
    正式训练建议错峰或协商。
  - transformers 5.10.2 很新, from_pretrained 需用 dtype= 参数; Trainer/trl 未验证。
  - vllm 0.29.0 绑死 torch==2.13.0, 与训练环境 torch 2.8.0a0 不兼容, 必须用独立 venv,
    不要 pip 进系统 python (会顶掉 NVIDIA torch, 毁掉 flash_attn 与训练环境)。
  - 该模型是 Mamba/attention 混合架构, vllm 默认 max_num_seqs=1024 超过 Mamba cache
    blocks (109) 会直接起不来; 必须显式调低 --max-num-seqs (本次 64 可用), 或加
    --enforce-eager 跳过 CUDA graph (会更慢)。
  - pip 全局 PIP_CONSTRAINT=/etc/pip/constraint.txt (NGC 容器) 会干扰任何 pip install,
    装包前务必前置 PIP_CONSTRAINT= 清空; 外网速慢, 优先复用本地 wheelhouse。

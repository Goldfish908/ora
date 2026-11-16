# Open-Jev-2B 修复候选排序：工程冒烟协议 v0.1

状态：10-step 冒烟与离线诊断已完成；工程链路通过，但小样本、长上下文及弱离线结果不支持能力晋升。本文不报告模型质量提升或自然泛化。

## 目的与放置位置

验证官方 Open-Jev-2B 能否在现有修复偏好数据上完成适配、保存和重载。未来模型仅位于“候选修复生成之后、确定性审计之前”做候选排序；SCIP、独立 witness 和业务评分不被替代。

这不是 Open-Jev 官方 benchmark 复现，也不是 27B judge 的继续训练。

## 固定实现与版本

- 官方代码：`/dfs/data/hewj13/Open-Jev`，HEAD `bd4118882f733574a3250a4b65fe4d884130c08b`。
- 官方 checkpoint：`ZefanCai/Open-Jev-2B`，revision `0c7aa498b1627be8da4acf34c863ff0ee0a92785`。
- 基座：`Qwen/Qwen3.5-2B`，revision `15852e8c16360a2fea060d615a32b45270f8a8fc`。
- 官方结构：LoRA rank 8 + 标量决策头；每个候选独立编码；soft cross-entropy + 0.1 Brier。
- 从官方已发布 2B checkpoint 适配，不从零初始化决策头。

## 数据与泄漏控制

输入：`work/sft_data/dpo.jsonl`，SHA256 `5b7212d159af93e3d6542c800f9062ef01c717833250021995d0bc14df6fe417`。

适配后目录：`work/jev_repair_data_v0.1/`。原始 459 对中，删除 16 对精确重复、21 对冲突输入及 95 个重复 rejected 输入对应 pair，保留 306 对/612 个候选行。输入脱敏，模型只见 state/question/kind/options，不见 source、scenario_id 或公开答案。

| split | 候选行 | pair | 用途 |
|---|---:|---:|---|
| train | 50 | 25 | 仅训练冒烟 |
| calibration | 6 | 3 | 仅温度校准 |
| test | 56 | 28 | 历史开发评估，本冒烟 defer |
| ood | 500 | 250 | wrong_constant 错误族，本冒烟 defer |

所有 scenario 整体同侧。原始 dev 是历史开发数据，不是新 heldout。`wrong_constant` 全部从 train 排除并进入 OOD。数据 manifest SHA256：`68a5551bbb030cc834b045a43115f53640d900002f027f2b49eba117d5654d02`。

远端 `python3 -m jev.data validate` 已通过：612 records、100 groups、612 unique inputs，train/calibration/test/ood 分别为 50/6/56/500。

## 冒烟配置

```text
steps=10
train_rows=50
calibration_rows=6
max_length=16384
lora_rank=8
accumulation=1
lr=5e-5
head_lr=1e-4
brier_weight=0.1
seed=42
training_sampling=shuffled
initial_checkpoint=/dfs/data/hewj13/ora_small_jev/derived_checkpoint_16k
output=/dfs/data/hewj13/ora_small_jev/runs/smoke_v0.1
log=/dfs/data/hewj13/ora_small_jev/logs/smoke_v0.1.log
CUDA_VISIBLE_DEVICES=1
```

使用 `--defer-heldout`：不加载或评估 test/OOD，不根据测试/OOD 调参。训练完成后由官方训练器保存、释放并重载 checkpoint，要求 calibration reload logit 最大误差不超过 0.05。

开始前必须满足：

1. 两个固定 revision 均下载完整，基座索引声明的 4,548,144,832 bytes 权重可读取；
2. 官方 checkpoint 的 adapter/head/model.json 完整；
3. 离线 snapshot 解析成功；
4. 数据校验与输入 hash 一致；
5. 不杀死或抢占已有 vLLM 进程，OOM 则记录失败，不改小目标掩盖。

## 停止条件与解释边界

本次只验证训练→保存→重载链路。训练集只有 25 对/12 个 scenario，校准只有 3 对/2 个 scenario，**不满足评估自然泛化或晋升模型的数据门槛**。即使 loss 下降或 calibration 表现改善，也不据此声称排序有效。

非 LLM pilot 使用不同的清洗口径，共 422 对；其 AST/TF-IDF 结果是后续有效实验需要超过的强基线，但不能与本冒烟的 306 对直接比较准确率。若要开展质量实验，需先统一切分、补足独立多候选数据，并做同基座、同预算、独立 SCIP/witness 评价。


## 长度审计与训练前修订

在训练前，使用官方 `candidate_prompts` 与 Qwen tokenizer 逐条测量：全部 612 条输入都超过 4096，train 最大 14738 tokens，test 最大 10778，calibration 最大 9182，全部输入均小于 16384。原 4096 配置会触发官方的显式长度异常，不能运行。

因此训练前将 `max_length` 修订为 16384，不静默截断、不按长度筛题。派生 checkpoint 只修改 `model.json` 的运行时长度字段，官方 adapter、决策头、基座权重均不变；原官方 checkpoint 不覆盖。审计保存在远端 `ora_small_jev/runs/token_length_audit.json`。

该上下文长度明显大于官方 2B 已发布配置的 4096，长上下文行为仍只作工程验证，不能从冒烟推断排序质量。


## 冒烟后的离线诊断（待执行）

只有冒烟 `status=complete` 且 checkpoint 重载通过后，才运行离线诊断。官方 2B 与训练 checkpoint 顺序加载，避免同时占用显存；使用同一个派生 16384 运行时配置和固定的历史 test 集，不根据 test/OOD 选择 checkpoint 或调整训练参数。

```bash
cd /dfs/data/hewj13/Open-Jev
PYTHONPATH=. python3 /dfs/data/hewj13/ora_small_jev/open_jev_offline_eval.py \
  --baseline /dfs/data/hewj13/ora_small_jev/derived_checkpoint_16k \
  --checkpoint /dfs/data/hewj13/ora_small_jev/runs/smoke_v0.1/checkpoint \
  --data /dfs/data/hewj13/ora_small_jev/data/jev_repair_v0.1/test.jsonl \
  --out /dfs/data/hewj13/ora_small_jev/runs/offline_eval_v0.2 \
  --split test --device cuda:1
```

输出 baseline/trained 的 pairwise accuracy、scenario macro、coverage、输入 token 和延迟。这里只是历史开发诊断，不是 frozen 终验，也不证明端到端修复提升。OOD 默认不运行。


## 前置校验修订记录

第一次排队未进入训练：完整性检查误将 safetensors 物理文件字节数等同于索引中的张量字节数，忽略了文件头开销。修正后改为检查全部分片存在、索引 key 与 `safe_open` 可读 key 一致，并检查 adapter/head/config；不据此把首次退出记为模型训练失败。

同时已在标准 HF cache 的固定 revision snapshots 下建立指向本地基座的链接，`local_files_only=True` 的 `snapshot_download` 已实测成功。后续运行保留 `driver_v0.1.log`，防止前置异常丢失。


## 完成结果

- `summary.json`：`status=complete`，10 steps，252.356 秒，checkpoint reload max error=0.0。
- 离线对照：官方 2B 为 7/28（macro 24.50%），10-step checkpoint 为 9/28（macro 30.67%）。
- 输入 token 两臂均为 501841；预测、指标、日志、adapter 和 head 已同步到 `work/open_jev_smoke_v0.1/`。
- 离线评估脚本曾出现进度日志参数错误，修正并增加第 10 条日志回归后，v0.2 已完成；该错误不是模型训练或加载失败。
- 结论仅为工程可行，能力不晋升，不继续扩大同类训练。

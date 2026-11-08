J1 实验 — 跨数据集语义判官 (semantic judge) 
日期: 2026-11-04, workspace app-workspace-1178-1789462142492 (2x A800-80G, 与 way2m 共卡)
================================================================

1. 任务
-------
用 RetailOpt 的 316 个带标签细胞 (P0/Open-Jev 标定同一 key 集) LoRA-SFT 一个
语义判官: 输入 {题面, 建模代码, 求解器返回目标值}, 输出 JSON 判词
{"verdict": "pass"|"fail", "reason": "..."}. 在 IndustryOR 240 个带标签细胞上
做跨数据集评估, 对照三个既有基线 (Open-Jev off-the-shelf / D2 规则门 / 自一致性).
硬约束: 训练只用 RetailOpt 细胞, IndustryOR 只在测试出现.

2. 数据
-------
- train_cells.jsonl  316 个 RetailOpt 细胞 (runs/judge_calib_p0/judge_p0.jsonl 的
  key 集; 标签 = witness 检查器: infeasible→fail/wrong, feasible→pass/correct;
  代码取自每个 key 自己的 sandbox fb__{sid}__{thinking}__r{round}/gen.py).
  注意: scripts/judge_calibration_p0.py 有个 truthiness bug ('off' 字符串为真值,
  被映射到 __on__ sandbox), 本实验用的是修正后的 per-key 正确 sandbox.
  题面 = data/m1_retailopt/retailopt_190.jsonl 的 prompt_schema, 按 scenario_id 关联.
- 标签分布: wrong 240 / correct 76 (3.16:1). 类别失衡处理: 损失按类加权
  (w_wrong=0.658, w_pass=2.079, 即 N/(2*n_class)), 不重采样不复制样本.
- train.jsonl  316 条 SFT 样本 {key, wrong, weight, system, user, target}.
  user = [PROBLEM] 题面(截 6000 字符) + [MODEL CODE] 代码(截 4000 字符)
  + [RETURNED OBJECTIVE] 目标值; target = JSON 判词, fail 的 reason 取
  witness_details 首条 (如 "C-DEMAND: ..."), pass 用固定句式.
- test.jsonl  240 个 IndustryOR 细胞 (runs/industryor/industryor_judge_cells.jsonl),
  wrong=true = 幻影 (打印目标值与 en_answer 不符). 同格式 user, 不带 target.
- train_eval.jsonl  同 316 训练细胞的评估格式副本 (分布内 sanity 用).

3. 训练
-------
- 基座 Qwen/Qwen3.8-27B (HF cache snapshot 1d4bf0f2, HF_HUB_OFFLINE=1),
  LoRA r=16 alpha=32 all-linear (可训练 116,727,808 = 0.43%), BF16, FA2,
  gradient checkpointing, device_map=balanced 双卡, batch=1, AdamW lr=1e-4.
- chat 模板: 模型模板强制 <think> 块, 训练 completion = "\n</think>\n\n" + target
  + "<|im_end|>\n" (mask 只留 completion, 平均每条 ~39 个监督 token).
- 显存关键: logits_to_keep=n_sup+1, 只对 completion 位置算 logits/loss —
  全序列 logits (5k x 151k vocab) 会爆显存 (首次冒烟 OOM 于此).
- MAXLEN 6656 (实际样本 ~2.3-3.3k token, 无截断发生).
- 训练脚本 train_j1.py, 日志 logs/train_metrics.jsonl.

4. 评估
-------
- eval_j1.py: 对每个细胞 (a) 强制前缀 prompt+"\n</think>\n\n{\"verdict\": \""
  单次前向 (logits_to_keep=1, 否则全位置 logits OOM), 取 fail/pass 两 token 的
  softmax 得 p_fail (AUC 用); (b) 贪心生成 160 token 判词全文 (定性检查).
  transformers 直跑, batch=4, 未用 vLLM. test 240 细胞 ~23min, train_eval 316
  (score-only, --no-gen) ~19min.
- 指标: AUC(p_fail), t=0.5 检出率(det=TP/61)与误报率(fp=FP/179), 分 arm 细分.
- 基线 (来自 runs/industryor 与 docs/paper/d1/d2 文档):
  Open-Jev off-the-shelf AUC 0.662 (t=0.5: det 1.6% / FP 0.0%, 本实验复算确认);
  D2 规则门 det 9.8% / FP 5.6%; 自一致性 det 16.4% / FP 5.0%.

5. 结果
-------
训练曲线 (logs/train_metrics.jsonl):
  epoch 1 共 316 steps 全部完成; loss 分段均值 steps 1-40=0.687, 41-80=0.373,
  81-120=0.263, 121-160=0.273, 161-200=0.258, 201-240=0.220, 241-280=0.231,
  281-316=0.246; 末段 ma10 ~0.21. step_s 均值 27.9s, 总训练 2.49h,
  峰值显存 gpu0 29.4G / gpu1 34.0G. epoch 1 完成后保存 adapter_ep1 并主动停止
  (样本量小 + loss 已平 + 与 way2m 共卡的时间成本, 放弃 epoch 2; epoch 2 仅跑了
  5 步, loss ~0.18, 不影响 adapter_ep1).

IndustryOR 240 (61 phantom / 179 correct), adapter_ep1:
  AUC(p_fail) = 0.6779
  t=0.5:  det 19.7% (12/61)   FP 5.0% (9/179)
  per-arm: z0 n=49  det 8.3%  FP 5.4%  AUC 0.645
           z1 n=92  det 25.0% FP 3.1%  AUC 0.744
           z2 n=99  det 19.0% FP 6.4%  AUC 0.618
RetailOpt 316 分布内 sanity (train_eval, 同一 adapter):
  AUC(p_fail) = 0.5693
  t=0.5:  det 14.6% (35/240)  FP 6.6% (5/76)

对照表 (t=0.5):
  method                        AUC     det      FP
  J1 judge (test_ep1)           0.678   19.7%    5.0%
  J1 judge (train_ep1, sanity)  0.569   14.6%    6.6%
  Open-Jev off-the-shelf        0.662   1.6%     0.0%
  D2 rule gate                  —       9.8%     5.6%*
  A1 self-consistency           —       16.4%    5.0%
  (*2 细胞无规则, 分母 177)

重要观察:
- p_fail 分布为窄钟形 (0.29-0.59, 中心 ~0.44), t=0.5 附近的 det/FP 对阈值极敏感.
- 自由生成模式下模型对全部 240 个测试细胞输出同一句固定 pass 模板
  (训练集 pass 的 reason 是常量句式, 被整体背诵; verdict token 坍缩到 pass),
  gen 判词 det=0 — 只有强制前缀打分 (p_fail) 通道有信号.
- 分布内 AUC 0.569 < 分布外 0.678, 且训练细胞上 wrong/pass 两侧的 p_fail 均值
  仅 0.463/0.458 几乎无分离: 1 epoch 训练基本没有让 verdict token 学到可迁移的
  判别信号, loss 2.36→0.2 的下降主要来自固定模板与 reason 文本的记忆.

结论 (诚实版): 测试集数字 (AUC 0.678 > Open-Jev 0.662, det 19.7% 为四法最高,
FP 5.0% 与自一致性持平) 在表面上最好, 但分布内 sanity 的失败 (0.569) 说明该
adapter 连训练集都未能可靠区分, 测试集优势应视为弱且不稳定证据, 不能断言
跨数据集迁移成功. 后续方向: (a) 训满 2-3 epoch 并把分布内 AUC 接近 1 作为继续
评估的前提; (b) verdict token 单独加大 loss 权重 (目前只是 ~43 个监督 token
中的 1 个); (c) 扩充训练细胞 (本实验还有 65 个已标注细胞未用, 且可用更多轮次
的 feedback sandbox); (d) pass 的 reason 不要常量句式, 防模板背诵.

6. 文件清单 (/dfs/data/hewj13/j1_judge/)
---------------------------------------
  train.jsonl / test.jsonl / train_eval.jsonl / train_cells.jsonl / stats.json
  train_j1.py / eval_j1.py / run_eval.sh
  adapter_ep1/                    LoRA adapter (epoch 1, 467MB safetensors)
  metrics.json                    聚合指标 (test + train sanity + 基线)
  logs/train_metrics.jsonl        训练日志 (321 step 记录)
  logs/eval_test_ep1.{metrics,predictions,log}.json(l)   IndustryOR 评估
  logs/eval_train_ep1.{metrics,predictions,log}.json(l)  分布内 sanity
  logs/eval_run.out               评估 stdout
  README.txt                      本文件
7. J1.1 (v2) 迭代 — 2026-11-05
--------------------------------
按 §5 修复清单执行: (1) 训练 3 个 epoch (MIN_EPOCHS=2, AUC_STOP=0.985 未触发);
(2) verdict token 单独 loss 权重 VTOK_W=40 (加权平均 CE, verdict 占 ~48% loss
质量; 定位经冒烟验证 381/381 命中, 恒在监督偏移 8); (3) 训练集扩到全部 381 个
已标注细胞 (316 P0 + 65 未用: 294 wrong / 87 pass, w_wrong=0.648, w_pass=2.190);
(4) pass reason 改为 8 模板按 key 哈希选取并嵌入 objective 值 (输入相关, 防背诵).
脚本 train_j1_v2.py, 数据 train_v2.jsonl, 日志 logs/train_v2_metrics.jsonl.
每个 epoch 末保存 adapter_v2_ep{1,2,3} 并对 train_eval_v2.jsonl 的 128 细胞子集
做 score-only 分布内 AUC 自检; auto_eval_v2.sh 在训练结束后自动按规则选 adapter
(最早达到 AUC>=0.985 者, 否则取自检 AUC 最高者) 并跑两套 eval.

训练曲线 (1143 steps = 3 x 381, 9.2h, 28.2s/step, 峰值显存 29.5G/34.1G):
  ep1 段均值 1.294→0.578, ep2 0.445→0.476, ep3 0.475→0.520 — epoch 0 后进入
  ~0.48 平台期不再下降: 可记忆的模板/reason 部分已背完, verdict token 始终学不会
  (若 verdict 学会, loss 应再降 ~0.33).
分布内自检 (128 细胞子集): ep1 AUC 0.591, ep2 0.680, ep3 0.577 — 无一接近 1.
选取 adapter_v2_ep2 (自检最高).

J1.1 结果 (adapter_v2_ep2):
  IndustryOR test 240: AUC 0.7166 | t=0.5 det 1.6% (1/61) FP 0.0% (0/179)
    per-arm AUC: z0 0.641, z1 0.770, z2 0.684
  RetailOpt train sanity 381 (全量): AUC 0.6428 | t=0.5 det 0.0% (0/294)
  p_fail 分布整体下移 (train max 0.438, test wrong max 0.500), t=0.5 退化;
  Youden 工作点不可用 (test det 57% @ FP 27%).
  verdict 坍缩仍存在: 自由生成 240/240 全判 pass; 但 reason 已变成输入相关
  (模板多样 + 从输入复制 objective 数值), 修复 4 对 reason 生效、对 verdict 无效.

J1.1 vs J1 vs 基线 (IndustryOR, AUC / det@0.5 / FP@0.5):
  J1.1 ep2 (381 细胞, 3ep, vtok x40)   0.717   1.6%    0.0%
  J1 v1 ep1 (316 细胞, 1ep)            0.678   19.7%   5.0%
  Open-Jev off-the-shelf               0.662   1.6%    0.0%
  A1 self-consistency                  —       16.4%   5.0%
  D2 rule gate                         —       9.8%    5.6%

总结论: 排序信号小幅增强 (AUC 0.678→0.717, 两轮均高于 Open-Jev 0.662), 但核心
前提失败 — 两轮训练分布内 AUC 都远低于 1 (0.569 / 0.643), 模型连自己的训练集都
分不开, 且 verdict 生成坍缩未消除. 判官任务 (从 题面+代码+目标值 推出 witness
标签) 对 27B + LoRA r16 + 381 样本 + 空 think 前缀的设定而言不可学; 测试集的
AUC 优势可能来自 IndustryOR 表面特征相关性而非真正的判官能力, 不宜采信.
后续若继续: 需要让模型在 think 块内真正推理 (去掉空 think 训练格式) 或改用
执行式检查器特征作为输入, 而非堆 epoch/样本.

8. v2 文件清单 (新增)
---------------------------------------
  train_v2.jsonl / train_eval_v2.jsonl / train_cells_v2.jsonl / stats_v2.json
  train_j1_v2.py / run_train_v2.sh / auto_eval_v2.sh
  adapter_v2_ep1/ adapter_v2_ep2/ adapter_v2_ep3/   (ep2 为选用)
  logs/train_v2_metrics.jsonl                       训练日志 (1143 steps)
  logs/eval_v2_test.{metrics,predictions,log}.json(l)   IndustryOR (ep2)
  logs/eval_v2_train.{metrics,predictions,log}.json(l)  分布内 sanity (ep2)
  logs/v2_pipeline_status.txt / v2_picked_adapter.txt
  metrics.json  已更新含 v2 聚合

注意: eval_j1.py 的 rates() 有重复 "fp" 键 bug, 原始 eval_*.metrics.json 里
t05_score.fp 是计数而非比率; metrics.json 与本 README 已用正确比率
(fp_rate = fp/n_neg). train_eval 以 --no-gen 运行, 故其 unparsed=316/381
是预期 (未生成), 非解析失败.

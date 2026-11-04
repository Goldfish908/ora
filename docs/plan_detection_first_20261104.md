# 下一阶段计划:检出端优先(Detection-First)

日期: 2026-11-04
状态: 执行中
前置复盘: 修复端已验证(playbook 营救 97%),检出端是瓶颈(D2.1 矩阵 det 33.3%/FP 12.9%,
端到端真实收益 ≈ 检出率 × 修复率 ≈ 32%)。本阶段把所有资源押到"无 gold 条件下的检出率"。

## 核心决策

**暂缓 1k 数据扩产**,等 J1 判官结果决定 SFT 数据投向(修复器 vs 判官 vs 建模器)。
避免在方向未定时烧 API 流量录错数据。

## 任务序列

### N1. J1 跨数据集判官收尾(远程 A800,agent-7)
- 监控训练(train_metrics.jsonl,~26s/step)直到 adapter 保存成功
- 跑 eval_j1.py:RetailOpt 316 细胞训练 → IndustryOR 240 细胞测试
- 对照基线:Open-Jev off-the-shelf AUC 0.662(IndustryOR)/ 0.534(RetailOpt)
- 判定:J1 AUC 显著超过 0.662 → 判官路线成立,检出端架构以判官为主;
  否则 → 检出端需要第三支柱(规则+自一致性集成,或专用分类头)
- 产出:j1_judge README + 结果落档 + commit

### N2. gapcheck60 确认 anchor margin≥15% 阈值
- 动机:D2.1 消融发现"违例幅度≥15%"能把 FP 12.9%→4.7%(J=+0.194),
  但该阈值是在 240 个 IndustryOR 测试细胞上选的,有测试集选择偏差风险
- 做法:在 gapcheck60(F1-F4 的 v1/v2/v3 变体,champion-only 过拟合检查集)上
  独立验证 margin∈{0%, 10%, 15%, 20%} 的 det/FP/J 曲线
- 判定:若 15% 在 gapcheck60 上同样改善 J 且 FP≤5%,则固化为默认配置;
  否则回到全阈值扫描并报告诚实结果
- 产出:docs/paper/d2_spec_evolution_v1.0.md 增补 + commit

### N3. 剧本跨分布迁移实验(回应"同分布胜利"质疑)
- 动机:P2 的 97% 营救是 RetailOpt 幻影→RetailOpt 幻影,审稿人必问迁移性
- 两个子实验:
  a) held-out 题型:幻影剧本蒸馏时留一族 RetailOpt 题型不参与,测该族上的营救率
  b) 跨数据集:把幻影剧本原样应用到 IndustryOR 上构造的同类错误
- 判定:迁移后营救率 ≥60% 即为阳性信号(显著高于无剧本基线 17.5%)
- 产出:docs/paper/p2_repair_playbook_v1.0.md 增补迁移小节 + commit

### N4. 决策点:SFT 数据方向 + 1k 扩产启动
- 前置:N1 完成
- 若判官路线成立 → 首批 LoRA 数据投判官(含 witness 自动化攒的判定样本)
- 否则 → 按原计划扩产修复样本(每题多常数/多约束/多注入点,目标 1k+)
- JEV 集成探索继续作为旁路(docs/paper/jev_integration_exploration_v0.1.md),
  若判官路线成立,优先评估 Open-Jev 辅助 witness 的位置

### N5. 端到端总装实验(论文主表)
- 前置:N2、N3 完成,N4 已启动
- 流程:D2.1 规则门(预求解)→ 剧本条件化修复 → witness 重判
- 在 held-out(gapcheck60 + IndustryOR 测试细胞)上跑全链路
- **双口径报告**:有 gold 监督(目标值匹配可用)/ 无 gold 监督(仅规则+判官)
  ——后者是通用性主张的依据
- 对照:ReLoop 同模型(Qwen3.8-27B)基线

## 跨切关注

- 所有新实验从本阶段起一律双口径(gold / no-gold)记录
- commit message 不含单引号;runs/、data/ 不入库
- authoring/修复调用一律关思考(enable_thinking=False)
- 失败样本归档保留(DPO 负例库存)

## 风险登记

| 风险 | 缓解 |
|---|---|
| J1 AUC 不超基线 | 检出端转集成方案(规则∨自一致性∨轻量分类头) |
| 15% 阈值在 gapcheck60 不成立 | 报告诚实曲线,用 gapcheck60 重选阈值并以 IndustryOR 为验证 |
| 剧本迁移阴性 | 收缩主张为"族内知识复用",迁移交给判官/规则层 |
| API 再次宕机 | 看守进程模式复用(/tmp/p1_refill_when_api.sh 模板) |

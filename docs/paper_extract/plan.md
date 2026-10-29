# Plan: L2/L3 协同训练方案设计（论文精读 → 方案共设计）

## 背景
用户的系统：LLM 输出 MILP formulation → SCIP/PlanB&B 求解。梯度不可穿透，协同训练三形态（奖励共享 / bilevel / co-adaptation）。已确认 PlanB&B = Strang et al. AAAI 2026（外部方法，MuZero-for-B&B）。当前决策焦点：WM 住 L2（实例/formulation 级元模型）与 L3（agent 决策层）的可能性。用户明确：现有想法未定稿，需要先精读相关论文，再共同设计有创新、可实践的方案。

## Stage 1 — 并行论文精读（explore 子代理 ×3）
- Agent A「L2 先例组」：Scavuzzo et al. 2024 (ML-augmented B&B 综述)、Hendel et al. 2022 (B&B 树大小估计)、Fischetti et al. 2019 (时限内可解性预测)、Zarpellon et al. 2021 (lookback branching)、Hosny & Reda 2024 (MILP 配置)、SATzilla 2008。
  提取：特征集、预测目标、在线/离线形态、数据协议、局限、对 L2 设计的启示。
- Agent B「L3 与奖励模型组」：OR-PRM (ICLR 2026)、Pathwise (ICML 2026)、LLM4Branch (ICML 2026)、CoBench 是否存在公开版本、Gao et al. 2022 (RM overoptimization)、LATS/RAP 简述。
  提取：值/奖励模型的状态表示、训练信号来源、搜索集成方式、预算设置、抗 Goodhart 机制。
- Agent C「solver 反馈 RL 与课程组」：SIRL (NeurIPS 2025) 奖励设计细节、StepORLM (ICLR 2026) 过程监督、ACEvo 训练协议、PAIRED/UED 课程生成。
  提取：reward 具体形式、solver 反馈粒度、交替/课程协议、塌缩防护措施。

## Stage 2 — 方案设计（主代理综合）
基于 Stage 1 报告 + 前几轮已读文献（FormuEvo、MILP-Evo、PlanB&B 全文级理解），产出：
- 研究定位与贡献声明（novelty 边界：PlanB&B=基底、FormuEvo/MILP-Evo=单侧、OR-PRM/Pathwise=L3 邻居）
- 具体方案：L2 元模型（数据协议/特征/目标/验收）、L2-as-reward-model 的 GRPO 设计、co-adaptation + 对抗课程 + 弃权架构、L3 专家迭代试点
- 实验协议：分布选择、基线、指标、消融
- 里程碑与风险登记册
输出：/mnt/agents/output/co-training-design.md（供用户评阅修改）

## 交付
设计稿 md 文件 + 对话内要点总结。docx 待方案定稿后再转。

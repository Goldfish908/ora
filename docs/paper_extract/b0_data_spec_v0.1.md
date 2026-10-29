# B0 数据规格 v0.1

状态：已裁决定稿（合并三方审查意见）
生效条件：与 schema v0.3 升版（含 P0 修复）同步落地，derived 全量重算一次
变更纪律：本规格任何变更升版本号 + ledger 落账

---

## 0. 定位

**B0 是 E 的学习型代理模型（learned surrogate）与前置筛选器**：在不调用真实评价环境的情况下，根据当前搜索状态和候选动作预测其评测后果，用于候选排序、预算分配和风险过滤。

- **E 始终是标签来源和最终评价权威**。B0 不做终审，只做粗筛。
- 首版科学假设：**在相同真实评价预算下，A+B 优于 A**（更快或更稳定地找到高质量方案，或达到同等质量时消耗更少真实评价）。
- B0 预测的是**求解过程**（候选修改 → 分数/错误/可行性/耗时），不是供应链状态演化。最终产物定名：面向供应链与工业制造组合优化的**求解过程 World Model**。

## 1. 输入 X

每条 TransitionRecord 必须可重构以下字段。

**铁律：所有上下文字段必须能用 `SearchState.from_events(events, as_of_seq=t)` 重构，禁止任何未来信息。**

| 组 | 字段 | 来源 |
|---|---|---|
| 问题 | problem_class、instance_id(hash)、规模特征、约束类型计数 | ProblemSpec 摘要（适配器产出） |
| 搜索上下文 | step_idx、budget_total、budget_remaining、incumbent_score（as_of=t）、stagnation_steps、已评估候选数、失败计数、archive top-k 摘要 | SearchState 派生视图 |
| 动作 | 候选内容（见 §7 Candidate 类型约定）、与父代差异摘要、parent_score、谱系深度 | CandidateRecord + 父代 |
| 决策状态 | state_snapshot_id、choice_set_id、candidate_position、choice_set_size | 见 §2 排序标签 |
| 出处 | policy_model_id、harness_version、protocol_version、arm_id、seed、sandbox_image_digest、dataset_manifest_digest、score_transform_version | HarnessSnapshot / ledger |

## 2. 标签 Y

### 2.1 状态与可观测性（可空 + 掩码，禁止用 false 冒充"未知"）

- `evaluation_status`：completed / precheck_rejected / runtime_error / timeout / executor_error
- `feasible`：**nullable bool**（代码未执行成功时为 null，不是 false）
- `score_valid`：bool
- `runtime_ms` + `runtime_censored`：bool（超时时 runtime 为右截断数据）
- 每个预测头配对应 `label_mask`

### 2.2 分数字段（全量保存）

`raw_score`、`normalized_score`、`parent_score`、`incumbent_score_before_action`、`delta_vs_parent`、`delta_vs_incumbent`

- 统一口径：**归一化后越大越好**。原始目标方向（最小化成本/最大化收益）由适配器完成方向与尺度归一化，并记录 `score_transform_version`。
- 候选筛选的主决策标签是 **delta_vs_incumbent**（delta_vs_parent 保留作辅助）。

### 2.3 排序标签：choice_set_rank（替代同父排序）

只有满足以下全部条件的候选才可互相排序：

1. 来自同一个 `state_snapshot_id`；
2. 同一问题与评价器版本、相同评价数据；
3. 组内候选**全部**获得真实评价（无 early-stop 遗漏）。

标签：`choice_set_rank`（同一决策状态下完整候选集合中的名次）。
BestOfN 天然提供此类数据。

**已知边界**：当前四臂中仅 BestOfN 产生 choice_set_size ≥ 3 的完整组；GR/iterative 每步单候选（choice_set_size=1，不进排序评估）。故排序头早期数据 BoN 主导，结论不可外推至搜索中段状态的重排。A1 引入 K 候选机制后覆盖才会丰富。

### 2.4 lineage_value@H（二期标签，先记录不训练）

- 定义：未来 H 次真实评价内是否成为 incumbent 祖先；
- `lineage_observation_complete`：是否拥有完整 H 步观察窗口（运行末尾候选标 censored，不记 false）；
- `derived_from_future=true`：**只能作为 Y，绝不进入 X**。

## 3. 划分规则（防泄漏，三级）

```text
L1 插值：按 run_id 分组切分（同 run 相邻候选绝不跨 train/val）
L2 泛化：按 instance 留出
L3 迁移：按 problem_class 留出（B0 换题型重训 vs 迁移——D0 预演）
禁止：按单条 transition 随机切分
```

## 4. 覆盖要求（readiness 参考，**不是阻塞探针的闸门**）

### 4.1 执行失败样本
- 聚合执行失败占训练数据目标 10%–30%；
- 单错误类别作独立预测类的门槛：训练集 ≥100 条、验证/测试各 ≥20–30 条；不满足则并入 other_error，但保留原始细分类标签；
- 自然分布与增强分布分别统计。

### 4.2 feasible=false
- 目标 ≥10%，分母限定为"可获得 feasible 标签的样本"；
- 自然不足时**只补训练集**；验证/测试保持自然分布；natural-only 与 augmented 结果分别报告。

### 4.3 近零 delta（决策边界带）
- `|normalized_delta_vs_incumbent| < ε_problem`，ε 按问题分数尺度/评价噪声/最小有意义差异确定；
- CO-Bench 初期可暂用 0.01，但**配置化，不写死进通用 schema**。

### 4.4 完整候选组
- ≥30% 已评价 Transition 属于 choice_set_size ≥ 3 的完整组；
- 每个用于正式排序评估的 split 目标 ≥50 组完整 choice set（目标值，非硬门槛）；
- 报告 choice set 数量、平均大小、候选对数量。

### 4.5 来源覆盖（分层，非均匀）
- 训练集保证每个主要数据生成策略（policy_id/harness_id/arm_id）最低覆盖，任何单一来源不垄断；
- 测试集保留自然运行分布；
- 需要平衡时用采样权重，不改测试分布；
- 问题类型与候选生态位的覆盖优先于臂间均匀。

### 4.6 b0_augment 纪律
- 增强候选**继承源父代所在 split**（源轨迹在训练集，扰动候选也必须在训练集）；
- 正式测试集 natural-only；增强数据只进训练集或单独的增强验证集；
- 打 purpose="b0_augment" 标记，与性能轨迹物理分桶。

## 5. 探针计划（阶段 A 数据落账后立即执行；LogReg/GBDT/规则基线，不碰神经网络）

| 探针 | 任务 | 指标 |
|---|---|---|
| 1 | P(error) | AUROC + 校准曲线 |
| 2 | P(feasible \| executed) | AUROC |
| 3 | delta_vs_incumbent 排序 | 组内候选对准确率 / Kendall τ |

### 探针 4：离线 A+B 重排（一步离线重放）

条件（缺一不可）：
- N 个候选来自同一 state_snapshot_id 的**完整** choice set；
- 全部被真实 E 评价；
- B0 训练数据不含这些测试 choice set 及其近邻谱系；
- 测试 choice set 在数据划分完成后才可用于重放。

对比策略：随机选 m（多次采样报均值与区间）/ Agent 原始顺序 / 简单规则基线 / **B0 排序 Top-m** / Oracle（仅作理论上界，非可实现基线）。

输出：Best@m、相对 Oracle 的 regret、Top-m 命中全局最优概率、达到指定分数所需真实评价次数、不同 m/N 的预算—效果曲线。

**能力边界声明**：探针 4 验证固定候选集合上的**单步重排**能力，不覆盖 B0 介入后的多步状态分布漂移。它是在线 A+B 实验的强预检，不能替代在线闭环验证。

## 6. 验收口径

- **通过**：至少一个决策相关头（better_than_incumbent / delta_vs_incumbent / choice_set_rank）在分组验证集上稳定超过规则基线，**且**探针 4 中 B0 排序在多个 m 值下优于随机与原始顺序；
- error / timeout / feasible 为辅助安全头，单头无信号不阻塞，但需记录原因；
- 所有决策相关头均无信号 → 优先检查状态表示、标签噪声、数据覆盖，**不直接扩大模型**；
- §4 配额为 readiness 参考，不构成探针的前置阻塞条件。

## 7. 架构约束（数据集无关性）

### 7.1 六层抽象（逻辑层）
ProblemSpec / **SearchState**（as_of_seq 重构的派生视图，有明确 schema 与重构函数，不强制物理表）/ Candidate / Executor / Outcome / TransitionRecord。

### 7.2 Candidate 类型约定
**公共强类型字段 + adapter 扩展字段**。CO-Bench 的 code/diff 属于 adapter 扩展，不得提升为所有数据集的必选字段（未来候选可能是调度方案、库存参数、MILP 修改、启发式、动作序列）。

### 7.3 依赖方向（静态审计 + 合同测试）
```text
core/contracts ← miniloop
core/contracts ← adapters/cobench
composition_root → miniloop + adapters/cobench
```
- miniloop 与通用 schemas **禁止 import 任何 CO-Bench 专属模块**；
- **Dummy Adapter 合同测试**：不安装/不导入 CO-Bench，用玩具 Executor（约百行的玩具优化环境）完整跑通 miniloop 闭环——这是"换数据集不换主循环"的实证；
- **Schema 污染检查**：通用 schema 中不得出现 eval_func、CO-Bench 实例路径、特定 solve() 约定。

## 8. 落地绑定

- 本规格引起的标签/schema 变更（nullable feasible、choice_set 字段、score 字段组、掩码）**与 P0 修复合并为一次 schema v0.3 升版**，derived 全量重算一遍，版本号与口径变更 ledger 落账；
- 64 步单臂单题运行定名 **Soak Test**（账本一致性/上下文膨胀/资源泄漏/谱系关联/回放一致性），不产出性能、泛化或论文对齐结论；
- 矩阵分析计划必备两表：臂间对比（Best@E-budget + 搜索曲线 AUC）+ 生态位分布表（§4 达成度自检）。

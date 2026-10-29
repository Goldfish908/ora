# Prompt for Coding Agent — Stage 2 下一轮实验（三项）

> 背景：Search WM Stage 2 已拿到 Phase C POSITIVE（gcol17/gcol7，ttt W=1/1，mean Δ(C−W)=6.0，mean Δ(R−W)=7.0，n=2 无统计显著性 claim）。gcol dev split 已耗尽（15/15），gcol 线封存。本 prompt 定义下一轮三个实验任务：**两个零 evaluator 成本的离线实验优先**，一个 harness 修复，最后才是新 family 预筛（需要人工批准后才动 evaluator）。
>
> 纪律沿用 CONTEXT.md §5–§8：raw 只追加不重写；任何比较口径变更先预注册再揭盲；所有产出落 EXPER_REGISTRY.md / CURRENT.md；测试产物带 RUN_MARK 前缀 + purpose 标记；不动宿主机无关进程；不 commit/push 除非明确授权（本任务授权 commit，不授权 push）。

---

## Task 0 — Harness 修复（前置，阻塞后续所有在线实验）

**问题**：control policy 在所有 seed 失败、无 incumbent 时崩溃（已记录，未修）。

**要求**：
1. 复现该崩溃路径，写出触发条件的最小描述（进 EXPER_REGISTRY.md 的 known issues）。
2. 修复策略：**不引入新行为语义**——当无 incumbent 时，control policy 显式进入 fallback（可用：随机挑一个 valid 候选 / 或声明该 step 为 NOP 并记录 `fallback_reason=no_incumbent`），不允许静默沿用任何未记录的默认行为。
3. 修复后跑现有 23 个测试 + 新增至少 2 个针对该路径的单测，全绿才算完成。
4. 这是一个 schema/行为变更的边缘：fallback 事件必须落 trace 字段（`fallback_reason`），字段加入即升 schema minor version 并落账。

---

## Task 1 — 离线排序器对照实验（零 evaluator 成本，最高优先）

**科学问题**：Phase C 的赢，是 LLM 语义先验（judge）的赢，还是 WM 状态特征的赢？这决定下一步投资方向。

**数据（全部已落账，不许新跑 episode）**：
- choice-set farm 的全部候选组（`purpose=b0_choiceset_farm`，约 25–30 候选，含 mid-search states）
- Phase A/B/C 全部 transition（82 条 + Phase C 落账部分）中带 choice_set / 多候选记录的组
- replay simulation 用过的 3 个可用 choice-set 组也并入，但标记来源

**四个排序器（全部离线打分，不调 evaluator、不调 LLM 生成）**：
1. `random`：随机排序（100 次重采样取均值，作为地板）
2. `judge_diff`：现用 diff-summary judge 的落账排序（直接从 trace 取，不重跑）
3. `judge_fullcode`：full-code judge——把候选完整代码（而非 diff 摘要）给同一 judge 模型版本打分。**这是唯一允许的新 LLM 调用**，预算上限 20 万 token，超出即停并报告。
4. `model_only`：risk head × P(gain>0) 的纯模型排序。P(gain>0) 头本次新训练：目标是 Δscore>0 的二分类，特征用现有浅层特征集，LOEO 纪律同 Phase B。若该头训出来 AUROC < 0.55，如实报告"model_only 无信号"，不要硬凑。

**评估口径（预注册，写进报告头部再揭盲）**：
- 主指标：**within-step pairwise ranking accuracy**——同一搜索时刻的候选组内，排序器把"实际 Δscore 更高"的候选排前面的比例（ties 计 0.5）
- 次指标：每个组的 bsf@1 / bsf@2（以组内真实最优为命中）
- 报告每个排序器在每个组上的逐组结果 + 汇总，不许只报汇总
- 与 replay simulation 的 hybrid@1=.8204 / random=.7547 / original-order=.8041 做口径对齐说明（若指标定义不同，明说，不许混用）

**判决规则（预注册）**：
- `judge_fullcode` 显著优于 `judge_diff`（pairwise accuracy 差 > 0.05 且组级胜率 ≥ 2/3）→ 后续在线实验固定用 full-code judge，升 judge 版本号
- `model_only` 接近 `judge_diff`（差距 < 0.05）→ gain 头路线 a 复活，立项"judge 逐步退出"实验
- `model_only` 远低于 judge → 确认 hybrid 分工是当前最优，judge 作为固定部件，转入成本优化
- 所有结果无论正负都落账

**产出**：`docs/offline_ranker_comparison_v0.1.md`（含逐组表 + 口径定义 + 判决）+ 数据落 `~/stage2/runs_search/offline_ranker/`。

---

## Task 2 — 可学性剖面表（零 evaluator 成本，与 Task 1 并行）

**科学假说**：WM 可学的不是"题目"，而是"搜索动态中的条件结构"。具体：E[score] = P(valid) × E[score|valid] 的分解里，**哪个因子有状态依赖性，哪个头就可学**。
- 预测 A：P(valid) 状态依赖高 → risk 头可学
- 预测 B：E[score|valid] 状态依赖高 → gain 头可学
- 预测 C：两者都低 → 该 family 对 WM 无意义，不应投入

**对每个已有数据的 family（gcol / jssp / binpack，以及任何已落账的其他 family）计算剖面**：

1. **P(valid) 状态依赖度**：
   - 基线：marginal base-rate 预测器（每 family 一个全局 valid 率）
   - 对照：现有浅层特征 + 状态特征模型（复用 Phase B probe 管线）
   - 指标：ΔBrier = Brier(baseline) − Brier(state model)；以及 5-fold 分组 CV 的稳定性
   - 已知锚点：gcol 上 ΔBrier ≈ 0.1262 − 0.0772（risk 头三次确认），用它校准口径正确性

2. **E[score|valid] 状态依赖度**（只在 valid transition 上算）：
   - 把 score 的方差分解为三部分：候选身份（candidate/prompt 语义）、状态特征（浅层集）、残差
   - 简单做法：三个模型对比——intercept-only、candidate-id-only（用候选的语义 embedding 或 hash 分组均值）、candidate-id + state features；报告每步的 ΔR²
   - 已知锚点：gcol 上 state 贡献 ≈ 0.000087（gain 浅层头死亡判决），同样用来校准口径

3. **汇总表**：每 family 一行——P(valid) 状态依赖度、E[score|valid] 状态依赖度、已观测到的头可学性事实（risk 可学/gain 死/无方差/恒定赢家）、假说预测 vs 事实是否吻合。

**判决规则（预注册）**：
- 若三个 family 的预测全部与事实吻合 → 剖面表升级为**新 family 投入的先验筛选器**，写进设计文档 §2
- 若有 family 不吻合 → 如实报告，列出可能的混淆因子（样本量、特征集表达力、状态定义），不许强行解释

**产出**：`docs/learnability_profile_v0.1.md` + 剖面计算脚本进 repo（可复现）。

---

## Task 3 — 新 family 预筛口径（预注册文档；执行需人工批准）

**只写口径和预注册，不执行任何 episode**。执行开关在人工。

**候选 family**：JSSP（仅限有决策面的子集，见下）、以及 repo 中可用的其他 problem class。gcol 封存，不许动。

**预筛流程（每个候选 family）**：
1. 用 control_v1_eps0.2 在 1–2 个 dev split instance 上各跑 1 个 episode（eval_budget ≤ 14）
2. 检查三条标准：
   - **C1 分数方差**：episode 内 distinct score 数 ≥ 3（排除 binpack 型无方差）
   - **C2 阶梯结构或持续改善**：best-score 曲线存在 ≥ 2 次改善跳变（排除一步定型）
   - **C3 候选可分辨性**：至少一个搜索时刻的候选组内，事后看 Δscore 有 spread（即"当时确实有得选"）
3. 三条满足 ≥ 2 条 → 进 Phase C 复现候选池；否则标记 `wm_unsuitable` 并记录原因
4. **JSSP 特别条款**：必须先排除"恒定赢家"实例——若 episode 内同一候选 lineage 从 step ≤ 3 起垄断 best，则该实例不入选

**预注册内容（在跑任何 episode 前写死）**：
- 上述 C1/C2/C3 阈值
- 入选后的 Phase C 复现配置：2–4 个 virgin units、paired by seed、W/R 共享候选池、ttt 主指标、margin=1 eval、judge 版本以 Task 1 判决为准
- 预算上限：预筛阶段每 family ≤ 1 个 episode 当量；总预筛 ≤ 4 episodes

**产出**：`docs/family_prescreen_prereg_v0.1.md`，提交后等人工批准再执行。

---

## 执行顺序与汇报要求

1. **Task 0 先做**（阻塞项），完成后立即汇报修复方式 + 测试结果。
2. **Task 1 与 Task 2 可并行**（都是离线），但各自独立落账、独立报告。
3. **Task 3 只交预注册文档**，执行等批准。
4. 每个 Task 完成时同步更新 EXPER_REGISTRY.md 和 CURRENT.md；commit message 带 task 编号。
5. 遇到任何与既有落账数据矛盾、或需要动用 test split、或需要超预算的情况——**停下来上报，不许自行扩权**。
6. 阴性结果（model_only 无信号、剖面假说不吻合、family 全部 wm_unsuitable）同样是合法产出，如实写，不许补跑凑数。

# Stage 2 Search WM：对标目标 · 技术设计 · 实验设计（v0.1 草案）

> 定位：工程实验导向——快速判断业务思路可行性，服务内部资源申请。
> 证据标准 = 可路演（convincing demo + 可信趋势），非可发表；
> 护栏 = virgin units 预提交 + 负结果如实落账。
> 细节实现权在 coding agent，本文档只钉架构选择、对照结构、判据与口径。
> 2026-09-03。

---

## 0. 冻结定义与两个"说破"

**WM 定义（冻结）**：

```text
Search State s_t + Search Action a_t → 决策相关未来 / 下一搜索状态（含不确定性）
```

用途：agent 在真实执行前对候选搜索动作做低成本 imagination，把昂贵 evaluator
预算分配给最值得的动作。

**说破一（随机核 + 确定性更新）**：s_{t+1} 的大部分分量（budget 扣减、archive
合并、stagnation 计数、step 推进）由 harness 确定性计算，不需要学。
**可学的核心只有一个随机核 P(outcome | s_t, a_t)**：P(complete)、E[gain]、
E[cost]、uncertainty。WM 不做 solver 内部模拟。

**说破二（单步边界声明）**：当前验证的是"单步决策分配价值"。"想象搜索路径"
（多步 rollout）存在误差复利问题，不在本阶段承诺范围内，是 roadmap 项。

---

## 1. 对标目标（三个层次）

### 1.1 实验内对照（每次实验自带）

| 对照 | 回答的问题 |
|---|---|
| control policy（固定启发式：种子→MUTATE→停滞逃逸） | 系统现状基线 |
| random selector（同 K/m 结构，随机选） | 隔离"选择机制"本身的贡献 |
| 规则基线（如 risk-only 过滤） | 浅规则能白捡多少 |
| 浅特征 WM（无 state 维度） | state 条件化的净增量（消融） |
| LLM judge（语义先验） | 语义通道的价值与成本 |
| oracle ceiling | 理论上界，仅参照不可实现 |

判读纪律：WM-guided 必须赢 random 和规则基线才算有信号；赢 control policy
才算有系统价值；与 oracle 的距离只作参照不作判据。

### 1.2 学术对标（定位用，不深追）

| 工作 | 它做什么 | 我们的差异 |
|---|---|---|
| FunSearch（DeepMind 2023） | LLM + 进化程序搜索，island 种群 | 无 WM：候选全靠真评价筛选；我们要省的就是真评价 |
| OpenEvolve / ReEvo / EoH | LLM 进化式算法设计 | 同上：搜索过程无结果预测，评价预算无分配智能 |
| AIDE | ML 工程 agent | 任务域不同，同样无 outcome model |
| GEPA | LLM 反思 + 文本基因组 Pareto 进化 | 我们 M1 已用于 self-evolution 面；它是进化器不是 WM |
| MuZero / model-based RL | decision-centric 动力学模型 | 思想源头：只学决策相关量；我们在 LLM-agent 搜索语境实例化 |
| Plan B&B / Compiler WM | solver 世界学习 | 同学 solver 世界；我们在搜索/episode 层级而非节点层级 |

**一句话定位**：别人用 LLM 进化"产生更好的候选"，我们学"哪个候选值得
花真评价"——评价预算经济学是无人区，这就是差异化的故事核。

### 1.3 业务对标（资源申请语言）

- **现状基线**：人工调参 / 默认求解器配置 / 无差别跑满预算；
- **单位经济学表**（必须产出）：一次真实评价 = X 秒 solver 机时
  （商业 license 场景直接折算钱）；一个 episode 总成本；WM 想象成本
  （特征模型 ≈ 0，LLM judge ≈ 万级 token/次）；
- **KPI 翻译**："time-to-threshold 降 40%" → "同样方案质量，求解时间减半"；
  不说 AUROC、不说 bsf@8。

---

## 2. 技术设计

### 2.1 数据契约（SearchTransition）

```text
SearchState s_t:
  problem 摘要（family、规模特征、unit_id hash）
  incumbent {score, candidate_id}
  archive top-k 摘要
  search history 摘要（近期 Δscore 轨迹、失败计数）
  budget {total, remaining, remaining_fraction}
  stagnation_steps
  step_id

SearchAction a_t:
  type ∈ {SEED, MUTATE, REFINE, ESCAPE, ALLOCATE(预留)}
  target（父代引用）
  option 参数槽（scope/parameters/budget/stop_condition —— 预留，
                 对接 A+B_θ+E 的 o_τ 六元组演化）

Outcome:
  complete: bool（及其 failure_type 细分）
  gain: Δscore vs incumbent
  cost: runtime / evaluator 秒数
  per-instance 分布（若可得）

Transition 完整性要求：
  (s_t, a_t) → outcome + s_{t+1}；state hash 链 + parent 链接；
  **available_actions：每个决策点记录完整可选动作集**（不只是 taken action）
  ——离线重放与 off-policy 评估的前提；
  口径字段：policy_id / model_id / harness_version / schema_version；
  raw append-only，derived 可重建。
```

### 2.2 模型架构（双通道混合分工，Case C 实证支撑）

```text
                 ┌─ risk 头：浅特征（执行上下文/静态代码特征）
P(outcome|s,a) ──┤   → P(complete)、P(timeout)   【Case C：浅特征赢】
                 │
                 ├─ gain 头：E[Δscore]            【三路线见下】
                 │
                 └─ cost 头：E[runtime]、uncertainty 输出
```

gain 头三路线（Phase C 前做一次明确取舍）：

| 路线 | 形态 | 成本 | 风险 |
|---|---|---|---|
| a 纯浅特征 | ridge/GBDT | ≈0 | Case C 已证质量排序掉到 baseline 级 |
| b LLM judge 在线 | 每候选一次调用 | 中（仍 << E） | 引入第二模型的漂移/预算管理 |
| c LLM 离线标注→蒸馏进特征 | 一次性 | 低 | 蒸馏保真度未验证（终局方向） |

**demo 阶段建议 b，路演材料里诚实列出想象成本，净收益为正即可。**

确定性状态更新器：harness 内实现，不进模型。

### 2.3 训练与评估纪律

- 划分：leave-one-unit-out（episode=unit 时即 LOEO）；禁止 transition 级随机切分；
- 特征铁律：任何特征可由 as_of_step=t 重构，禁止未来信息；
- 评估按两层：**头指标**（Brier/校准曲线、Kendall τ）+ **决策指标**
  （离线重放 Best@m、regret vs oracle、vs random/原始顺序）——后者才是
  planning value 的预演；
- 生态位覆盖仪表盘：失败/超时/近零 delta 分布随数据采集实时可看，
  覆盖不足的生态位定向补采（不删不过滤）。

### 2.4 与 self-evolution plane 的边界

WM 数据（连续性能规律）只进 telemetry，不强行规则化成 memory/skill
（M1 已定纪律）；memory/skill 走 replay gate 晋升通道，与 WM 互不越界。

---

## 3. 实验设计

### Phase A — sequential transition 数据采集（进行中）

- 6 virgin gcol units（预提交、import-time assert 防重叠）× 14 evals × ≤120s；
- 控制策略：4 seeds → MUTATE incumbent、停滞 3 步逃逸；
- **待裁决建议：ε-随机化（~20% 步随机选动作类型）**——否则 REFINE 无数据，
  Phase C 的 WM 将在训练未覆盖的动作区域被查询（off-policy 空洞）；
  若改策略：落账 + 前后 episode 标不同 policy_id；
- 每 transition 核账；异常 run 补 ABORTED 记录，不原样重跑。

### Phase B — 离线 gate（零成本，数据落账后跑一次）

- 划分 LOEO；风险头 + gain 头 + **状态条件化消融**（全特征 vs 去 state 维度——
  路演第一张图：state 条件化的净增量）；
- 判读三态预注册：
  - GO：决策指标上 WM 排序稳定优于 random/原始顺序（折间方向一致）；
  - NO-GO：方向错误或增量≈0 → 查状态表示/标签噪声/覆盖，不直接扩大模型；
  - **inconclusive（n 小，合法结果）→ 预写追加方案**：加跑 N 个 episode、
    定向采哪些状态、追加预算多少——现在就写，不空转。

### Phase C — 在线验证（demo 导向）

- **系统级对比优先**（业务问的是"整套东西 vs 现状"）：WM-guided 臂 vs
  control policy 臂；random-selector 臂作廉价伴随对照；
- **配对设计**（同 unit 同 seed 两臂配对——小样本下省 run 的关键，不是洁癖）；
- 主指标：**time-to-threshold**（达 oracle X% 所需真实评价数）+
  bsf-vs-evals 曲线；token/机时记辅助账进单位经济学表；
- 误杀审计：被 WM 过滤的候选留档抽验（filtered 留档纪律）；
- 产出物定位：**路演证据包** = 一条 before/after 曲线 + 单位经济学表 +
  virgin units 预提交声明 + （若阳性）state 消融图。

### 成本估算框架

- Phase A：~1M token + ~3h 机时（已在跑）；
- Phase B：≈0；
- Phase C：两臂 × 6 units × 14 evals 配对 ≈ Phase A 的 1.5–2 倍
  （LLM judge 若走路线 b 另计，预估前先实测单价）；
- 总额度纪律：单线预算上限 + 撞闸主动预警，沿用 CO-Bench 线惯例。

### 风险与缓解

| 风险 | 缓解 |
|---|---|
| n 小判不出 | inconclusive 分支预写；配对设计提功效 |
| 动作覆盖空洞（REFINE） | ε-随机化 / 声明 WM 仅在已覆盖动作内选择 |
| demo 选题自欺 | virgin units 预提交 + 判据先钉后跑 |
| policy 漂移致 WM 失配 | policy_id 指纹进每条 transition；换 policy 必重标定 |
| LLM judge 成本侵蚀净收益 | 单位经济学表全成本入账，净收益为判据 |

---

## 4. 里程碑映射与叙事

```text
M1 非参数自进化闭环（已实证：memory/skill 晋升，token 减半）
  → M2 Search WM（当前 Stage 2：Phase A/B/C）
  → M3 持续 WM（第二 problem distribution：恢复更快、旧知识保留）
  → 终局：工业业务世界 WM（业务动作 → 业务后果）
```

Stage 2 Phase C 的阳性结果 = M2 位置的最后一根支柱；届时 M1+M2 双证据
+ M3 roadmap 即构成完整资源申请包。

## 5. 待裁决清单（给 human review）

1. Phase A 是否加 ε-随机化（改控制策略，落账）；
2. gain 头路线 a/b/c 取舍（建议 b）；
3. Phase C 臂配置与配对方案批准；
4. 单位经济学表的口径（solver 机时如何折算业务成本）。

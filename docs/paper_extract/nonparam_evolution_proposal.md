# 非参数自进化扩展方案：Memory / Skill / Harness 三层 + 跨数据集迁移协议

**版本**：v1.0　**日期**：2026-08-29
**前置**：SELF_EVOLUTION_TWO_GEN_TECHNICAL_REPORT（v0.1/v0.2 两代实验）
**调研依据**：`research/nonparam_dim01~05.md`（5 路并行调研，130+ 次检索，关键结论均有 arXiv/GitHub 一手引用）

---

## 0. 总原则：一种协议，四种资产类型

v0.1/v0.2 已验证的核心资产不是 prompt patch，而是**那套协议本身**（evaluator-gated 选拔、阶梯评估、immutable snapshot、预算守恒、数据分区、retain 纪律）。扩展三层不需要新协议，只需要**资产类型系统**：

```
Asset = 公共信封 + 类型载荷 + regime 护照
公共信封：asset_id / locus / version / status / evidence_refs / parent / sha256
类型载荷：POLICY=文本段落 | SKILL=代码骨架 | MEMORY=条目+触发条件 | HARNESS=wrapper 中间件文件
regime 护照：发现该资产时的 {数据集族, 实例规模分布, E 预算, timeout, 模型 id}
```

每种类型的差异只落在三处：**变异算子、结构闸门（Stage 0）、sanity 门**。选拔、晋升、预算、归档、快照机制完全复用。这是避免"每加一层长一套新框架"的关键设计约束。

**层的引入顺序按爆炸半径升序**：Memory（纯 wrapper 侧注入，不改行为链路）→ Skill（代码骨架，影响生成内容）→ Harness（wrapper 策略，影响所有请求）。每层独立 MVP、独立可杀。

---

## 1. Memory 层

### 1.1 调研结论（dim01）
- 你们现有的"复发 ≥2 episode 才入库"闸门被独立验证：selective-addition 实证显示 add-all（全量写入）**劣于无记忆**；Mem0 的 ADD/UPDATE/DELETE/NOOP 四操作是事实标准。
- 记忆条目本身可进化有直接先例：MemSkill（与你们最同构——记忆条目带触发条件、版本化、可进化）、Memory-R1（RL 训记忆操作策略）、MemEvolve/EvolveLab。
- 检索注入：Anthropic Agent Skills 三级渐进披露（元数据常驻 → 触发加载 → 按需读资源）是工业标准形态；top-K 呈倒 U 型但**不存在普适 K**（不同研究最优值 2/10-15/50 不一）——必须自测，不可照抄。
- token 税有据：Mem0 论文的对照显示常驻记忆注入可带来 ~72% 的上下文膨胀——支持你们 v0.3 的 triggered injection 方向。
- 治理：MINJA 污染攻击、raw 轨迹直接回放的负迁移与 false validation confidence 是三类已证实失败模式——支持"只喂变异、不注运行时"的现行纪律作为**默认态**，注入必须以晋升门为前提。

### 1.2 选型
| 决策 | 选择 | 不选 |
|---|---|---|
| 资产形态 | 记忆条目 = {trigger 条件, 内容, support_count, regime 护照}，可 ADD/EDIT/RETIRE | 自由文本笔记堆 |
| 注入策略 | triggered injection（机检信号命中才注入），retrieval_policy_version 冻结进 snapshot | 常驻 system prompt 注入 |
| 写入闸门 | 维持复发闸门 + 语义去重（现行），晋升前不注入 | LLM 自判重要性直接入库 |
| 进化对象分两步 | 先进化**条目内容**（变异源=机检报告+轨迹），再进化**检索策略**（K、触发阈值、排序） | 一步到位同时进化（归因灾难） |

### 1.3 MVP-M1（首个实验）
**问题**：triggered injection 相比"memory 只喂变异"是否带来净收益？
- 设计：单资产变更（注入开关），固定检索策略（K=3、触发=机检信号精确匹配），A/B 两组在 EVO-TRAIN 子池各 ≥3 cases × 2 seeds 配对运行。
- 度量：分数差 + token 税（每 episode 增量 token）双指标；决策要求**分数不劣且 token 税 <15%**，或分数显著优且税 <40%（预登记阈值）。
- 预算估算：~12-16 episodes，约 2-3M tokens，在现行硬顶内。
- 杀线：token 税 >40% 且分数无显著差异 → memory 层回到"只喂变异"，不进入进化。

---

## 2. Skill 层

### 2.1 调研结论（dim02）
"LLM 抄代码比守纪律可靠"的假说现在有**四条独立证据链**：
1. CodeAct：代码动作比文本动作 +20pp；
2. EvolveTool-Bench：代码进化策略 0.603 vs 文本策略进化 0.520，直接同构对照；
3. s1：prompt 时间纪律失控 vs budget forcing（代码级强制）完美可控——与你们 C2 的 0.4464 惨败几乎同一实验；
4. SkillsBench：**自写 skill −1.3pp（伤害！）vs 精选 skill +16.2pp**——技能无验证环净收益为负，这正是你们 evaluator-gated 协议的价值所在。

其他关键结论：验证环主流为执行级（LATM 单测三段式、Voyager 执行+自验证入库）；**Library Drift 实证**——技能库膨胀导致静默失效，解药是结果驱动退休 + 活跃技能上限 + 贡献分日志（你们的 archive 保留全部失败者做 stepping-stone 是对的，但 **active set 需要治理**，这是 v0.2 没有的协议缺口）；FunSearch/EoH/LLaMEA 确认"骨架+LLM 填充"形态，并给出两条纪律：报错=零分（防止垃圾骨架污染）、警惕种子锚定偏置。

### 2.2 选型
| 决策 | 选择 | 不选 |
|---|---|---|
| 资产形态 | code-carrying skill（C6/C7 形态），body=可运行骨架，附 trigger+前提 | 纯文本"纪律"patch（已证伪） |
| Stage 0 闸门 | 结构闸门升级为**执行级**：ast.parse + 沙箱烟雾测试 + 保底路径存在性检查 | 仅 schema 校验 |
| 库治理 | active set 上限（建议 ≤8）+ 结果驱动 RETIRE + 贡献分日志 | 只进不出 |
| 变异 | GEPA 反思层（已接入）对骨架的 docstring/参数/分支做单位点变异 | 整骨架自由重写（报错零分纪律难保） |

### 2.3 MVP-S1（建议提到 GEPA A/B 之前）
就是你们已建的 C6/C7 实测决策点，但按新统计协议执行（见 §4）：每 skill 单独一代（OFAT，不混合变更），paired (case,seed)，晋升=选拔池胜出 + **确认池复测**双门。预算 ~64-128 E 与你们原估算一致。

---

## 3. Harness 层

### 3.1 调研结论（dim03）
- 概念：harness 已被形式化为 H=(E,T,C,S,L,V)（arXiv 2605.29682）。映射到你们系统：**wrapper 缝恰是 C（上下文）+L（控制逻辑）**，冻结线是 E/T/V+预算权威——harness 进化对你们 = **wrapper 中间件文件的进化**，定义上自洽。
- 直接先例三个：
  - **Meta-Harness**：直接搜索 context 构造代码，token 少 4× 反 +7.7 分——证明 wrapper 策略是可搜索空间且有真实收益；
  - **AHE（Agentic Harness Evolution）**：中间件**文件化** + git 回滚 + 每条编辑必须可证伪——与你们 git-based 资产库同构；
  - **Self-Harness**：回归测试门禁的 harness 自进化，其进化产物恰好就是 retry discipline 和 tool-error middleware——正是你们 `_sanitize_history` 所在的位置。
- 预算分配进化可在 wrapper 无训练实现：s1 budget forcing、BudgetThinker 比例注入、TALE 档位。
- 公平性：你们的 E=16 服务端冻结是**架构级**预算守恒，强于文献中所有协议级方案（Kapoor Pareto、HAL、RoboPhD 三同协议）——这是写后续报告时可以强调的方法论优势。
- 风险基线照 DGM：沙箱、时限、域限定、谱系审计，四件齐全方可动 harness。

### 3.2 选型
| 决策 | 选择 | 不选 |
|---|---|---|
| 资产形态 | wrapper 中间件文件（每个 = 一个命名策略文件，如 `sanitize_policy_v3.py`），git 版本化 | 在线自改 wrapper 主文件（无回滚） |
| 首批可进化面 | 历史压缩策略（`_compact_history` 的阈值/占位符规则）、重试与修复策略、注入触发策略 | episode 循环、tool 分发、evaluator 契约（冻结线） |
| Stage 0 闸门 | **回归测试套件**（用历史轨迹做 replay：新中间件不得改变已通过案例的最终输出语义）+ 结构检查 | 无门禁直接进选拔 |
| 预算公平 | 中间件变更不得改变 E=16/token cap 的服务端语义；wrapper 侧省 token 合法，多烧非法 | 任何绕过预算权威的"优化" |
| 安全 | 四件基线（沙箱/时限/域限定/谱系）+ 每条编辑附可证伪假设 | 无假设的"改进" |

### 3.3 MVP-H1
**问题**：`_compact_history` 的压缩策略能否作为资产被进化出更优版本？
- 选它做首个 harness MVP 的理由：已有 baseline（现行规则）、影响面全请求、可 replay 回归、收益双侧（token 降 + 可能分数升）。
- 设计：3-5 个压缩策略变体（手写模板 + GEPA 反思各半），先 replay 回归门（历史轨迹，零 evaluator 成本），通过者进 paired 选拔。
- 决策双指标：token 税下降幅度 + 分数不劣（paired 2σ）。
- 预算：回归门 ~0 E；选拔 ~8-12 episodes。

---

## 4. 跨数据集迁移协议（dim04）

调研确认：跨基准迁移失败已被多方独立复现（MAS 拓扑过拟合、PromptBridge、URS、Cozzuto 不跨 TSP/CVRP 族），你们的 regime-specificity 发现是普遍规律。**成功迁移的共同特征：迁移的是"框架/组合/带触发条件的元技能"，从来不是单点冠军。** 由此设计五条协议：

1. **regime 护照（§0 已入 schema）**：每个资产标注发现环境 {数据集族, 规模分布, E, timeout, model_id}。这是后续一切治理的数据基础，必须在新层上线前补进现有资产。
2. **换域自动降级**：数据集族或预算包线变化时，全部继承资产自动降为 challenger——不删除、不激活，进入再验证队列。裸迁移的证据几乎全负面，没有例外条款。
3. **shadow 再晋升 + 先验衰减**：challenger 在新域走低成本确认（paired、少 case），通过即复职；连续两代未通过的先验权重衰减，但不退出 archive（stepping-stone 原则）。
4. **fitness 多分布化**：EVO-TRAIN 从单数据集族改为 ≥2 族（哪怕第二族规模小），晋升判据从均值改为 **worst-group**（最差族上的表现）——直接压低单分布过拟合，也是对假晋升的结构性防护。
5. **holdout 滚动轮换**（LiveBench 模式）：每次迁移时旧 holdout 降级为 PROMO 池、新建 holdout，防止任何池被长期"隐形适应"。

中期方向（单 lineage 未 plateau 前不做）：archive 按任务族做行为维度分格（丐版 MAP-Elites）+ per-instance 资产选择器（SATzilla/GEPA 范式）——这是"迁移组合而非冠军"的机械化形态。

---

## 5. 选拔统计升级（v0.3 必备，dim05）

在上一轮建议（确认门/配对/行为门）基础上，调研给出了更精确的工具：

1. **配对是第一杠杆**：配对种子的实证等效样本量放大 3-100×——在 E=16 硬约束下，这是让 MDE≈0.15 可检测的**唯一**途径。所有 stage 强制同 (case, seed) 对。
2. **两阶段晋升有直接模板**：GSME（arXiv 2607.13683）在冻结 27B 上实现"K=1 粗筛 → K=3 选拔 → sealed test paired-2σ 确认"，与你们系统几乎同构，可直接作为确认门协议蓝本。
3. **PACE 的 e-process 门**：paired McNemar + e-process 给出 anytime-valid 的晋升判据，报告比固定样本 2σ 省 ~18% 评估，且允许"边评边停"——适合 E 预算严格的场景，v0.3 可选装。
4. **行为漂移门**（维持前轮建议）：n_evals/token 量/停止原因分布漂移超阈 → 转人工。reward hacking 的行为侧检测文献支持。
5. **多资产归因**：多层共存后，严格 OFAT（一代只动一类资产）；需要交互效应时用 2³ 分式因子（Res-IV），8 个 cell 覆盖三类资产的主效应+关键交互，不要全因子。

---

## 6. 实施顺序与决策点

| 序 | 事项 | 预算直觉 | 通过判据 | 杀线 |
|---|---|---|---|---|
| 0 | regime 护照补进 schema 与现有资产 | 0 E | — | — |
| 1 | MVP-S1（C6/C7，已就绪，证据链最强） | ~64-128 E | paired 选拔胜 + 确认池复测过 | 代码载体同样败 → skill 层降级为手写库 |
| 2 | MVP-M1（memory triggered injection A/B） | ~12-16 ep | 分数不劣 + 税 <15%（或显著优 + 税 <40%） | 税 >40% 无收益 → memory 只喂变异 |
| 3 | 选拔统计升级（配对+确认门+行为门） | 协议改动，省 E | 协议评审 | — |
| 4 | MVP-H1（压缩策略进化，回归门先行） | ~8-12 ep | token 降 + paired 2σ 不劣 | 回归门不过 → harness 层冻结在 v0 |
| 5 | 迁移协议激活（随首次数据集迁移生效） | 迁移时计 | worst-group 不劣于旧域 retain 线 | — |

每层独立、可杀、失败不影响其他层；四层共享同一套选拔/晋升/预算/快照协议。

## 7. 不做清单

- 不同时进化多类资产（归因灾难）；
- 不做在线自改 wrapper 主文件（无回滚路径）；
- 不做 memory 常驻注入（token 税实证 + 污染风险）；
- 不做自由重写代码骨架（报错零分纪律与种子锚定偏置）；
- 单 lineage 未 plateau 前不做 MAP-Elites/population/选择器；
- 不做权重训练（接口已留，范围外）。

## 8. 关键参考（详见 research/nonparam_dim01~05.md 的完整引用）

- GEPA（arXiv 2507.19457，ICLR'26 oral）— 反思变异层
- PACE（arXiv 2606.08106）— 假 commit 率 30-42%，e-process 门
- GSME（arXiv 2607.13683）— 冻结 27B 两阶段选拔确认协议（同构模板）
- MemSkill / Memory-R1 / MemEvolve — 记忆条目与记忆策略可进化的直接先例
- SkillsBench — 自写 skill −1.3pp vs 精选 +16.2pp（验证环必要性）
- EvolveTool-Bench — 代码进化 0.603 vs 文本进化 0.520
- s1 budget forcing — 代码级预算强制 vs prompt 纪律（C2 同构）
- Meta-Harness / AHE / Self-Harness — wrapper 中间件进化的三个直接先例
- Harness 形式化（arXiv 2605.29682）— H=(E,T,C,S,L,V)
- LATM / Voyager / FunSearch / EoH / LLaMEA — 执行级验证与骨架+填充形态
- LiveBench — holdout 滚动轮换模式

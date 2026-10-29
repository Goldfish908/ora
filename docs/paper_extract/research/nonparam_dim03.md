# 非参数维度调研 · Dim-03：Agent Harness（脚手架）层自进化 —— 机制全景与可复用设计

- 调研日期：2026-08-29
- 调研人：技术调研员（子代理）
- 检索规模：25 次独立搜索查询（中英混合，术语用英文）+ 4 篇原文精读（arXiv abs/HTML）
- 背景系统锚点：推理+验证 solver，冻结 Qwen 27B，CO-Bench/JSSP 评测；`driver/`（episode 循环、tool 分发）与 `mcp_server/`（evaluator、预算权威 E=16）为冻结红线；可进化面为 **llm_fn wrapper 缝**（当前承载 `_sanitize_history` / `_compact_history` / reasoning_effort 注入）；已有结论 H0 不存在、H1/H2 冻结。

---

## 0. 执行摘要（TL;DR）

1. **Harness 已是 2026 年公认的一等设计对象**：多篇综述（arXiv:2606.20683、2605.29682、2605.18747）将 harness 形式化为模型之外的执行层，并提出 4 大演化范式（prompt engineering → workflows → context engineering → **harness engineering / 协同进化**）[^1^][^2^][^4^]。背景系统的"wrapper 缝进化"恰好落在 harness 六元组 H=(E,T,C,S,L,V) 中的 **C（Context Manager）+ L（Lifecycle Hooks）**，而 E/T/S/V 冻结 —— 与文献推荐的"冻结运行契约、开放控制面"结构完全一致[^2^]。
2. **上下文管理策略可进化有强先例**：四大主流 coding harness（Pi、OpenClaw、Claude Code、Letta）独立收敛到同一套 context 管理 playbook（file-read 上限、token 阈值触发 LLM compaction、subagent 隔离、tool 结果落盘）[^6^]；IDP AutoOpt 实验证明 **compaction 触发阈值本身就是可优化超参**（30–60% 实用区间，10% 会烧光时间预算）[^9^]；Meta-Harness 直接把"决定存什么、取什么、呈现什么"的 harness 代码当搜索对象，4× 更少 context token 反而 +7.7 分[^12^]。
3. **wrapper/中间件自进化先例成熟且安全性设计可直接抄**：AHE（arXiv:2604.25850）把 middleware 等 7 类组件暴露为文件、git commit 级回滚、每次编辑绑定"可证伪预测"，10 轮进化超人类设计 harness[^13^]；Self-Harness（2606.09498）用"弱点挖掘→最小提案→**回归测试门禁**"三阶段，9/9 模型×基准组合 held-in/held-out 双提升，且进化出的正是 **retry discipline、tool-error-triggered middleware** 这类 wrapper 级机制[^14^]。DGM 给出安全基线：沙箱 + 时限 + 限定修改域 + archive 谱系审计[^15^]。
4. **预算分配策略可进化且可在 wrapper 层无训练实现**：s1 budget forcing（解码时截断/追加 "Wait"）[^20^]、BudgetThinker 的周期控制 token 注入[^21^]、TALE 的 prompt 内预算估计[^22^] 都是"注入/截断型"机制，天然适配 llm_fn wrapper；EvoHarness-RL 用 cost-aware RL 学到"选择性、成本感知"的 harness 调用[^23^]；TokenOps 给出 run 级逐调用"读花费→决策→记账"的预算权威模式[^25^]——但注意背景系统的预算权威（E=16）在 mcp_server 冻结，wrapper 只能进化**预算的分配与呈现策略**，不能进化预算本身。
5. **公平性方法论已有明确范式**：Kapoor《AI Agents That Matter》的成本-精度联合 Pareto[^26^]、HAL 的 21,730 rollouts 大规模证据（"更高 reasoning 预算在 21/36 设置中反而降低精度"）[^27^]、RoboPhD 的"同信息/同种子/同预算（1,500 evals）"比较协议[^24^]、HarnessForge 的 budgeted Pareto 半选[^18^]、《Harness Updating ≠ Benefit》的 in-situ 协议与"tools/ 和评测文件只读"权限块[^28^]。核心结论：**跨代公平靠"预算守恒 + 评测面冻结 + 同预算头对头比较"**，背景系统 E=16 冻结恰是天然的 budget conservation 锚点。

---

## 1. 维度一：「LLM harness」概念界定与分层

### 1.1 Harness 的正式定义与六元组模型
- **名称**：Agent Harness 形式化 H=(E,T,C,S,L,V)
- **来源**：Meng et al., *Agent Harness for Large Language Model Agents: A Survey*, arXiv:2605.29682（2026-04-28，preprints.org 同步）[^2^]
- **核心机制**：首个系统性 harness 综述，将 harness 定义为六元组：**E**xecution Loop（观察-思考-行动循环、终止、错误恢复）、**T**ool Registry、**C**ontext Manager（上下文窗口管理、**compaction**、检索）、**S**tate Store、**L**ifecycle Hooks（授权、日志、策略执行、插桩）、**V**alidation/Evaluation Interface；并赋予 labeled-transition-system 语义，区分 safety 性质（不变式）与 liveness 性质（最终进展）[^2^][^3^]。
- **证据强度**：强（110+ 论文、23 个系统、Harness Completeness Matrix、HF 数据集）。
- **可复用性**：高 —— 直接给出"什么可进化/什么必须冻结"的分类语言：LTS 的 safety 不变式 ↔ 冻结红线；C/L 组件 ↔ 可进化控制面。
- **对背景系统适用判断**：**高度适用**。背景系统的 wrapper 缝精确对应 C（compaction/截断/注入）与 L 的子集（策略执行）；driver/ 对应 E+T，mcp_server/ 对应 V+预算权威（L 的 enforcement 部分）。综述将"reliability 由 harness 而非模型决定"立为中心命题（"tool format optimization alone moved SWE-bench performance from 6.7% to 68.3%"）[^3^]，为"冻结 Qwen 27B 而进化 harness"提供直接理论背书。

### 1.2 Model–Harness 透镜与四范式演化线
- **名称**：A Survey on Agent System and Harness Design
- **来源**：arXiv:2606.20683（2026-06-14）[^1^]
- **核心机制**：以 model–harness 透镜分解 agent，追踪四大工程范式："from prompt engineering to workflows and context engineering, harness engineering, and agent-native training with co-evolution"；把 harness 分解为六项耦合运行时职责（observation、context、control、action、state、verification/governance），并指出开放挑战包括 "value-aware evaluation, safety, harness generalization, and model–harness co-evolution"[^1^]。
- **证据强度**：强（综述，arXiv 权威 S）。
- **可复用性**：中高 —— 提供"范式定位"话术：背景系统已完成 prompt patch 进化（范式 1-2），wrapper 缝进化即跨入范式 3（harness engineering），且明确避免范式 4（co-evolution 需动模型，不可行）。
- **适用判断**：适用。其"context"职责即 wrapper 的 `_compact_history/_sanitize_history`；"control"职责即注入与重试策略。

### 1.3 产业界定与栈分层
- **名称**：Harness 工程产业共识（LangChain / Builder.io / winder.ai 四层栈）
- **来源**：LangChain "Anatomy of an Agent Harness"（2026-03-10，经二手转述）、Builder.io 定义（2026）、winder.ai 比较文（2026-08-20）[^5^]
- **核心机制**：LangChain 简式定义 "an agent is a **model plus a harness**"；Builder.io 定义为"every piece of code, configuration, and execution logic that wraps an AI model"；winder.ai 将栈分四层：**model（推理）→ harness（跑一个 agent）→ framework（编排多个）→ platform（多团队 durable execution、成本归因、治理）**[^5^]。
- **证据强度**：中（产业博客，但与学术综述互证）。
- **可复用性**：中 —— 用于对外沟通与文档措辞。
- **适用判断**：背景系统的 driver+mcp_server+wrapper 合起来正是"harness"，冻结红线即"harness 内部再分 frozen kernel vs evolvable control plane"，与 platform playbook 的"bounded, attributable, verifiable, reversible"五原语一致[^5^]。

### 1.4 相关综述补充（证据归档）
- *Code as Agent Harness*（arXiv:2605.18747, 2026-05-18）：把 code 本身作为 harness 的操作基底，三层组织（interface / mechanisms / scaling）[^4^]。对"wrapper 是代码、因此可被 agent 当代码进化"提供框架支撑。
- *Externalization in LLM Agents*（arXiv:2604.08224, 2026-04）：**Weights → Context → Harness** 叠层框架，论证能力重心从权重外移到 harness[^4^]。背景系统"冻结权重 + 进化 wrapper"正是该外移路径的实践。

---

## 2. 维度二：上下文管理策略的可进化性

### 2.1 主流 harness 的 context 管理收敛 playbook（进化搜索空间的先验）
- **名称**：Context management convergence study（Pi / OpenClaw / Claude Code / Letta）
- **来源**：Arize 工程博客（2026-08-12）[^6^]
- **核心机制**：四大 harness 独立收敛到同一套设计："All four harnesses hard-cap file reads… cap tool result sizes… isolate sub-agent sessions… run **LLM-powered compaction triggered by a token threshold**… estimate context usage and detect pressure"；具体技巧包括 head-truncate + continuation nudge、超大 tool 结果落盘留路径、compaction 时保护 tool-call/result 边界、compaction 后按预算重挂最近文件、prompt-too-long 时确定性 head-drop 兜底[^6^]。
- **证据强度**：中强（一线代码考古，四个生产代码库逐一核对；非同行评议）。
- **可复用性**：**极高** —— 这就是 wrapper 缝进化的初始候选动作集：每个收敛技巧都可参数化为 wrapper 策略的一个维度（触发阈值、保留比例、落盘开关、重挂预算、兜底规则）。
- **适用判断**：直接适用。`_compact_history` 的进化方向应覆盖：触发阈值、9-section 式结构化摘要 prompt、scratchpad 剥离、post-compact 文件重挂、head-drop 兜底——全部是 wrapper 内可实现、不碰 driver 的改动。

### 2.2 工业级双层 compaction 设计
- **名称**：Glean harness compaction（conversation + tool-output 双层）
- **来源**：Glean 官方博客（2026-04-29）[^7^]
- **核心机制**：conversation compaction 保留 "user intent, decisions made so far, approaches that failed, planned next steps, and recent high-signal tool outputs"；tool-output compaction 将大输出写入沙箱文件系统、只留摘要+路径；sub-agent 作为 context 隔离边界，各自有独立 context window 与 **token budget**[^7^]。
- **证据强度**：中（厂商博客，但有 ~5% 查询撞窗口的真实数据）。
- **可复用性**：高 —— "保留什么"的语义清单可直接写进可进化的 compaction prompt 模板。
- **适用判断**：适用。CO-Bench/JSSP 长 episode 中"失败的验证反馈"属于 must-keep 类；tool-output 落盘需 driver 配合，若 driver 冻结则 wrapper 只能用"截断+引用"的弱化版。

### 2.3 Compaction 的成本-收益理论化
- **名称**：Context Compaction Theory
- **来源**：arXiv:2608.01326（2026-08-02）[^8^]
- **核心机制**：指出约束在 LLM 输入窗口 W 而非 agent 记忆（agent 可存全量 transcript）；LLM-based summarization 每次 compaction 本身有显著成本（示例：800K tokens 历史压成 100K 摘要，单次 $13），因此"何时压、压多少"是真正的优化变量而非免费操作[^8^]。
- **证据强度**：中（理论+算例，预印本）。
- **可复用性**：高 —— 为"compaction 策略进化"提供目标函数：压缩收益 vs 压缩调用成本 vs 信息损失风险。
- **适用判断**：适用。冻结 Qwen 27B 自托管时成本主要体现为延迟/显存占用与 E 预算消耗，理论框架同样成立：compaction 调用若计入 episode 预算，则进化目标应包含 compaction 频率惩罚。

### 2.4 把 compaction 阈值当可优化超参的直接先例
- **名称**：IDP AutoOpt 的 context 管理阈值研究
- **来源**：arXiv:2607.26075v2, Appendix B（2026-08-22）[^9^]
- **核心机制**：每次模型调用前 hook 检查 token 占用是否超阈值（窗口百分比）；超则 (1) 旁路 LLM 摘要旧历史为结构化要点 (2) 保留最近消息 (3) 重注入完整优化日志。阈值实证：**50% 约每 18 次迭代压一次且精度损失最小；10% 每次迭代压 ~5 次、"consuming the time budget on summarization"、半数迭代超时；30–60% 为实用区间**[^9^]。
- **证据强度**：中强（单系统但有受控阈值扫描）。
- **可复用性**：**极高** —— 这是"把 compaction/注入策略当可优化对象"的最直接证据：阈值是连续超参，可用进化/BO 搜索；副作用模式（过频压缩烧预算）也给出了进化时需要监控的护栏指标。
- **适用判断**：直接适用于 `_compact_history` 触发策略的进化；注意背景系统的"时间预算"对应 E=16 步数，过频 compaction 会间接浪费步数。

### 2.5 把"存什么/取什么/呈现什么"当搜索对象：Meta-Harness
- **名称**：Meta-Harness: End-to-End Optimization of Model Harnesses
- **来源**：arXiv:2603.28052（2026-03-30）[^12^]
- **核心机制**：定义 harness 为 "the code that determines what information to store, retrieve, and present to the model"；外循环系统用 agentic proposer（可经文件系统访问全部历史候选的源码、分数、执行轨迹）**搜索 harness 代码本身**；在线文本分类上比 SOTA context 管理系统 +7.7 分且 **context token 少 4×**；IMO 级数学 +4.7 分（5 个 held-out 模型平均）；TerminalBench-2 超最佳手工 harness[^12^]。
- **证据强度**：强（Stanford 团队、三域验证、held-out 模型泛化）。
- **可复用性**：高 —— 证明了"context 管理代码（而非 prompt 文本）可作为进化对象"，且"更少 token + 更高分"的 Pareto 改进存在。
- **适用判断**：高度适用。背景系统的 wrapper 正是 Python 代码；Meta-Harness 的 proposer-via-filesystem 模式可改造为：evolver agent 读写 wrapper 策略模块（而非冻结的 driver/），每次候选在 CO-Bench/JSSP held-in 集上评估。

### 2.6 经验驱动的自适应 harness：MemoHarness
- **名称**：MemoHarness: Agent Harnesses That Learn from Experience
- **来源**：arXiv:2607.14159（2026-07-14）[^10^]
- **核心机制**：把 harness 沿推理时序分解为**六个可编辑控制维度（context、tool、generation、orchestration、memory、output）**；双层经验库（per-case 诊断 + 蒸馏全局模式）；测试时检索相似 case 把全局 harness W* 适配为 case 级 W(x_j)，无需测试时标签；**correctness-first 排序，执行成本仅作平局裁决**，防止搜索漂向"便宜但错"的配置[^10^]。
- **证据强度**：中强（三域基准，0.806 vs 0.722 固定 harness 基线；作者自承统计稳健性待证）。
- **可复用性**：高 —— 六维分解可直接用作 wrapper 进化的**基因空间定义**；"correctness-first + cost-tiebreak"是可照抄的选择算子，与背景系统的预算守恒约束天然兼容。
- **适用判断**：适用。case 级适配（按 JSSP 实例规模检索历史经验调整注入/压缩强度）是 prompt patch 之外的增量维度。

### 2.7 上下文/prompt 级进化的邻近证据
- **ACE（Agentic Context Engineering, arXiv:2510.04618）** 与 **GEPA（arXiv:2507.19457）**：把 context/playbook/prompt 当可进化对象；在 AHE 对照实验中作为"prompt-only 自进化"基线，**输给开放整个脚手架编辑的 AHE**——"The harness components ACE and TF-GRPO never edit are exactly where the gain lives"（AHE 的 tools/middleware/long-term memory 单独换入即 +3.3/+2.2/+5.6pp，而 system prompt 单独 −2.3pp）[^11^]。
- **适用判断**：对背景系统是**关键警示**：已完成 prompt patch 进化后，继续只在 prompt 面进化可能收益见顶甚至为负；增量收益在 wrapper 的中间件/记忆/工具结果处理层。

---

## 3. 维度三：wrapper/中间件层进化的先例与安全性

### 3.1 AHE：可观测性驱动的 harness 自动进化（最直接对标）
- **名称**：Agentic Harness Engineering (AHE) / NexAU substrate
- **来源**：arXiv:2604.25850（2026-04-28，v4 2026-05-18；Fudan+PKU；代码开源）[^11^][^13^]
- **核心机制**：harness 基座把 **7 类正交组件（system prompt、tool description、tool implementation、middleware、skill、sub-agent 配置、长期记忆）暴露为固定挂载点的文件**；组件松耦合（"adding a middleware does not require editing the system prompt"）；每次逻辑编辑 = 一次 git commit（"file-level diffs and rollback granularity for free"）；三支柱可观测性：组件可观测（动作空间显式可回滚）、经验可观测（百万 token 轨迹蒸馏成分层证据库）、决策可观测（**每次编辑绑定自我声明的预测，下一轮验证 —— 把编辑变成可证伪契约**）。10 轮迭代 Terminal-Bench 2 pass@1 从 69.7%→77.0%，超人类设计的 Codex-CLI（71.9%）；冻结后的 harness 零重进化迁移到 SWE-bench-verified 且 token 少 12%，跨 3 个模型族 +5.1~+10.1pp[^11^]。
- **证据强度**：**强**（有人类 harness 与 ACE/TF-GRPO 双基线、消融定位到组件级、跨基准跨模型迁移）。
- **可复用性**：**极高** —— 组件文件化 + git 回滚 + 可证伪预测三件套可直接移植；"从极简种子起步以保归因干净"也是可复用方法论。
- **适用判断**：**最贴背景系统的先例**。映射：wrapper 的 sanitize/compact/inject 各为一个"middleware 组件文件"；冻结 driver/mcp_server = AHE 的固定执行循环与评测器；CO-Bench/JSSP 的 held-out split 充当下轮验证集。AHE 证明 middleware 层（恰是 wrapper 缝）的进化收益是真实且可迁移的。

### 3.2 Self-Harness：无外部强模型的自进化 + 回归测试门禁
- **名称**：Self-Harness: Harnesses That Improve Themselves
- **来源**：arXiv:2606.09498（2026-06-08，v3 2026-08-20）[^14^]
- **核心机制**：三阶段迭代环 —— **Weakness Mining**（从执行轨迹识别模型特有失败模式）→ **Harness Proposal**（生成多样但最小的修改）→ **Proposal Validation**（候选编辑**仅在通过回归测试后接受**）。9/9 模型×基准组合 held-in 与 held-out 双提升，整体相对增益最高 132%。进化保留的编辑恰恰是 wrapper 级机制：Qwen3.5 案例 "emphasize artifact checking, missing-artifact recovery, **retry discipline**, and **tool-error-triggered middleware**"；GLM-5 案例 "session-scoped tools"（让环境变更跨 shell 命令持久）与"从过长探索转向实现"的推进策略[^14^]。
- **证据强度**：强（三基准三模型族全组合、held-out 验证）。
- **可复用性**：**极高** —— "回归测试门禁"是最朴素有效的安全接受准则；"最小修改"约束降低突变风险；证明了**不需要更强的外部 evolver**（可用自身或同级模型），适合只有 Qwen 27B 可用的场景。
- **适用判断**：直接适用。背景系统已有验证 solver，回归测试基础设施现成；retry discipline 与 tool-error-triggered middleware 正是 llm_fn wrapper 可承载的进化对象。

### 3.3 Live-SWE-agent：运行时不改循环的自造工具
- **名称**：Live-SWE-agent: Can Software Engineering Agents Self-Evolve on the Fly?
- **来源**：arXiv:2511.13646（2025-11-17，v3 2025-11-24）[^15^]
- **核心机制**：从仅 bash 的极简 scaffold 出发，在解题循环中**合成/修改/执行自定义工具**（编辑器、代码搜索、领域分析器）；两处轻改动：初始 prompt 加工具创建指令与示例 + 每步环境反馈后追加 step-reflection（问"造/改工具能否加速"）；"leaves the underlying scaffold unchanged, requires no offline training, and is agnostic to the underlying LLM"；SWE-bench Verified 77.4%（无 test-time scaling）。消融：无工具创建 62.0% → 仅 prompt 提示 64.0% → prompt+反思 76.0%，证明反思机制必要[^15^]。
- **证据强度**：强（SOTA 级结果 + 干净消融）。
- **可复用性**：中高 —— "在冻结循环上只加 prompt 级钩子与反思"的介入方式最轻；step-reflection 是 wrapper 可注入的消息。
- **适用判断**：部分适用。背景系统的 tool 分发在冻结 driver/，**自造工具不能进 tool registry**；但"wrapper 注入反思消息""工具错误触发的 wrapper 行为"仍可借鉴。另一启示：弱模型（GPT-5-Nano）用不好自进化——27B 模型需谨慎设定进化粒度[^15^]。

### 3.4 DGM：自修改 scaffold 的安全基线
- **名称**：Darwin Gödel Machine
- **来源**：arXiv:2505.22954（2025-05；v3 2026-03-12）[^16^]
- **核心机制**：开放式进化自我改进的 coding agent（改自己的 Python 代码库）。安全设计四件套（可直接抄）：(1) "All agent execution and self-modification processes are conducted within **isolated sandboxed environments**"；(2) "Each execution within the sandbox is subjected to a **strict time limit**"；(3) "self-improvement process is currently **confined to the well-defined domain**…modifying the agent's own Python codebase, thus limiting the scope of potential modifications"；(4) "the DGM archive providing a **traceable lineage of modifications** for review"[^16^]。
- **证据强度**：强（被广泛引用的标杆系统）。
- **可复用性**：高（安全设计部分）；其离线进化成本（Live-SWE-agent 估 DGM 单次 ~$22K）是反面教材[^15^]。
- **适用判断**：安全基线直接适用 —— 背景系统的"wrapper 缝"本身就是比 DGM 更强的 scope confinement（只准改一个缝而非整个代码库）；archive 谱系对应 prompt patch 跨代进化的既有存档机制，应扩展到 harness patch。

### 3.5 在线无重置进化：Continual Harness
- **名称**：Continual Harness: Online Adaptation for Self-Improving Foundation Agents
- **来源**：arXiv:2605.09998（2026-05-11）[^17^]
- **核心机制**：具身长程任务中 agent 在**单次 run 内**交替"行动↔精炼自己的 prompt、sub-agents、skills、memory"，无需 episode reset（对比 prompt 优化方法必须重置）；从裸环境接口起步，button-press 成本显著低于极简基线并收复大部分到手工专家 harness 的差距[^17^]。
- **证据强度**：中强（Pokemon 全通关级实证，但领域特殊）。
- **可复用性**：中 —— "在线、无重置、episode 内进化"对 CO-Bench/JSSP 的 per-episode 进化（而非仅跨代进化）有启发。
- **适用判断**：部分适用。背景系统的跨代进化已是主循环；episode 内在线进化 wrapper（如按当前 instance 动态调整压缩阈值）是可选增量，但会引入 episode 内非平稳性，需谨慎处理公平性（见 §5）。

### 3.6 邻近参考
- **HarnessForge**（arXiv:2606.01779, 2026-06-01）：把 agent 系统形式化为 **harness–policy 对**，harness 侧 fault-guided tailoring（故障归因→archive 引导改进→候选生成→**budgeted Pareto 选择**），policy 侧训练 harness-conditioned LoRA；meta-agent 实现为"带固定输入输出契约的分阶段算子"、产出 schema 控制的可审计工件[^18^]。背景系统模型冻结 → policy 侧不可用，但 **harness 侧的故障引导剪裁流程与 budgeted Pareto 选择完全可复用**。
- **Runtime Harness Adaptation**（arXiv:2605.22166, 2026-05）："Adapting the Interface, Not the Model" —— 运行时适配 prompt 格式、动作校验、反馈解释、轨迹控制，专为冻结模型+规则域设计[^4^]。与 CO-Bench/JSSP（规则明确的调度/优化域）匹配度高。
- **未查到**：专门以"self-modifying middleware retry policy"为题的独立论文；该能力散落在 AHE（middleware 组件）与 Self-Harness（retry discipline 进化产物）中作为子机制出现。

---

## 4. 维度四：预算/资源分配策略的进化

### 4.1 解码时预算强制的 wrapper 实现：s1 Budget Forcing
- **名称**：s1: Simple test-time scaling — budget forcing
- **来源**：arXiv:2501.19393（2025-01-31，EMNLP 2025）[^20^]
- **核心机制**："forcing a maximum and/or minimum number of thinking tokens"：上限=直接追加 end-of-thinking 分隔符提前退出；下限=抑制结束符并追加 "Wait" 促使自我复核，"often fixing incorrect reasoning steps"；AIME24 从 50%→57%（budget forcing 外推）[^20^]。
- **证据强度**：强（EMNLP、广泛复现）。
- **可复用性**：**极高（工程上）** —— 纯解码时介入，是 wrapper/代理层的天然能力，零训练。
- **适用判断**：高度适用。背景系统的 reasoning_effort 注入已是同类机制；可进化为：**自适应 budget forcing**（按 instance 难度/剩余 E 步数决定 "Wait" 追加次数或截断点），策略参数（何时逼停、何时追加）作为可进化资产。注意 BARD 等工作指出朴素截断弱于学习型预算管理[^20^]——冻结模型下 wrapper 级 budget forcing 是可行的次优解。

### 4.2 周期注入剩余预算信号：BudgetThinker 模式
- **名称**：BudgetThinker: Empowering Budget-Aware LLM Reasoning with Control Tokens
- **来源**：arXiv:2508.17196（2025-08-24）[^21^]
- **核心机制**：推理中**周期性插入控制 token 持续告知剩余 token 预算**（"merely stating a budget constraint in the initial prompt is insufficient"）；SFT+课程 RL 训练预算依从；**Budget Ratio（按比例通知剩余量）优于固定间隔**；平均精度 +4.9% 且预算依从更精确[^21^]。
- **证据强度**：中强（多基准，但收益依赖训练）。
- **可复用性**：高（注入模式本身）——"按比例的剩余预算提示"是 wrapper 可直接注入的；无训练时依从性弱（TALE 的 token elasticity 现象[^22^]），但方向正确。
- **适用判断**：适用。背景系统的 E=16 步数预算可在 wrapper 注入"已用 e/E"信号（类似 Budget Ratio），注入模板作为可进化资产。这是"预算分配策略进化"在冻结模型约束下的最现实形态：**不进化预算值（mcp_server 冻结），进化预算的呈现节奏与格式**。

### 4.3 Prompt 内预算估计与 token elasticity：TALE
- **名称**：TALE: Token-Budget-Aware LLM Reasoning
- **来源**：arXiv:2412.18547（2024-12，v4 2025-02-17）[^22^]
- **核心机制**：TALE-EP 用 zero-shot 估计每题合理 token 预算并写入 prompt；平均 **token −67%、精度损失 <3%**；关键发现 **token elasticity**：预算收得太紧时模型会超支，"prompting alone is insufficient for strict enforcement"[^22^]。
- **证据强度**：中强（多模型多基准）。
- **可复用性**：高 —— "先估预算再注入"的两段式是 wrapper 可承载的策略；token elasticity 是进化时必须内置的护栏认知（软预算需配合硬截断）。
- **适用判断**：适用。对 CO-Bench/JSSP：可按 instance 规模（job 数/机器数）先验估计推理预算档位，档位映射表可进化。

### 4.4 RL 学出的成本感知 harness 使用：EvoHarness-RL
- **名称**：EvoHarness-RL: Learning Self-Evolving Runtime Harness for Long-Horizon LLM Agents
- **来源**：arXiv:2608.05446（2026-08-05，UIUC+Meta）[^23^]
- **核心机制**：把外部工作区结构化为 **Belief/Progress/Experience (BPE)** 状态并定义 harness 元动作（读/更新/合并）；SFT 启动 + **cost-aware GRPO** 优化选择性使用；出现 **harness annealing**："usage drops quickly and stabilizes near one call per episode…GRPO gradually internalizes routine scaffolded behaviors into the policy, while preserving harness access only when the expected benefit outweighs its step cost"；Qwen3-8B 在 ALFWorld 96.9%[^23^]。
- **证据强度**：强（Meta 背书、两阶段训练消融）。
- **可复用性**：中 —— 需要训练，背景系统冻结模型不可直接复用；但"**harness 调用有 step cost，应选择性使用**"的原则与"经验合并压缩工作区"的 harness 侧进化方向可借鉴。
- **适用判断**：原则适用、方法不适用（需 GRPO）。间接证据：E=16 预算下，wrapper 的每次注入/压缩都消耗上下文与步数，进化目标应含成本项——与 MemoHarness 的 correctness-first/cost-tiebreak 一致[^10^]。

### 4.5 预算感知的工具/行为选择与 run 级预算权威
- **BATS（Budget-Aware Tool Selection）**："simply granting larger tool-call budgets fails to improve agent performance; …explicit budget awareness enables effective scaling"（经二手综述转述，arXiv:2601.08815 §3.2）[^19^]。含义：**把预算做成 agent 可见的一等信号**比单纯放大预算有效 —— 支持 wrapper 注入预算呈现策略的进化方向。
- **TokenOps（Microsoft，2026-08-13）**：run-scoped 实时成本控制："each call: **read the run's spend, apply the decision, dispatch, then record the true cost**" —— 逐调用的"读账→决策→派发→记账"循环[^25^]。这正是背景系统 wrapper 与 mcp_server 预算权威的分工模板：**mcp_server 记账与裁决（冻结），wrapper 进化"apply the decision"的策略**（降级 reasoning_effort、提前压缩、截断输出等）。
- **适用判断**：两者合并给出背景系统预算进化的合法边界：预算权威不动，**预算驱动行为的策略面**（何时降级、何时压缩、如何呈现剩余预算）全部可进化。

### 4.6 评估预算本身的分配进化：RoboPhD
- **名称**：RoboPhD: Evolving Diverse Complex Agents Under Tight Evaluation Budgets
- **来源**：arXiv:2604.04347（2026-04-06；GitHub 开源 MIT）[^24^]
- **核心机制**：三种进化范式的首次系统头对头（Elo 锦标赛 vs GEPA Pareto vs Autoresearch 爬山），**固定 1,500 次评估预算**；提出 **validation-free evolution**：不划分训练/验证预算，Elo 竞争同时充当评估与进化信号（"every evaluation spent on validation is thus 'dead' from evolution's perspective"）；4 基准中 3 个胜出；ARC-AGI 22 行种子→1,013 行 agent（27.8%→65.8%）[^24^]。
- **证据强度**：中强（受控同预算比较 + 开源可复现；独立研究者）。
- **可复用性**：高 —— "评估预算是进化的一级约束，其内部分配（探索 vs 验证）本身可被优化"是方法论级启示；小验证集在同预算下一致更优的发现可直接指导背景系统 held-in 评估的规模配置。
- **适用判断**：适用于背景系统的**进化外层**（harness patch 候选的评估调度），而非 episode 内。与 §5 的公平性协议互补。

---

## 5. 维度五：公平性约束下的 harness 进化（budget conservation 方法论）

### 5.1 成本-精度联合评估的奠基文献
- **名称**：AI Agents That Matter
- **来源**：Kapoor, Stroebl, Siegel, Nadgir, Narayanan, arXiv:2407.01502（2024-07）[^26^]
- **核心机制**：指出 agent 评测两大病灶：只看精度不看成本、held-out 与开发集混用导致过拟合；方法上要求**联合优化精度与成本并报告 Pareto 前沿**（HumanEval 上简单 baseline 以 ~2% 成本追平 LATS）；要求固定总预算下的受控比较[^26^]。
- **证据强度**：强（NeurIPS 脉络、被 HAL 等后续直接继承）。
- **可复用性**：**极高** —— "harness 变了但比较仍要公平"的标准答案不是冻结 harness，而是**把成本/预算纳入比较维度、报告 Pareto 点而非单点精度**。
- **适用判断**：直接适用。背景系统的 E=16 是天然的成本固定锚；跨代比较应报告 (E 消耗, CO-Bench/JSSP 分数) 的联合指标；任何 harness patch 若改变实际 token/步数消耗，须在报告中显性化。

### 5.2 大规模实证：更高预算常常不更优（HAL）
- **名称**：Holistic Agent Leaderboard (HAL)
- **来源**：arXiv:2510.11977（2025-10，经 agentpatterns 二手转述其数字）[^27^]
- **核心机制**：21,730 次 agent rollout、9 模型 × 9 基准、$40K 花费的联合成本/质量 Pareto 扫描；关键发现：**"increased reasoning-token budget reduced accuracy in 21 of 36 model × benchmark settings"**；最贵模型很少 Pareto 最优[^27^]。
- **证据强度**：强（大样本）。
- **可复用性**：高 —— 直接支持背景系统的 E=16 硬预算设计：预算不是越大越好，因此**预算分配策略（而非预算量）才是可进化资产**；也为"reasoning_effort 注入进化"提供护栏——effort 升档可能降分。
- **适用判断**：直接适用。wrapper 进化 reasoning_effort 注入策略时，须按 Pareto 而非精度单指标接受 patch。

### 5.3 同预算/同种子/同信息的三同协议：RoboPhD 比较范式
- **来源**：arXiv:2604.04347[^24^]
- **核心机制**："given the **same information, the same seed agent, and the same objective**, which optimization algorithm yields the best results **under the same evaluation budget**?"；三系统共用评估基础设施、测试集、逐题诊断[^24^]。
- **可复用性**：高 —— 这就是"harness 变了比较仍公平"的操作化协议：**冻结种子、冻结评测面、冻结评估预算，让 harness 成为唯一变量**。
- **适用判断**：直接适用于背景系统的跨代比较设计：每代 harness patch 在同一 CO-Bench/JSSP split、同一 E=16、同一随机种子集上评估；与 HGM 的"对所有方法一致应用 budget-friendly 修改以保公平"同构[^29^]。

### 5.4 权限块与 in-situ 协议：Harness Updating ≠ Benefit
- **名称**：Harness Updating Is Not Harness Benefit: Disentangling Evolution Capabilities in Self-Evolving LLM Agents
- **来源**：arXiv:2605.30621（2026-05-28，UCSC+Amazon+PSU 等）[^28^]
- **核心机制**：(a) 解耦两种能力——harness-updating（产出有用更新）与 harness-benefit（从更新受益）；(b) 发现 updating 能力对模型规模**平坦**（Qwen3.5-9B 的更新收益可比肩 Claude Opus 4.6），benefit **非单调**（中档模型受益最多；弱模型因 activation failure 与 adherence failure 受益最少）；(c) 公平协议细节："**The tools/ directory and evaluation files are read-only for all benchmarks**"，权限块逐周期传给 evolver；in-situ 评估：每个任务在 H_{t−1} 下计分后其证据才用于产生 H_t[^28^]。
- **证据强度**：强（7 模型 × 3 基准全配对矩阵）。
- **可复用性**：**极高** —— 权限块 + 只读评测面 + in-situ 计分是可逐字照抄的公平性协议。
- **适用判断**：直接适用，且含两条对背景系统的**特化警示**：(1) 27B 处于"中档受益区"附近，harness 进化预期有正收益，但须监控 harness adherence（注入的策略指令是否被 27B 忠实遵循，弱模型会随轨迹漂移：Qwen3-32B 的遵循度从加载时 0.52 漂到末轮 0.13）；(2) evolver 不必更强 —— 用 Qwen 27B 自己做 evolver 是文献支持的合理选择。

### 5.5 谱系级度量与预算一致性：HGM
- **名称**：Huxley-Gödel Machine
- **来源**：arXiv:2510.21614（2025-10-24）[^29^]
- **核心机制**：指出 Metaproductivity-Performance Mismatch（当下跑分 ≠ 未来自我改进潜力）；提出 **CMP（Clade-Metaproductivity）**：聚合后代谱系表现作为节点选择准则；公平比较做法：所有方法"start with the **same initial ancestor**"、统一"**maximum allowance of 800 benchmark task evaluations**"、对 HGM 与全部基线一致应用相同的 cost-efficient backbone 替换[^29^]。
- **证据强度**：强（SWE-bench Verified/Polyglot 上超 DGM/SICA 且 CPU 时更少）。
- **可复用性**：中高 —— CMP 思路适用于背景系统的跨代进化：**选择用于扩展的 harness patch 时，看其后代谱系表现而非单代跑分**，避免 greedy 选择陷阱；"统一评估配额 + 同一祖先"是可直接套用的公平条款。
- **适用判断**：适用。背景系统的 prompt patch 谱系已有 archive，CMP 可扩展到 harness patch 谱系选择。

### 5.6 同预算候选筛选与归因隔离（工程条款）
- **HarnessForge budgeted half-selection**：候选 harness 在"**Under the same rollout budget**"下分级过滤（每级 200 任务），Pareto 排序保上半；policy 训练复用已收集 rollout，"does not require a new environment-interaction phase"以保预算[^18^]。
- **AHE 归因隔离**："All three role agents share one base model, isolating the gain to harness edits"；从**极简种子**出发（"A seed already fitted to the target benchmark would contaminate every subsequent edit's attribution"）；k=2 rollouts/任务/迭代的固定评估开销[^11^]。
- **适用判断**：两者合并给出跨代公平的工程清单：同一基座（Qwen 27B 冻结天然满足）、同 rollout 预算筛选候选、种子/祖先一致性声明、编辑-收益归因到组件级（git diff 粒度）。

### 5.7 本维度未查到项
- 未查到以 **"budget conservation"** 为正式术语处理"进化中的跨代公平"的专门文献；该概念以上述"同评估预算 / Pareto 联合报告 / 只读评测面 / 权限块"等操作形式分散存在。背景系统将 E=16 预算权威冻结在 mcp_server，实质上是把 budget conservation **从协议约束升级为架构约束**——这一做法本身比现有文献的协议级方案更强，可作为论文卖点。

---

## 6. 机制-适用性总表

| # | 机制 | 来源 | 证据强度 | 对背景系统适用性 | 一句话结论 |
|---|------|------|---------|----------------|-----------|
| 1 | H=(E,T,C,S,L,V) 形式化 | arXiv:2605.29682 | 强 | 高（分层语言） | wrapper=C+L，冻结线=E/T/V+预算权威 |
| 2 | 四范式演化线 | arXiv:2606.20683 | 强 | 高 | wrapper 进化=范式3，避免范式4 |
| 3 | 收敛 context playbook | Arize 博客 2026-08 | 中强 | 极高 | wrapper 进化的初始动作集 |
| 4 | 双层 compaction | Glean 博客 2026-04 | 中 | 高 | must-keep 语义清单可照抄 |
| 5 | compaction 阈值优化 | arXiv:2607.26075 | 中强 | 极高 | 阈值是连续可进化超参，30–60% 实用 |
| 6 | harness 代码搜索 | Meta-Harness 2603.28052 | 强 | 极高 | context 管理代码可作进化对象 |
| 7 | 六维控制面+经验库 | MemoHarness 2607.14159 | 中强 | 高 | 基因空间定义+选择算子可抄 |
| 8 | 组件文件化+可证伪编辑 | AHE 2604.25850 | 强 | 极高 | 最直接对标；middleware 进化有真实收益 |
| 9 | 回归测试门禁自进化 | Self-Harness 2606.09498 | 强 | 极高 | 接受准则=回归测试；retry/middleware 是进化产物 |
| 10 | 运行时自造工具 | Live-SWE-agent 2511.13646 | 强 | 部分（tool registry 冻结） | 借鉴其反思注入与轻介入 |
| 11 | 沙箱+时限+域限定+谱系 | DGM 2505.22954 | 强 | 高（安全基线） | wrapper 缝本身是更强的 scope confinement |
| 12 | budget forcing | s1 2501.19393 | 强 | 极高 | 解码时介入，wrapper 零训练可实现 |
| 13 | 预算比例周期注入 | BudgetThinker 2508.17196 | 中强 | 高 | 注入"已用 e/E"模式可进化 |
| 14 | prompt 内预算估计 | TALE 2412.18547 | 中强 | 高 | 档位映射可进化；注意 token elasticity |
| 15 | 成本感知 harness 使用 | EvoHarness-RL 2608.05446 | 强 | 原则适用（方法需训练） | harness 调用有成本，进化目标含成本项 |
| 16 | run 级读账-决策-记账 | TokenOps 2026-08 | 中（厂商文档） | 高 | wrapper 进化"apply decision"策略面 |
| 17 | 成本-精度 Pareto | Kapoor 2407.01502 | 强 | 极高 | 公平性奠基：联合指标而非单点 |
| 18 | 大预算≠更优实证 | HAL 2510.11977 | 强 | 高 | 支持固定 E=16；effort 升档需 Pareto 验收 |
| 19 | 三同比较协议 | RoboPhD 2604.04347 | 中强 | 极高 | 同种子/同评测面/同预算，harness 为唯一变量 |
| 20 | 权限块+in-situ 计分 | Harness Updating≠Benefit 2605.30621 | 强 | 极高 | 公平协议可逐字照抄；27B 处受益区间 |
| 21 | 谱系级选择 CMP | HGM 2510.21614 | 强 | 中高 | 扩展选择看后代谱系而非单代分 |
| 22 | budgeted Pareto 半选 | HarnessForge 2606.01779 | 强 | 高 | 同预算分级筛选候选 patch |

---

## 7. 对背景系统的综合设计建议（调研推导，非事实）

1. **进化基因空间（wrapper 内）**：compaction 触发阈值（连续，参考 §2.4 的 30–60% 先验）、compaction 摘要模板（must-keep 清单，§2.2）、tool 结果截断/落盘开关（§2.1）、reasoning_effort 注入策略（含预算比例信号格式，§4.2/§4.3）、retry/修复策略（§3.2 证明可进化）、budget forcing 参数（§4.1）。用 MemoHarness 式六维表登记，每个维度一个可 git-diff 的文件（§3.1）。
2. **接受准则（安全门禁）**：Self-Harness 回归测试 + Kapoor Pareto 双指标 + HAL 警示（effort 升档可能降分）；每次编辑绑定可证伪预测，下轮在 held-out CO-Bench/JSSP split 验证（§3.1）；archive 谱系 + CMP 式选择（§5.5）。
3. **公平协议（冻结红线自然满足大部分）**：mcp_server 只读 + E=16 架构级 budget conservation（强于文献的协议级方案）；同祖先声明、同评估配额、in-situ 计分、权限块随进化周期下发（§5.4/§5.3）。
4. **风险预警**：(a) 27B 模型的 harness adherence 会随轨迹漂移（§5.4），注入策略宜"短指令+周期提醒"而非一次性长指令；(b) prompt-only 进化收益可能已见顶（§2.7），增量在 middleware/记忆/工具结果处理；(c) token elasticity：软预算必须配硬截断（§4.3）；(d) 过频 compaction 烧预算（§2.4），进化目标须含成本惩罚项。

---

## 参考与原文摘录

[^1^]: *A Survey on Agent System and Harness Design*, arXiv:2606.20683, 2026-06-14. https://arxiv.org/abs/2606.20683 — "As agent systems have evolved from prompt engineering to workflows and context engineering, harness engineering, and agent-native training with co-evolution…we decompose the execution harness into six coupled runtime responsibilities: observation, context, control, action, state, and verification/governance…open challenges in value-aware evaluation, safety, harness generalization, and model–harness co-evolution."

[^2^]: Meng et al., *Agent Harness for Large Language Model Agents: A Survey*, arXiv:2605.29682 / preprints.org 2026-04-28. https://www.preprints.org/manuscript/202604.0428 — "A formal definition of the agent harness as a six-component tuple H = (E,T,C,S,L,V), i.e., execution loop, tool registry, context manager, state store, lifecycle hooks, and evaluation interface…the reliability of LLM agents in production environments is increasingly determined not by the underlying model but by the agent harness that encapsulates it."

[^3^]: Agent Harness Engineering: Survey & Taxonomy（agentic-ai.readthedocs.io，综合 2605.29682 与 TMLR 投稿）. https://agentic-ai.readthedocs.io/en/latest/AgentHarness/llm-harness-survey/ — "Tool format optimization alone moved SWE-bench performance from 6.7% to 68.3% — more than any model upgrade in the same period." 及 H=(E,T,C,S,L,V) 各组件职责表（C: "Context window management, compaction, retrieval"；L: "Authorization, logging, policy enforcement, instrumentation"）。

[^4^]: *Code as Agent Harness*, arXiv:2605.18747, 2026-05-18, https://arxiv.org/abs/2605.18747；*Externalization in LLM Agents*, arXiv:2604.08224, 2026-04（"Weights → Context → Harness" 叠层）；*Adapting the Interface, Not the Model: Runtime Harness Adaptation*, arXiv:2605.22166, 2026-05（"adapt the harness interface at runtime — prompt formats, action validation, feedback interpretation, trajectory control"）。均经 https://atto.bot/labs/arxiv-agent-harnesses/ 转述核对。

[^5^]: winder.ai, *A Comparison of AI Agent Harnesses in 2026*, 2026-08-20. https://winder.ai/ai-agent-harness-comparison/ — "LangChain puts it more bluntly. A harness is every piece of code, configuration, and execution logic that isn't the model itself…the model, which reasons; the harness, which runs one agent; the framework, which composes several; the platform, which runs many harnesses across a team over time." 另见 puppyone.ai playbook（2026-06-25）："bounded, attributable, verifiable, and reversible"。

[^6^]: Arize, *Context management in agent harnesses*, 2026-08-12. https://arize.com/blog/context-management-in-agent-harnesses/ — "All four harnesses hard-cap file reads…cap tool result sizes…isolate sub-agent sessions…run LLM-powered compaction triggered by a token threshold…These are not coincidences. They are convergent solutions to the same engineering problem: a fixed-size working set that has to feel infinite." Claude Code 细节："Trigger: Estimated tokens exceed the effective context window minus a 13,000-token buffer…Fallback on prompt-too-long: a deterministic head-drop removes the oldest API-round groups."

[^7^]: Glean, *The harness as the context manager*, 2026-04-29. https://www.glean.com/blog/harness-context-manager — "preserves the parts of conversation state that are load-bearing for continued execution: user intent, decisions made so far, approaches that failed, planned next steps, and recent high-signal tool outputs…Large tool outputs are written to files in the sandbox filesystem and reduced to summaries with file paths"；sub-agent "its own context window and token budget"。

[^8^]: *Context Compaction Theory*, arXiv:2608.01326, 2026-08-02. https://arxiv.org/html/2608.01326v1 — "The constraint is that the LLM that the agent uses accepts at most W tokens of input…The summarization call reads 800,000 input tokens and generates 100,000 output tokens…That adds up to $13 for a single query."

[^9^]: *IDP AutoOpt*, arXiv:2607.26075v2, 2026-08-22, Appendix B. https://arxiv.org/html/2607.26075v2 — "At a 50% threshold, compaction occurs roughly every 18 iterations with minimal accuracy impact. At 10%, it fires approximately 5 times per iteration, consuming the time budget on summarization…Thresholds of 30–60% are practical; we use 50% throughout."

[^10^]: *MemoHarness: Agent Harnesses That Learn from Experience*, arXiv:2607.14159, 2026-07-14. https://arxiv.org/abs/2607.14159 — "decomposes the harness into six editable control dimensions (context, tool, generation, orchestration, memory, output)…A correctness-first ranking rule, with execution cost only as a tiebreaker, keeps the search from drifting onto cheap-but-wrong configurations…MemoHarness improves over the strongest fixed-harness baseline we run (0.806 vs. 0.722)."

[^11^]: Lin et al., *Agentic Harness Engineering (AHE)*, arXiv:2604.25850, 2026-04-28（v4 2026-05-18）. https://arxiv.org/abs/2604.25850 — "component observability gives every editable harness component a file-level representation so the action space is explicit and revertible…pairs every edit with a self-declared prediction, later verified against the next round's task-level outcomes…ten AHE iterations lift pass@1 on Terminal-Bench 2 from 69.7% to 77.0%…swapping in AHE's tools, middleware, or long-term memory alone yields +3.3, +2.2, and +5.6 pp, while the system prompt alone is −2.3 pp…The harness components ACE and TF-GRPO never edit are exactly where the gain lives." 代码：https://github.com/china-qijizhifeng/agentic-harness-engineering

[^12^]: Lee et al., *Meta-Harness: End-to-End Optimization of Model Harnesses*, arXiv:2603.28052, 2026-03-30. https://arxiv.org/abs/2603.28052 — "the harness: the code that determines what information to store, retrieve, and present to the model…Meta-Harness improves over a state-of-the-art context management system by 7.7 points while using 4x fewer context tokens…discovered harnesses surpass the best hand-engineered baselines on TerminalBench-2."

[^13^]: AHE §3.1（NexAU 基座）. https://arxiv.org/html/2604.25850v4 — "exposes seven orthogonal component types as explicit files at fixed mount points in a single workspace: system prompt, tool description, tool implementation, middleware, skill, sub-agent configuration, and long-term memory…Each logical edit becomes one commit on the workspace's git history, which yields file-level diffs and rollback granularity for free…A seed already fitted to the target benchmark would contaminate every subsequent edit's attribution."

[^14^]: *Self-Harness: Harnesses That Improve Themselves*, arXiv:2606.09498, 2026-06-08. https://arxiv.org/abs/2606.09498 — "Weakness Mining…Harness Proposal…Proposal Validation, which accepts candidate edits only after regression testing…every final harness improves both held-in and held-out pass rates, with overall relative gains of up to 132%"；Qwen3.5 案例 "reaches 36.7% after merging edits that emphasize artifact checking, missing-artifact recovery, retry discipline, and tool-error-triggered middleware."

[^15^]: *Live-SWE-agent*, arXiv:2511.13646, 2025-11-17. https://arxiv.org/abs/2511.13646 — "the first live, runtime self-evolving software engineering agent that expands and revises its own capabilities on the fly…This mechanism leaves the underlying scaffold unchanged, requires no offline training, and is agnostic to the underlying LLM…77.4% and 45.8% solve rates"；消融："base mini-SWE-agent 62.0%…prompt without explicit reflection 64.0%…full LIVE-SWE-AGENT 76.0%"；DGM 成本对照："DGM reportedly costing around $22,000 for a single run on SWE-bench."

[^16^]: *Darwin Gödel Machine*, arXiv:2505.22954 v3, 2026-03-12. https://arxiv.org/html/2505.22954v3 — "All agent execution and self-modification processes are conducted within isolated sandboxed environments…subjected to a strict time limit…confined to the well-defined domain of enhancing performance on specific coding benchmarks by modifying the agent's own Python codebase…the DGM archive providing a traceable lineage of modifications for review."

[^17^]: *Continual Harness*, arXiv:2605.09998, 2026-05-11. https://arxiv.org/abs/2605.09998 — "a reset-free self-improving harness for embodied agents…the agent alternates between acting and refining its own prompt, sub-agents, skills, and memory…Prompt-optimization methods require episode resets; Continual Harness adapts online within a single run."

[^18^]: *HarnessForge*, arXiv:2606.01779, 2026-06-01. https://arxiv.org/abs/2606.01779 — "formulates an agent system as a harness–policy pair…fault-guided harness tailoring…budgeted Pareto selection…Under the same rollout budget, policy evolution should not introduce a separate data-collection stage…implements it as a staged operator with fixed input-output contracts…making the evolution process auditable rather than opaque."

[^19^]: 预算治理综述 arXiv:2601.08815 §3.2（PDF 摘录）. https://arxiv.org/pdf/2601.08815 — "The TALE framework introduces token-budget-aware reasoning, achieving 68% reduction in token usage with less than 5% accuracy degradation…'token elasticity'…BudgetThinker addresses this through control tokens injected during inference…Liu et al. (2025) demonstrate that simply granting larger tool-call budgets fails to improve agent performance; their Budget-Aware Tool Selection (BATS) framework shows that explicit budget awareness enables effective scaling."

[^20^]: Muennighoff et al., *s1: Simple test-time scaling*, arXiv:2501.19393, 2025-01-31. https://arxiv.org/abs/2501.19393 — "budget forcing to control test-time compute by forcefully terminating the model's thinking process or lengthening it by appending 'Wait'…from 50% to 57% on AIME24."（BARD arXiv:2511.14702 指出朴素截断弱于学习型预算管理。）

[^21^]: *BudgetThinker*, arXiv:2508.17196, 2025-08-24. https://arxiv.org/html/2508.17196v1 — "periodically inserts special control tokens during inference to continuously inform the model of its remaining token budget…the Budget Ratio strategy yields the best performance…improves accuracy by an average of 4.9% across all tested budgets."

[^22^]: Han et al., *TALE: Token-Budget-Aware LLM Reasoning*, arXiv:2412.18547, 2024-12. https://arxiv.org/html/2412.18547v4 — "TALE-EP achieves a 67% reduction in token usage while maintaining accuracy with less than a 3% decrease…token elasticity: LLMs often exceed specified budgets when constraints are tight, demonstrating that prompting alone is insufficient for strict enforcement."

[^23^]: *EvoHarness-RL*, arXiv:2608.05446, 2026-08-05. https://arxiv.org/html/2608.05446v1 — "GRPO gradually internalizes routine scaffolded behaviors into the policy, while preserving harness access only when the expected benefit outweighs its step cost. Thus, EvoHarness-RL shifts from scaffolded exploration to selective, cost-aware coordination." 及 "Applying the explicit harness significantly elevates struggling frontier policies, boosting GPT-4.1 by +22.1 and GPT-5 by +25.7."

[^24^]: *RoboPhD*, arXiv:2604.04347, 2026-04-06. https://arxiv.org/abs/2604.04347 — "given the same information, the same seed agent, and the same objective, which optimization algorithm yields the best results under the same evaluation budget?…all under a fixed budget of 1,500 evaluations…RoboPhD introduces validation-free evolution…smaller validation sets consistently outperform larger ones under tight budgets…the optimal validation set size under budget pressure trends toward zero." 代码：https://github.com/andborth/RoboPhD

[^25^]: Microsoft Command Line, *TokenOps: Real-time, run-scoped cost control for AI agents*, 2026-08-13. https://commandline.microsoft.com/tokenops-real-time-run-scoped-cost-control-ai-agents/ — "each call: read the run's spend, apply the decision, dispatch, then record the true cost."

[^26^]: Kapoor, Stroebl, Siegel, Nadgir, Narayanan, *AI Agents That Matter*, arXiv:2407.01502, 2024-07. 经 https://agentpatterns.ai/token-engineering/cost-quality-pareto-measurement/ 转述："Kapoor et al. formalize the property as the non-dominated set under joint optimization…a simple warming-strategy baseline matched the LATS architecture's accuracy at roughly 2% of LATS's cost."

[^27^]: Kapoor et al., *Holistic Agent Leaderboard (HAL)*, arXiv:2510.11977, 2025-10. 同上转述："Across 21,730 agent rollouts spanning nine models and nine benchmarks ($40,000 spend)…increased reasoning-token budget reduced accuracy in 21 of 36 model × benchmark settings tested."

[^28^]: *Harness Updating Is Not Harness Benefit*, arXiv:2605.30621, 2026-05-28. https://arxiv.org/html/2605.30621v1 — "harness-updating is flat in base capability…even Qwen3.5-9B's updates yield gains comparable to those of Claude Opus 4.6…harness-benefit is non-monotonic…two failure modes: harness activation failure…harness adherence failure"；"The tools/ directory and evaluation files are read-only for all benchmarks. These permissions are passed to the evolver at each cycle"；"in-situ evaluation setting: each task in X_t is scored under H_{t−1} before its evidence is used to produce H_t"；遵循度漂移："Qwen3-32B drifts from 0.52 to 0.13."

[^29^]: *Huxley-Gödel Machine*, arXiv:2510.21614, 2025-10-24. https://arxiv.org/html/2510.21614v2 — "we identify a mismatch between the agent's self-improvement potential (metaproductivity) and its coding benchmark performance…a metric (CMP) that aggregates the benchmark performances of the descendants of an agent…with a budget-friendly modification applied consistently to both HGM and all baselines to ensure fairness…after a maximum allowance of 800 benchmark task evaluations."

（调研中使用的其他检索入口：Awesome-Reliable-Self-Evolving Agents（https://github.com/wkqdzkd/Awesome-Reliable-Self-Evolving-Agents，L2 Scaffold-Level 目录）、Awesome-Agent-Harness（Gloriaameng）、atto.bot arXiv harness 论文索引、agentic-ai.readthedocs.io 分类页。）

*报告完。*

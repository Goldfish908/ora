# Agent 记忆层自进化：机制全景与可复用设计调研

- 调研日期：2026-08-29
- 目标背景：自研 agent 系统（推理+验证 solver，冻结 Qwen 27B，CO-Bench/JSSP 组合优化评测，未来迁移数据集）。已有 prompt patch 跨代进化（(1+λ)+archive、阶梯评估、晋升协议、immutable generation snapshot、实验日志）与 memory.jsonl（写入闸门：同一 (signal, case_family) ≥2 episode 复发才入库；只喂变异不注入运行时）。目标：把 memory 升级为"可进化资产类型"（条目可 ADD/EDIT/RETIRE，检索/注入策略可进化）。
- 搜索记录：6 轮共 24 个独立查询（英文术语为主，兼查中文二手综述），覆盖 arXiv / GitHub / Anthropic 官方工程博客 / 厂商技术博客。逐条查询关键词见各节引用。

> 说明：任务要求核对的 **AdaExplore** 在公开文献与工程资料中**未查到**（应为内部/未公开名称），下文所有写入策略均为 AdaExplore 之外的公开先例。

---

## 1. 记忆写入闸门与提炼机制

### 1.1 A-MEM（Agentic Memory）——记忆条目可演化
- 来源：https://arxiv.org/abs/2502.12110（2025-02-17；NeurIPS 2025）
- 机制一句话：新记忆写入时生成含上下文描述/关键词/标签的结构化 note，与历史记忆自动建立链接；新记忆可**触发旧记忆的上下文表示与属性更新（Memory Evolution）**，整个记忆网络持续精炼。[^1^]
- 证据强度：有对照实验（LoCoMo 长对话数据集、6 个基座模型、6 项指标，"demonstrating significant improvements"）。[^1^]
- 可复用性：**机制移植**（EDIT 算子的直接范本：写入时不只 ADD，还允许新证据重写既有条目字段）。GitHub 有开源实现可代码参考。
- 适用判断：高适用。其"新记忆触发旧条目演化"可直接映射为背景系统 memory.jsonl 的 EDIT 算子：当新 episode 与既有 (signal, case_family) 条目复发时，不只 support_count+1，而允许改写条目文本（保留版本号与 generation snapshot 对应关系）。注意其演化由 LLM 在线执行，背景系统是离线进化循环，更安全。

### 1.2 MemGPT / Letta——memory block 自编辑 + sleep-time 离线重组
- 来源：MemGPT arXiv:2310.08560（2023-10）；Letta 模式综述 https://github.com/Teja216/Agent_Memory（2026-08-06 更新）；Sleep-time Compute https://arxiv.org/abs/2504.13171（2025-04-17）
- 机制一句话：core memory 是始终驻留在 prompt 内的可编辑文本块，agent 通过 `core_memory_append/replace` 等**工具调用自主编辑自己的记忆**；sleep-time compute 让第二个 agent 在空闲时离线重组/整合记忆，使下一轮推理从更干净的上下文开始。[^2^][^3^]
- 证据强度：架构级证据（SWE 修复案例平均省 3,000 tokens 且方案更好）；工程综述明确指出局限："Token overhead is high…LLMs sometimes forget to update core memory, make incorrect replacements"。[^2^][^3^]
- 可复用性：**机制移植**（自编辑工具接口 + 离线重组 pass 的分工）。Letta 框架本身代码复用价值低（面向对话场景）。
- 适用判断：中高适用。背景系统已有"写入闸门"，可补一个"离线 consolidate pass"（对应晋升协议之间执行）：对 memory.jsonl 做去重/合并/冲突消解，产出新 generation 的记忆快照。其警示同样适用：让单个 LLM 自由 EDIT 核心记忆会产生错误替换，必须配合版本化与评估闸门——这正是背景系统已有晋升协议的优势。

### 1.3 EverMemOS（EverMind）——原子 MemCell + 分层组织 + 混合索引
- 来源：arXiv:2601.02163（2026-01，论文名 "EverMemOS: A Self-organizing Memory Operating System"）；第三方评测 https://www.switchtools.io/tool/evermemos（2026-08-19）
- 机制一句话：原始交互被加工成原子 MemCell（episodic trace、原子事实、time-bounded foresight），再组织成 episode/语义知识图谱/user profile 多级记忆；检索用 BM25(Elasticsearch)+向量(Milvus)+RRF，可选 LLM 引导的多轮检索。[^4^]
- 证据强度：厂商自报 LoCoMo 93.05%、检索延迟 <300ms、记忆蒸馏比 naive 长上下文省最多 70% token（未独立复现，权威度低）。[^4^]
- 可复用性：**仅参考**（重型基础设施 MongoDB/ES/Milvus/Redis，不适合自研进化实验台）。
- 适用判断：低-中。可借鉴"原子条目→高层结构"的两层组织（memory.jsonl 原子条目 + 按 case_family 聚合的家族级条目），其余工程栈不必引入。

### 1.4 MemGen——生成式隐空间记忆（参数化方向）
- 来源：https://arxiv.org/abs/2509.24704（2025-09；ICLR 2026）
- 机制一句话：动态生成式记忆框架，让 agent 自发演化出 planning/procedural/working memory 等类人记忆机能（latent memory，嵌入模型内部）。[^5^]
- 证据强度：有对照实验（会议接收）。
- 可复用性：**仅参考**。
- 适用判断：**不适用**。背景系统 LLM 冻结（Qwen 27B），latent/参数化记忆路线与约束冲突；列出仅为全景完整性。

### 1.5 MIRIX——六类记忆 + Meta Memory Manager 路由
- 来源：https://arxiv.org/abs/2507.07957（2025-07-10）
- 机制一句话：Core/Episodic/Semantic/Procedural/Resource/Knowledge Vault 六类结构化记忆，各配 Memory Manager，由 Meta Memory Manager 做写入路由；检索侧提出 **Active Retrieval**——agent 回答前必须先生成 topic 再检索，检索结果注入 system prompt。[^6^]
- 证据强度：有对照实验（ScreenshotVQA 比 RAG 高 35%、存储降 99.9%；LOCOMO SOTA 自报）。
- 可复用性：**机制移植**（记忆分桶 + 写入路由决策；主动触发式检索）。
- 适用判断：中适用。"按记忆类型分桶"对背景系统的启示：memory.jsonl 条目可加 type 字段（failure_signal / strategy_hint / verifier_hint），写入路由与检索路由都可作为可进化参数。Active Retrieval 是"触发式注入"的学术先例，但背景系统当前"不注入运行时"的决策有其合理性（见 §3.2 负迁移证据）。

### 1.6 MemoryOS——OS 启发的分层记忆与 heat-based 更新
- 来源：EMNLP 2025（arXiv:2506.06326）
- 机制一句话：short-term / mid-term / long-term 三级记忆，按"热度"在层级间迁移更新（含分段分页式组织），在 LoCoMo 上以 F1/BLEU-1 与 MemoryBank/MemGPT/A-MEM 对比。[^7^]
- 证据强度：有对照实验（LoCoMo + GVD，多基线）。
- 可复用性：**机制移植**（层级晋升 = 温度/频次驱动的条目升降级，天然对应背景系统的"晋升协议"）。
- 适用判断：中适用。其"热度驱动的层级迁移"可直接映射为：memory 条目按 retrieval 命中/复用次数在 active pool 与 cold archive 间迁移，迁移阈值作为可进化超参。

### 1.7 Mem0——结构化记忆操作集 ADD/UPDATE/DELETE/NOOP
- 来源：https://arxiv.org/abs/2504.19413（2025-04）
- 机制一句话：从对话中抽取候选事实后，与既有记忆比对，由 LLM 在 {ADD, UPDATE, DELETE, NOOP} 四操作中决策，实现记忆的显式增删改。[^8^]
- 证据强度：有对照实验（LoCoMo 上相对 RAG/全上下文提升，延迟/成本下降）；被后续大量工作（Memory-R1 等）作为操作集标准沿用。
- 可复用性：**机制移植**（四操作集已成为事实标准，背景系统的 ADD/EDIT/RETIRE 可直接对齐：EDIT≈UPDATE、RETIRE≈DELETE）。
- 适用判断：高适用（作为操作词汇表的标准化参考）。

### 1.8 ReasoningBank——成功+失败双通道的推理记忆
- 来源：https://arxiv.org/abs/2509.25140（2025-09，Google/UIUC）
- 机制一句话：把成功与失败轨迹都蒸馏为可复用的推理策略条目（含标题/描述/内容），检索注入后续任务，并配套 memory-aware test-time scaling（MaTTS）。[^9^]
- 证据强度：有对照实验（WebArena/Mind2Web，相对无记忆与轨迹记忆基线提升）。
- 可复用性：**机制移植**。
- 适用判断：高适用。背景系统 JSSP 场景可从失败 episode 蒸馏"哪类 search move 在哪类 case_family 上失败"的反例条目——与现有 (signal, case_family) 键天然兼容。

### 1.9 Dynamic Cheatsheet / ACE——可增删改的"活文档"记忆
- 来源：Dynamic Cheatsheet https://arxiv.org/abs/2504.07952（2025-04）；ACE（Agentic Context Engineering）https://arxiv.org/abs/2510.04618（2025-10）
- 机制一句话：维护一份随测试样本流持续策展的 cheatsheet/playbook，LLM 对其做增量 delta 更新（追加/修订/去重）而非整体重写，防止"context collapse"。[^10^][^11^]
- 证据强度：Dynamic Cheatsheet 有跨任务对照（数学/谜题/多跳 QA 提升）；ACE 有 AppWorld/金融分析对照（+10.6% 等），并实证了整体重写导致的细节侵蚀问题。[^11^]
- 可复用性：**机制移植**（增量 delta 更新 + 条目化 playbook）。
- 适用判断：高适用。背景系统的 prompt patch 已是条目化；memory.jsonl 升级为"条目化 + delta 操作日志"后，与现有 immutable generation snapshot 天然兼容（快照=条目集+操作日志）。ACE 对"重写导致信息坍缩"的实证支持保留 RETIRE 而非覆盖式清理。

### 1.10 写入闸门的直接实证：Selective Addition
- 来源：HBS AI Institute 研究简报 https://aiinstitute.hbs.edu/smarter-memories-stronger-agents-how-selective-recall-boosts-llm-performance/（2025-08-21）
- 机制一句话：跨 EHR/自动驾驶/网络安全三类 agent 的实证：**"add-all"（每条经验都入库）比完全不加记忆更差**；严格评估过滤后再写入，平均带来 ~10% 性能提升。[^12^]
- 证据强度：有对照实验（3 个领域 agent，add-all vs no-memory vs selective）。
- 可复用性：**仅参考**（证据）。
- 适用判断：直接验证背景系统现有"≥2 episode 复发才入库"闸门的设计方向；闸门阈值本身可纳入进化超参。

### 1.11 Mem-α / A-MAC——把"写什么"当可学习对象
- 来源：Mem-α https://arxiv.org/abs/2509.25911（2025-09）；A-MAC 见 https://arxiv.org/pdf/2605.00356 的相关工作综述（2026-05）
- 机制一句话：Mem-α 用 RL 训练"记忆构建策略"（写什么、怎么组织）；A-MAC 把写入准入分解为 utility/novelty/confidence 三个可解释因子再决策。[^13^][^14^]
- 证据强度：均有对照实验。
- 可复用性：**机制移植**（A-MAC 的三因子准入打分不需要 RL，可直接做成可进化规则）。
- 适用判断：中-高适用。背景系统可把写入闸门从单一"复发计数"升级为 (utility, novelty, confidence) 多因子打分，各因子权重作为可进化基因；置信标注同时服务 §3 的质量治理。

---

## 2. 检索与注入策略

### 2.1 Anthropic Agent Skills——progressive disclosure 三级披露
- 来源：https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills（2025-10；2025-12-18 转为开放标准）
- 机制一句话：Level 1 仅常驻 SKILL.md 的 name+description（约 100 tokens），Level 2 触发后才读入正文（<5k tokens），Level 3+ 的引用文件按需加载——**用"元数据常驻 + 正文触发"替代全文常驻**。[^15^]
- 证据强度：官方工程规范（无对照实验，但给出明确 token 预算表：L1≈100、L2<5k、L3 不限）。
- 可复用性：**机制移植**（披露层级设计 + description 即路由键）。
- 适用判断：高适用。背景系统 memory 条目可拆为"常驻索引行（signal/case_family/一行摘要，~几十 token/条）+ 触发后注入的完整条目"两层；条目的 description 质量直接决定触发率，可作为可进化字段（与 prompt patch 进化共用变异算子）。

### 2.2 渐进披露的实证对照：Is Progressive Disclosure All You Need?
- 来源：https://arxiv.org/abs/2607.17598（2026-07-20）
- 机制一句话：把 Agent Skills 规范中捆绑的两个设计选择（递归披露深度、索引物理位置）拆开对照：raw / flat disclosure / hierarchical disclosure 三方案在书级长文档上比较。[^16^]
- 证据强度：有对照实验（三方案受控比较）。
- 可复用性：**仅参考**（评估协议设计可借）。
- 适用判断：中适用。其价值在于示范了"注入策略本身可以受控 A/B"——背景系统进化检索/注入策略时，应采用同样方式把"披露深度"与"索引位置"作为独立基因而非耦合变量。

### 2.3 检索 top-K 实证（"K 峰值"类结论）
- **MEMTIER（LongMemEval-S 消融）**：来源 https://arxiv.org/pdf/2605.03675（2026-05）。全系统默认 k=4，k 扫描显示 k=2 为最优、k=8 时性能下降，呈倒 U；token 注入预算 150/300/600 也有独立扫描。[^17^]
- **MemCoT**：来源 https://arxiv.org/html/2604.08216v1（2026-04-09）。细粒度 TopK 在 10–15 区间有显著收益，>15 后性能下降，作者归因于"retrieved memory entries expanding the context…thereby inducing catastrophic forgetting"。[^18^]
- **Exabase M-1（LongMemEval 工程复现）**：来源 https://exabase.io/research/exabase-achieves-state-of-the-art-on-longmemeval-benchmark（2026-08-06）。准确率 top-10=90.8% → top-50=96.4%（峰值）→ top-200=95.4%（回落），"at greater depths, additional context introduces noise that can degrade answering accuracy, even as recall coverage increases"。[^19^]
- **LongMemEval 本体**：阅读策略（Chain-of-Note + JSON 结构化）在检索完美时也能造成 10 分差距——"Even with perfect retrieval, suboptimal reading strategies could cause 10-point accuracy drops"。[^20^]
- 证据强度：三个独立 k 扫描均呈**倒 U 曲线**（小-中 k 最优，大 k 因噪声回落）；具体峰值随任务/预算变化（2、4、10-15、50 均有报告）。任务给出的"K=4 峰值"单一出处**未查到**，但"存在有限最优 K、超量注入有害"是多方一致的实证结论。
- 适用判断：直接适用于背景系统——**K 必须作为可进化超参而非固定常量**，且评测时要同时记录"注入 token 预算"维度（MEMTIER 证明两个维度可分别扫描）。

### 2.4 memory 注入 vs 常驻 system prompt 的 token 税
- 来源：Mem0 工程博客 https://mem0.ai/blog/the-2026-token-optimization-playbook-cut-ai-agent-memory-costs-3%E2%80%934x（2026-05-06）
- 机制一句话：全量常驻注入随条目数线性增长（7 条≈146 tokens/call，24 条=594，200 条≈3,200，500 条≈8,000），检索式注入在同 24 条库上仅 166 tokens（top-5），**同质量下省 72%**（真实 usage.prompt_tokens 验证）。[^21^]
- 证据强度：工程级对照（同库同模型同查询，厂商动机需注意）；方向性结论与 Letta 模式综述"Token overhead is high…consume a large share of the context window before the conversation even starts"一致。[^2^]
- 可复用性：**仅参考**（测算方法可直接抄：对比 usage.prompt_tokens）。
- 适用判断：高适用。给背景系统的注入策略进化提供**成本项**：适应度函数除 CO-Bench 分数外应计入注入 token 税（多目标或罚项），否则进化会倾向于无限注入。

### 2.5 触发式注入的其他先例
- MIRIX Active Retrieval（先让 agent 生成 topic 再检索注入 system prompt）[^6^]；"Ask only when needed: Proactive retrieval from memory and skills"（arXiv:2604.20572，2026-04）——把"何时检索"训练/决策化，只在需要时主动取记忆与技能。[^22^]
- 证据强度：MIRIX 有对照；后者为预印本。
- 适用判断：中适用。背景系统目前是"只喂变异不注入运行时"；这些先例说明若未来要做运行时注入，"先自评是否需要再触发"是比"每步固定注入"更稳的默认策略。

---

## 3. 记忆质量治理

### 3.1 记忆污染与错误累积的实证
- **MINJA（Memory INjection Attack）**：来源 https://arxiv.org/abs/2503.03704（2025-03；v5 2026-02）。攻击者仅通过查询交互即可向 agent 记忆库注入恶意记录，借助 bridging steps 使恶意记录在受害查询时被检索命中——**写入侧无过滤 = 任何人都能污染记忆**。[^23^] 证据强度：多 agent 对照实验。
- **跨域负迁移（Memory Transfer Learning）**：来源 https://arxiv.org/abs/2604.14004（2026-04-15）。六基准共享记忆池平均 +3.7%，但低抽象记忆（raw trajectory）会负迁移，机制归因三类：domain-mismatched anchoring（表面相似但结构无关的记忆当错误锚点）、false validation confidence（验证类记忆制造虚假确定感，"self-confirming loops"）、misapplied best-practice transfer；高抽象 insight 记忆跨域迁移安全。[^24^] 证据强度：有对照 + 失败案例分类学。
- **经验复用研究**（When Continual Learning Moves to Memory）：Raw 记忆在 A→B 序列上 FWT 为负，且负迁移集中在 hard cases（ΔNL=-26.1）；Insight 记忆显著降低脆弱性。[^25^]
- **选择性写入实证**：add-all 比无记忆更差（见 §1.10）。[^12^]
- 适用判断：对背景系统有三点直接含义——(1) "只喂变异不注入运行时"当前是**有实证支持的保守正确选择**，尤其"false validation confidence"对 verifier 类信号最危险（检索到的旧验证结论可能让 solver 跳过真实验证）；(2) 若未来做运行时注入，应优先注入**高抽象 insight 条目**而非 raw episode；(3) 迁移新数据集时应对记忆做**域适配过滤/重写**，不能整库搬运。

### 3.2 对策机制清单
- **Ebbinghaus 遗忘曲线衰减**：MemoryBank（AAAI 2024）按时间与重要性动态调整记忆强度，旧而低用的条目衰减、被反复强化的保留。[^8^] MEMTIER 消融中移除 time decay 权重 -0.016 Acc，独立贡献可测。[^17^]
- **support_count / 复发闸门**：背景系统已有；A-MAC 将准入分解为 utility/novelty/confidence 三因子，是闸门结构化的升级方向。[^14^]
- **置信标注**：A-MAC confidence 因子[^14^]；MemX 的 low-confidence rejection rule（检索置信不足时拒答，抑制虚假召回）[^26^]。
- **冲突消解/知识更新**：LongMemEval 把 knowledge updates 列为五大能力之一；多粒度记忆系统中 Refresher（显式冲突解决与更新机制）在 knowledge-update 场景 0.897 vs 移除后 0.568——**没有显式更新机制时旧记忆严重拖后腿**。[^27^]
- **Truth-maintained memory agent**（NeurIPS 2025）：主动质量控制维护记忆真值。[^28^]
- 适用判断：RETIRE 算子建议实现为"衰减 + 显式冲突检测"双通道：support_count 长期不增长→衰减降级；新条目与旧条目矛盾→走晋升协议裁决而非静默覆盖（对应 ACE 反 context-collapse 证据）。[^11^]

### 3.3 记忆评测基准（可借为 memory 进化 evaluator）
| 基准 | 来源 | 设计要点 | 对背景系统的借用方式 |
|---|---|---|---|
| **LoCoMo** | ACL 2024, https://aclanthology.org/2024.acl-long.747/ | 最长 35 会话/约 300 轮/9-16K tokens 的合成+人校对话；QA 分 single-hop/multi-hop/temporal/open-domain/adversarial 五类（adversarial 考拒答）；1986 题，常用 1540 非对抗子集；F1/LLM-judge [^29^][^30^] | 场景为对话，**不能直接当 evaluator**；可借"按能力维度切分报告"与"adversarial/拒答类"设计——对应背景系统可构造"该记忆不应被触发的 case"作负样本 |
| **LongMemEval** | ICLR 2025, https://arxiv.org/abs/2410.10813 | 500 题嵌入可伸缩聊天历史（S≈115K tokens，M≈500 会话）；五能力：信息抽取/多会话推理/时间推理/知识更新/拒答；把记忆设计统一拆为 indexing/retrieval/reading 三阶段 + value/key/query/reading 四控制点，并逐项消融 [^20^] | **三阶段四控制点框架是检索/注入策略进化空间的现成坐标系**（粒度、键扩展、查询扩展、阅读格式都可作基因）；"知识更新"维度对应 EDIT/RETIRE 算子的评测 |
| **MemoryBench** | arXiv:2510.17281（2025-10，THUIR） | Task Provider + User Simulator + Performance Monitor 三模块；同时覆盖陈述性/程序性记忆与显式/隐式反馈，测持续学习 [^31^] | 可借"训练期反馈日志→测试期性能监控"的协议结构，把 episode 日志当训练侧、held-out CO-Bench case 当测试侧 |
| **MemBench / MemoryAgentBench / MemoryArena** | MemBench [Tan et al. 2025]；MemoryAgentBench [Hu et al. 2025]；MemoryArena arXiv:2602.16313 | MemoryAgentBench 四能力含 **selective forgetting**（现有系统普遍失败）；MemoryArena 发现 LoCoMo 近满分模型在决策相关任务上跌到 40-60%——**被动回忆≠决策可用** [^32^] | 警示：别用"条目检索命中率"当进化适应度；应以"注入该记忆后下游求解是否变好"（决策相关）为适应度，正好契合背景系统以 CO-Bench 分数为终评的现有管线 |
| **Evo-Memory / EvoMemBench / TAME** | arXiv:2511.20857；arXiv:2605.18421；arXiv:2602.03224 | 专门从"自进化"视角评测 test-time 记忆学习/记忆演化可信度 [^33^][^34^] | 协议参考（自进化系统的评测设计要求跨代追踪，而非单代静态测） |
| **LoCoMo-Plus** | arXiv:2602.10715（2026-02） | 揭示字符串匹配指标与任务提示会系统性误导；cue-trigger 语义断开下的隐式约束记忆 [^35^] | 提醒：用 LLM-judge 评记忆质量时要防"表面重叠"假阳性 |

---

## 4. 把"检索策略/记忆控制器"当可进化对象的先例

### 4.1 Memory-R1——RL 学习的 Memory Manager
- 来源：https://arxiv.org/abs/2508.19828（2025-08-27）
- 机制一句话：Memory Manager 用 PPO/GRPO 学习 {ADD, UPDATE, DELETE, NOOP} 操作决策，Answer Agent 学习从检索条目中筛选与推理；仅 152 个 QA 对训练即超过最强基线，跨 LoCoMo/MSC/LongMemEval 与 3B-14B 骨干泛化。[^36^]
- 证据强度：有对照实验（三基准多骨干消融）。
- 可复用性：**仅参考**（RL 训练记忆策略）。
- 适用判断：中适用。背景系统 LLM 冻结，无法 GRPO；但其证明"写/删/留操作决策本身可学、且小数据即可学"——为"用进化（而非梯度）学习同一决策策略"提供动机背书，(1+λ) 进化正是无梯度替代。

### 4.2 MemSkill——记忆操作技能库的双层进化（与背景系统最同构）
- 来源：https://arxiv.org/abs/2602.02474（2026-02-02；v2 2026-05）
- 机制一句话：把记忆操作重构为**可学习可进化的 memory skills**（抽取/整合/剪枝例程）：controller 学"选哪些 skill"（RL），LLM executor 按 skill 产出记忆，designer 周期性挖掘 hard cases **精炼旧 skill 并提出新 skill**；维护最优 skill bank 快照、退化即回滚，形成闭环。[^37^]
- 证据强度：有对照实验（LoCoMo/LongMemEval/HotpotQA/ALFWorld 一致提升+泛化）；演化出的技能呈领域专门化（LoCoMo 技能偏时间/活动结构，ALFWorld 偏动作约束/物体位置）。
- 可复用性：**机制移植 + 部分代码复用**（开源 github.com/ViktorAxelsen/MemSkill）。
- 适用判断：**最高同构先例**。其"hard-case buffer + designer + 快照回滚 + 新技能探索偏置"与背景系统的"(signal,case_family) 复发闸门 + 变异算子 + immutable snapshot + 晋升协议"几乎一一对应；其 controller 的 RL 可替换为背景系统已有的进化选择。直接借鉴点：(1) skill 进化每轮限 3 处编辑、每 100 步触发一次（防突变失控）；(2) hard case 用聚类+难度分选代表（复发失败模式优先）——与"≥2 复发"闸门同理但更精细；(3) 快照回滚即晋升协议的否决分支。[^37^]

### 4.3 MemEvolve + EvolveLab——记忆架构本身作为进化对象
- 来源：https://arxiv.org/abs/2512.18746（2025-12-21）
- 机制一句话：把 12 个代表性记忆系统蒸馏为 (encode, store, retrieve, manage) 模块化设计空间（EvolveLab），**元进化框架联合进化"经验知识"与"记忆架构本身"**，跨任务跨 LLM 迁移，给 SmolAgent/Flash-Searcher 等带来最高 +17.06%。[^38^]
- 证据强度：有对照实验（4 个 agentic 基准，跨任务/跨骨干泛化）。
- 可复用性：**机制移植 + 代码复用**（EvolveLab 统一代码库）。
- 适用判断：高适用。这是"检索/注入策略可进化"最直接的学术先例：其 (encode, store, retrieve, manage) 四元组可直接作为背景系统记忆策略的基因分段；其跨 LLM 迁移结论支持"在 Qwen 27B 上演化出的策略可迁移到未来骨干"。

### 4.4 Memento——神经 case 检索策略（memory reading 即策略改进）
- 来源：https://arxiv.org/abs/2508.16153（2025-08-22）
- 机制一句话：M-MDP 形式化下，case bank 写入只追加 (s,a,r)，**策略改进完全由 memory reading（检索）实现**：参数化变体在写入时在线更新 Q(s,c;θ)，读取按学到的 Q 分布采样 case——"记忆不变，检索策略在变"。[^39^]
- 证据强度：有对照（GAIA val 87.88% Pass@3 第一；case memory 在 OOD 上加 4.7-9.6 点；参数化与非参数化 CBR 消融）。
- 可复用性：**机制移植**（外部小 Q 网络不涉及 LLM 权重，与冻结约束兼容）。
- 适用判断：高适用。若想在进化之外加一层"快适应"，可让检索打分函数含一个小的可在线更新模块（如每条目维护命中后成功率统计，做 Beta/Bayesian 加权），慢层仍走 (1+λ) 进化——快慢双层。

### 4.5 其他检索策略学习先例
- **Budget-tier routing**（arXiv:2602.06025，2026-02）：学习 query-aware 的预算分层路由，按查询决定取哪档记忆预算。[^40^]
- **Memory as Action**（arXiv:2510.12635，2025-10）：把记忆操作建模为 agent 的动作空间，自主策展上下文。[^41^]
- **MemSearcher / AgeMem / MemRL**：端到端 RL 训练"搜索+管理记忆"统一策略；AgeMem 把六种记忆操作暴露为工具调用做渐进式 RL。[^14^][^42^]
- 适用判断：均为 RL 路线，作全景备案；背景系统的无梯度对应物就是"检索策略基因 + CO-Bench 适应度"的进化，证据链由 4.1-4.4 提供。

---

## 5. 综合：对背景系统的可复用设计建议

1. **操作词汇表对齐标准**：ADD/EDIT(≈UPDATE)/RETIRE(≈DELETE)/NOOP 四操作（Mem0[^8^]、Memory-R1[^36^] 事实标准）；EDIT 允许新证据重写条目字段（A-MEM 的 Memory Evolution[^1^]），RETIRE 走衰减+冲突裁决双通道（§3.2），避免整体重写（ACE 反 context-collapse[^11^]）。
2. **进化空间坐标系**：记忆策略基因 = LongMemEval 的 (value 粒度, key 扩展, query 扩展, reading 格式) 四控制点[^20^] × MemEvolve 的 (encode, store, retrieve, manage) 四段[^38^]；K 与注入 token 预算必须是独立基因（倒 U 证据[^17^][^18^][^19^]，token 税证据[^21^]）。
3. **披露结构**：条目拆"常驻索引行 + 触发正文"两层（Anthropic Skills L1/L2[^15^]）；description/触发条件作为可进化字段。
4. **适应度设计**：用决策相关指标（注入后 CO-Bench 分数差）而非检索命中率（MemoryArena 的被动回忆陷阱[^32^]）；构造"不应触发"的负样本 case（LoCoMo adversarial 设计[^29^]）；适应度计入 token 税。
5. **防污染**：维持并强化复发闸门（selective-addition 实证[^12^]）；准入升级为 utility/novelty/confidence 多因子打分（A-MAC[^14^]）；优先演化高抽象 insight 条目而非 raw 轨迹（负迁移证据[^24^][^25^]）；若未来运行时注入，"先自评再触发"（MIRIX/Ask-only-when-needed[^6^][^22^]），并对 verifier 相关条目特别警惕 false validation confidence[^24^]。
6. **过程治理**：直接复用 MemSkill 的闭环节奏——hard-case 聚类选代表、每轮限编辑数、最优快照回滚[^37^]，与现有晋升协议/immutable snapshot 同构合并；未来迁移新数据集时记忆库需域适配过滤而非整库搬运[^24^]。

---

## 引用

[^1^]: A-MEM: Agentic Memory for LLM Agents, arXiv:2502.12110, 2025-02-17。https://arxiv.org/abs/2502.12110 。摘录："this process enables memory evolution - as new memories are integrated, they can trigger updates to the contextual representations and attributes of existing historical memories, allowing the memory network to continuously refine its understanding."
[^2^]: Letta/MemGPT patterns, Agent_Memory repo, 2026-08-06。https://github.com/Teja216/Agent_Memory/tree/main/all_techniques/26_letta_memgpt_patterns 。摘录："The agent calls memory tools: edit core memory, search recall or archival memory, or insert new archival entries… Token overhead is high. The memory tools, system prompt, and core memory blocks consume a large share of the context window before the conversation even starts."
[^3^]: Sleep-time Compute: Beyond Inference Scaling at Test-time, arXiv:2504.13171, 2025-04-17。https://arxiv.org/abs/2504.13171 。摘录："Your task is to re-organize and consolidate memories by calling rethink_memory at every single step…"（Letta-Offline-Memory 提示词）。
[^4^]: EverMemOS 第三方评测, SwitchTools, 2026-08-19。https://www.switchtools.io/tool/evermemos 。摘录："The February 2026 launch of EverMemOS Cloud added a production-ready API layer, achieving 93.05% accuracy on the LoCoMo benchmark with retrieval latency under 300ms… Memory distillation cuts context-window token usage by up to 70%."；论文：arXiv:2601.02163（2026-01，"EverMemOS: A self-organizing memory operating system for structured long-horizon reasoning"）。
[^5^]: MemGen: Weaving Generative Latent Memory for Self-Evolving Agents, arXiv:2509.24704, 2025-09；ICLR 2026。https://arxiv.org/abs/2509.24704 。摘录（TLDR 转引自 arXiv:2601.07468）："MemGen…spontaneously evolves distinct human-like memory faculties, including planning memory, procedural memory, and working memory."
[^6^]: MIRIX: Multi-Agent Memory System for LLM-Based Agents, arXiv:2507.07957, 2025-07-10。https://arxiv.org/abs/2507.07957 。摘录："we propose an Active Retrieval mechanism, where the agent is required to generate a topic before answering the question or executing the next step, and the retrieved information is inputted into the model in the system prompt."
[^7^]: Memory OS of AI Agent (MemoryOS), arXiv:2506.06326；EMNLP 2025。https://arxiv.org/pdf/2506.06326 。摘录："TiM manages memory via insertion, forgetting, and merging… MemoryBank dynamically adjusts memory strength based on the Ebbinghaus Forgetting Curve…"（对比方法与 LoCoMo 评测设置）。
[^8^]: Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory, arXiv:2504.19413, 2025-04。转引自 Memento 相关工作（arXiv:2508.16153）："Mem0 adopts a structured memory mechanism with explicit operations (ADD, UPDATE, DELETE, NOOP)."
[^9^]: ReasoningBank: Scaling Agent Self-Evolving with Reasoning Memory, arXiv:2509.25140, 2025-09。https://arxiv.org/abs/2509.25140 （经 SkillNet arXiv:2603.04448 引用确认）。
[^10^]: Dynamic Cheatsheet: Test-Time Learning with Adaptive Memory, arXiv:2504.07952, 2025-04。https://arxiv.org/abs/2504.07952 。
[^11^]: ACE: Agentic Context Engineering: Evolving Contexts for Self-Improving Language Models, arXiv:2510.04618, 2025-10。https://arxiv.org/abs/2510.04618 ；二手综述摘录（https://www.ayautomate.com/blog/context-engineering, 2026-06-17）："Newer research like Agentic Context Engineering (ACE) treats context as an evolving, itemized playbook that updates incrementally instead of being rewritten…context collapse (rewriting context repeatedly erodes detail)."
[^12^]: How Selective Recall Boosts LLM Performance, HBS AI Institute, 2025-08-21。https://aiinstitute.hbs.edu/smarter-memories-stronger-agents-how-selective-recall-boosts-llm-performance/ 。摘录："simply storing every experience leads to significantly worse outcomes…storing every task and output ('add-all') performed worse than using no memory addition at all…strict evaluation criteria and filtering before storage led to an average 10% performance boost."
[^13^]: Mem-α: Learning Memory Construction via Reinforcement Learning, arXiv:2509.25911, 2025-09。https://arxiv.org/abs/2509.25911 （经 arXiv:2605.00702 引用确认）。
[^14^]: RL-Trained Memory Management 综述段落，arXiv:2605.00356, 2026-05。https://arxiv.org/pdf/2605.00356 。摘录："Memory-R1…trains both a Memory Manager, which predicts ADD/UPDATE/DELETE/NOOP operations…A-MAC decomposes admission into interpretable factors such as utility, novelty, and confidence…AgeMem exposes six memory operations as tool calls and trains a unified policy through progressive RL."
[^15^]: Equipping agents for the real world with Agent Skills, Anthropic Engineering, 2025-10（2025-12-18 起为开放标准）。https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills 。摘录："This metadata is the first level of progressive disclosure…Level 1 SKILL.md Metadata (YAML): Always loaded, ~100 Tokens; Level 2 SKILL.md Body: Loaded when Skill triggers, <5k; Level 3+ Bundled files: Loaded as-needed."
[^16^]: Is Progressive Disclosure All You Need for Long-Context Agents?, arXiv:2607.17598, 2026-07-20。https://arxiv.org/abs/2607.17598 。摘录："the Agent Skills specification bundles two design choices the practitioner literature never separates: how deep the disclosure recurses, and where the per-chunk index physically lives. We pull them apart by comparing…Raw-document navigation…Flat disclosure…Hierarchical disclosure."
[^17^]: MEMTIER 消融表（arXiv:2605.03675, 2026-05）。https://arxiv.org/pdf/2605.03675 。摘录："Table 2: Ablation study on LongMemEval-S (N=500). Full system: Acc=0.382, F1=0.412 (k=4, 300 tokens)…Retrieval entries k: k=1…k=2 (optimal)…k=4 (default)…k=8"；另 "- time decay (w_decay=0): ΔAcc -0.016"。
[^18^]: MemCoT: Test-Time Scaling through Memory-Driven Chain-of-Thought, arXiv:2604.08216, 2026-04-09。https://arxiv.org/html/2604.08216v1 。摘录："setting K in the range of 10–15 yields a notable performance gain, whereas values exceeding 15 lead to a decline. We attribute this to the increased number of retrieved memory entries expanding the context…thereby inducing catastrophic forgetting."
[^19^]: Exabase M-1: Beyond Model Scale for Long-Term Memory, 2026-08-06。https://exabase.io/research/exabase-achieves-state-of-the-art-on-longmemeval-benchmark 。摘录："Performance peaks at top-50 (96.4%) and slightly declines at top-200…at greater depths, additional context introduces noise that can degrade answering accuracy, even as recall coverage increases."
[^20^]: LongMemEval, arXiv:2410.10813 / OpenReview pZiyCaVuti（ICLR 2025）。https://arxiv.org/abs/2410.10813 。摘录（alphaxiv 综述）："Even with perfect retrieval, suboptimal reading strategies could cause 10-point accuracy drops…expanding the keys with extracted user facts improves both memory recall (9.4% higher recall@k) and downstream question answering (5.4% higher accuracy)…time-aware query expansion…improving the memory recall for temporal reasoning by 6.8%~11.3%."
[^21^]: The 2026 Token Optimization Playbook, Mem0 blog, 2026-05-06。https://mem0.ai/blog/the-2026-token-optimization-playbook-cut-ai-agent-memory-costs-3%E2%80%934x 。摘录："24 entries already costs 594 tokens per call. A retrieval-based memory architecture cuts that to 166 tokens with identical answer quality, thereby 72% savings…7 entries requires ~146 prompt tokens per call; 200 entries requires ~3,200 tokens; 500 entries requires ~8,000 tokens."
[^22^]: Ask Only When Needed: Proactive Retrieval from Memory and Skills for Experience-Driven Lifelong Agents, arXiv:2604.20572, 2026-04。（经 arXiv:2605.07164 参考文献确认）。
[^23^]: Memory Injection Attacks on LLM Agents via Query-Only Interaction (MINJA), arXiv:2503.03704, 2025-03（v5 2026-02-12）。https://arxiv.org/abs/2503.03704 。摘录："The attacker injects malicious records into the memory bank by only interacting with the agent via queries and output observations…With minimal requirements for execution, MINJA enables any user to influence agent memory."
[^24^]: How Memories are Transferred Across Domains in Coding Agents (Memory Transfer Learning), arXiv:2604.14004, 2026-04-15。https://arxiv.org/abs/2604.14004 。摘录："Domain-mismatched anchoring…False validation confidence: Verification memories can create a false sense of certainty. This leads to self-confirming loops…Misapplied best-practice transfer…low-abstraction memories like Trajectories retain excessive task-specific details that can distract the agent."
[^25^]: When Continual Learning Moves to Memory: A Study of Experience Reuse in LLM Agents（综述 Moonlight, 2026-05-01）。https://www.themoonlight.io/en/review/when-continual-learning-moves-to-memory-a-study-of-experience-reuse-in-llm-agents 。摘录："Raw memory consistently produced negative FWT…Insight memory, however, yielded positive FWT…in ALFWorld A→B with Raw memory, ΔRR was slightly positive (+4.6), but ΔNL was severely negative (-26.1)."
[^26^]: MemX: A Local-First Long-Term Memory System for AI Assistants, arXiv:2603.16171, 2026-03-17。https://arxiv.org/abs/2603.16171 。摘录："vector recall, keyword recall, Reciprocal Rank Fusion (RRF), four-factor re-ranking, and a low-confidence rejection rule that suppresses spurious recalls when no answer exists in the memory store."
[^27^]: 多粒度记忆系统消融（arXiv:2601.20352v3）。https://pdfs.assets.alphaxiv.org/2601.20352v3.pdf 。摘录："enabling the Refresher substantially improves performance on knowledge-update scenarios in LongMemEval, achieving an accuracy of 0.897. In contrast, removing the Refresher leads to a sharp drop to 0.568."
[^28^]: Truth-maintained memory agent: Proactive quality control for reliable long-context dialogue, NeurIPS 2025（经 MemDelta arXiv:2606.29914 参考文献确认）。
[^29^]: Evaluating Very Long-Term Conversational Memory of LLM Agents (LoCoMo), ACL 2024。https://aclanthology.org/2024.acl-long.747/ 。摘录："LoCoMo, a dataset of very long-term conversations, each encompassing 600 turns and 16K tokens on avg., over up to 32 sessions…question answering, event summarization, and multi-modal dialogue generation."
[^30^]: LoCoMo 五类问题描述（arXiv:2602.14038 附录）。摘录："Single-hop…Multi-hop…Temporal…Open-domain…Adversarial: intentionally crafted to trigger hallucinations; the desired behavior is to recognize the question as unanswerable."
[^31^]: MemoryBench: A Benchmark for Memory and Continual Learning in LLM Systems, arXiv:2510.17281, 2025-10。https://arxiv.org/html/2510.17281v5 。摘录："the framework consists of three modules: Task Provider, User Simulator, and Performance Monitor…feedback logs S are the main resources for the LLMsys to build its declarative and procedural memory."
[^32^]: 记忆基准格局综述（arXiv:2603.07670）。https://arxiv.org/pdf/2603.07670 。摘录："MemoryAgentBench grounds evaluation in cognitive science, probing four competencies: accurate retrieval, test-time learning, long-range understanding, and selective forgetting…most fail conspicuously on selective forgetting…models that score near-perfectly on LoCoMo plummet to 40-60% in MemoryArena, exposing a deep gap between passive recall and active, decision-relevant memory use."
[^33^]: Evo-Memory: Benchmarking LLM Agent Test-time Learning with Self-Evolving Memory, arXiv:2511.20857, 2025-11。
[^34^]: EvoMemBench: Benchmarking Agent Memory from a Self-Evolving Perspective, arXiv:2605.18421, 2026-05；TAME: A Trustworthy Test-Time Evolution of Agent Memory, arXiv:2602.03224。
[^35^]: LoCoMo-Plus, arXiv:2602.10715, 2026-02-11。https://arxiv.org/abs/2602.10715 。摘录："conventional string-matching metrics and explicit task-type prompting are misaligned with such scenarios, and propose a unified evaluation framework based on constraint consistency."
[^36^]: Memory-R1, arXiv:2508.19828, 2025-08-27。https://arxiv.org/abs/2508.19828 。摘录："a Memory Manager that learns structured operations, including ADD, UPDATE, DELETE, and NOOP; and an Answer Agent that pre-selects and reasons over relevant entries…With only 152 training QA pairs, Memory-R1 outperforms strong baselines and generalizes across diverse question types, three benchmarks (LoCoMo, MSC, LongMemEval), and multiple model scales (3B-14B)."
[^37^]: MemSkill: Learning and Evolving Memory Skills for Self-Evolving Agents, arXiv:2602.02474, 2026-02-02（v2 2026-05）。https://arxiv.org/abs/2602.02474 。摘录："a controller that learns to select a small set of relevant skills, paired with an LLM-based executor…a designer that periodically reviews hard cases where selected skills yield incorrect or incomplete memories, and evolves the skill set by proposing refinements and new skills…we maintain snapshots of the best-performing skill bank and roll back if an update degrades performance…skill evolution is triggered every 100 training steps, with at most 3 skill edits per evolution round."
[^38^]: MemEvolve: Meta-Evolution of Agent Memory Systems, arXiv:2512.18746, 2025-12-21。https://arxiv.org/abs/2512.18746 。摘录："a meta-evolutionary framework that jointly evolves agents' experiential knowledge and their memory architecture…EvolveLab, a unified self-evolving memory codebase that distills twelve representative memory systems into a modular design space (encode, store, retrieve, manage)…improving frameworks such as SmolAgent and Flash-Searcher by up to 17.06%."
[^39^]: Memento: Fine-tuning LLM Agents without Fine-tuning LLMs, arXiv:2508.16153, 2025-08-22。https://arxiv.org/abs/2508.16153 。摘录："The policy is continually updated based on environmental feedback through a memory rewriting mechanism, whereas policy improvement is achieved through efficient memory reading (retrieval)…In the parametric setting, Write further online updates a Q-function to shape the retrieval distribution, while Read is driven by the learned Q-function…case-based memory adds 4.7% to 9.6% absolute points on out-of-distribution tasks."
[^40^]: Learning Query-Aware Budget-Tier Routing for Runtime Agent Memory, arXiv:2602.06025, 2026-02（经 arXiv:2604.08224 参考文献确认）。
[^41^]: Memory as Action: Autonomous Context Curation for Long-Horizon Agentic Tasks, arXiv:2510.12635, 2025-10（经 AutoMem arXiv:2607.01224 参考文献确认）。
[^42^]: MemSearcher, arXiv:2511.02805, 2025-11；MemRL: Self-Evolving Agents via Runtime Reinforcement Learning on Episodic Memory, arXiv:2601.03192, 2026-01。

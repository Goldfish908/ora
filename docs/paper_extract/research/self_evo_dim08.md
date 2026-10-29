# 维度 08：多智能体系统结构/拓扑自进化（Agent 团队构成 / 协作拓扑 / Workflow 图结构自动进化）开源方案调研

- 调研日期：2026-08-20（所有 stars 均为该日通过 shields.io/GitHub 页面查询的约数）
- 调研目标：为「Cursor + GPT + superpower skill 管理工程」场景引入 **Agent 自进化模块**，要求开源、可直接使用、支持二次开发与领域专用改进。
- 事实口径：stars / license / 最近提交时间来自 shields.io badge API 与 GitHub 页面（2026-08-20）；机制性描述来自 arXiv 原文与官方 README，均附行内引用。查不到的标注「未查到」。

## 0. 检索记录（独立检索，中英文混合）

1. `EvoAgent automatic multi-agent generation github`
2. `AgentSquare modular multi-agent system design github`
3. `GPTSwarm language agents graph topology optimization github`
4. `DyLAN dynamic LLM-agent network github`
5. `MAS-Zero multi-agent system design zero supervision arxiv github`
6. `multi-agent topology evolution github 2025`
7. `automatic multi-agent system design 2026 arxiv`
8. `多智能体 拓扑 自进化 开源`
9. `EvoAgent github code repository yuan kaitao song`
10. `AgentScope adaptive orchestration multi-agent workflow 自适应 编排`
11. `AutoGen AG2 dynamic group chat CaptainAgent agent network building`
12. `MaAS multi-agent architecture search agentic supernet github`
13. `Why Do Multi-Agent LLM Systems Fail MAST taxonomy arxiv`
14. `AFlow automating agentic workflow generation github MetaGPT stars`
15. `MAS-Zero code release github mas-design Salesforce`
16. `EvoMAC self-evolving multi-agent coding network github`
17. `ScoreFlow optimizing agentic workflow score-based preference github`
18. `MASS multi-agent system search optimizing prompts topology github`
19. `CrewAI self-improving adaptive agents training memory flow orchestration`
20. `G-Designer architecting multi-agent communication topologies graph neural networks code github`
21. `FlowReasoner reinforcing query-level meta-agents github`
22. `SwarmAgentic fully automated agentic system generation swarm intelligence github`
23. `"Multi-Agent System Search" MASS code available github`（二次检索，仍未查到官方仓库）
24. `ADAS automated design agentic systems meta agent search mechanism archive`
25. `MaSLab multi-agent software development laboratory evomac github`
26. `AgentScope ReMe memory self-evolving agentscope release 2025`
27. `CrewAI AMP ... self-improvement crew training evaluation`
28. `"A Unified and Comprehensive Codebase for LLM-based Multi-Agent Systems" github MAS-Lab repository`
29. `MAS-Zero Salesforce code "github.com" mas-design open source released`
30. `AgentDropout dynamic agent elimination token-efficient github`

另有 GitHub/shields.io 直接核验（stars、license、LICENSE 文件、last-commit）约 25 次。

## 1. 总览对比表（stars 查询日期：2026-08-20）

| 方案 | 仓库 | Stars | License | 语言 | 进化对象 | 维护状态 |
|---|---|---|---|---|---|---|
| EvoAgentX | EvoAgentX/EvoAgentX | ~3.2k | MIT | Python | prompt+工具配置+workflow 拓扑 | 活跃（最近一周内提交）[^3^] |
| ADAS | ShengranHu/ADAS | ~1.6k | Apache-2.0 | Python | 代码空间中的整个 agent 系统 | 停更（2025-01）[^9^] |
| GPTSwarm | metauto-ai/GPTSwarm | ~1k | MIT | Python | 节点 prompt + 边（agent 间拓扑） | 低频（最近提交 2026-02）[^5^] |
| AFlow | FoundationAgents/AFlow | ~580 | MIT | Python | workflow 图（MCTS 搜索） | 中频（2025-12）[^27^] |
| MaAS | bingreeky/MaAS | ~281 | **未声明** | Python | agentic supernet（按 query 采样架构） | 中频（2025-11）[^10^] |
| MASLab | MASWorks/MASLab | ~245 | **未声明** | Python | 统一 20+ MAS 方法（含 EvoMAC） | 停更（2025-07）[^24^] |
| AgentSquare | tsinghua-fib-lab/AgentSquare | ~230 | **未声明** | Python | 四类模块的进化+重组 | 中频（2025-11）[^8^] |
| DyLAN | SALT-NLP/DyLAN | ~212 | MIT | Python | agent 团队选择 + 动态通信结构 | 停更（2024-05）[^7^] |
| EvoAgent | siyuyuan/evoagent | ~169 | **未声明** | Python | 单 agent→多 agent 群体（EA 算子） | 停更（2024-10）[^6^] |
| SwarmAgentic | YaoZ720/SwarmAgenticCode | ~149 | Apache-2.0 | Python | 从零生成系统（语言化 PSO） | 中频（2025-11）[^18^] |
| FlowReasoner | sail-sg/FlowReasoner | ~145 | **未声明** | Python | query 级 MAS（R1 蒸馏+RL） | 停更（2025-05）[^19^] |
| MAS-Zero | SalesforceAIResearch/MAS-Zero | ~118 | Apache-2.0 | Python | 推理时逐实例 MAS 设计（代码生成） | 活跃（2026-06）[^11^] |
| G-Designer | yanweiyue/GDesigner | ~98 | **未声明** | Python | VGAE 生成任务自适应通信拓扑 | 停更（2024-12）[^16^] |
| AgentDropout | wangzx1219/AgentDropout | ~52 | **未声明** | Python | 邻接矩阵优化动态裁剪 agent/边 | 中频（2026-06）[^25^] |
| MASS | 官方代码**未查到** | — | — | — | 三阶段 prompt↔拓扑交替优化 | — |
| AutoGen | microsoft/autogen | ~61k | MIT | Python/.NET | CaptainAgent 运行时自适应组队 | 活跃 |
| AG2 (AutoGen 分叉) | ag2ai/ag2 | ~4.9k | Apache-2.0 | Python | 同上 | 活跃 |
| AgentScope | agentscope-ai/agentscope | ~29k | Apache-2.0 | Python | MsgHub 动态成员 + Trinity-RFT 后训练 | 活跃 |
| CrewAI | crewAIInc/crewAI | ~57k | MIT | Python | crew.train() 反馈注入，无拓扑进化 | 活跃 |

> ⚠️ 法律提示：AgentSquare、EvoAgent、MaAS、G-Designer、FlowReasoner、AgentDropout、MASLab 仓库内**没有 LICENSE 文件**（2026-08-20 逐一核验 GitHub 页面与 raw 文件均未见），按著作权惯例默认保留所有权利，二次开发/商用前需向作者确认授权。

## 2. 核心方案详评

### 2.1 EvoAgent —— 用进化算法把单 agent 自动扩展为多 agent 群体

- **仓库**：https://github.com/siyuyuan/evoagent （169 stars；无 LICENSE 文件；Python；NAACL 2025 论文）[^1^][^6^]
- **核心机制**：把已有的单专家 agent 框架作为初始个体，施加一系列进化算子（变异、交叉、选择）生成具有多样化设定的多个 agent，组成多 agent 系统：「we consider the existing agent frameworks as the initial individual and then apply a series of evolutionary operators (e.g., mutation, crossover, selection, etc.) to generate multiple agents with diverse settings」[^1^]。论文强调可泛化到任意 LLM agent 框架：「can be generalized to any LLM-based agent framework to extend them into multi-agent systems」[^1^]。
- **即插即用程度**：中低。研究脚本式代码，按任务分目录（`spp/`、`mmmu/`、`scienceworld/`、`travelplanner/`），需配置环境变量（MODEL_NAME、IND 迭代数、GROUP_NUM 种群数、SELECT_STRATEGY 等）运行 `llm_evoagent.py` 等入口脚本[^6^]。
- **二次开发入口**：进化算子与 `evaluate` 逻辑在各任务脚本内；将自有 agent（如 Cursor 工程里的 skill agent）作为「初始个体」接入，替换评估函数即可。
- **领域定制方式**：换初始个体 + 换任务评估指标；论文在 NLP、多模态（MMMU）、ScienceWorld、TravelPlanner 上验证[^6^]。
- **局限**：进化只在「agent 设定（角色 prompt 等）」层面，不进化通信拓扑；无 license；代码 2024-10 后停更；每代种群需多次 LLM 调用，成本随种群×迭代线性增长。

### 2.2 AgentSquare —— 模块化设计空间中的自动 MAS 搜索（MoLAS）

- **仓库**：https://github.com/tsinghua-fib-lab/AgentSquare （230 stars；无 LICENSE 文件；Python；ICLR 2025，清华 FIB-Lab）[^2^][^8^]
- **核心机制**：提出 Modularized LLM Agent Search (MoLAS)，把 agent 设计抽象为四个统一 IO 接口的模块——Planning、Reasoning、Tool Use、Memory；搜索框架含两个核心机制：**module evolution**（进化元提示在 prompt 层生成新模块）与 **module recombination**（用 LLM 推理搜索模块组合）；另有 in-context 代理模型（performance predictor）跳过不优设计以降成本。「average performance gain of 17.2% against best-known human designs」[^2^]。
- **即插即用程度**：较好。「This design space is also highly extensible, allowing new agentic systems to be integrated as plug-in modules」[^2^]——标准 IO 接口让已有文献中的 agent 设计可作为即插模块复用。
- **二次开发入口**：模块注册机制 + 进化元提示（meta-prompt）+ 代理评估器；四模块接口是最清晰的二开抽象。
- **领域定制方式**：把领域专用的 planning/reasoning/tool/memory 实现注册为新模块进入设计空间，搜索自动完成组合。
- **局限**：进化对象是「单 agent 的模块组合」而非严格的多 agent 通信拓扑（MaAS 论文批评其单 agent 搜索限制性能约 4%[^10^]）；无 license；搜索仍需验证集评估。

### 2.3 GPTSwarm —— 把 agent 群体建模为可优化的图

- **仓库**：https://github.com/metauto-ai/GPTSwarm （~1k stars；MIT；Python；ICML 2024 Oral，top 1.5%）[^4^][^5^]
- **核心机制**：三层图抽象——Operation↔Node、Agent↔Graph of Nodes、Swarm↔Composite Graph；**边优化**用 REINFORCE 在 DAG 空间优化 agent 间连接（邻接矩阵概率化，`max_E u_τ(G_E)`），**节点优化**基于历史反馈改写节点 prompt：「The graph connectivity (adjacency matrices) between agents can self-improve online as a task is being solved」[^4^]。CoT/ToT/Self-Consistency/Reflexion 都可表示为图并被自动重组[^4^]。
- **即插即用程度**：好。`pip install gptswarm`；三行代码起 swarm：`Swarm(["IO","IO","IO"], "gaia")`；模块划分清晰（`swarm.environment / swarm.graph / swarm.llm / swarm.memory / swarm.optimizer`）[^5^]。
- **二次开发入口**：自定义 Agent/Operation 子类 + `swarm.optimizer` 中的优化算法；Colab 教程齐全[^5^]。
- **领域定制方式**：在 `swarm.environment` 注册领域操作/工具/任务，边优化自动学习任务的最优编排。
- **局限**：G-Designer 论文指出其训练成本高：「continuously optimizes its distribution, albeit at a relatively high training cost」[^17^]；仓库主功能 2024 年定型，此后低频维护（shields 显示最近提交 2026-02）[^5^]。

### 2.4 DyLAN —— 动态 LLM-Agent 网络（团队优化 + 动态通信）

- **仓库**：https://github.com/SALT-NLP/DyLAN （212 stars；MIT；Python；ACL 2024）[^7^]
- **核心机制**：两阶段范式。Team Optimization 阶段用无监督指标 **Agent Importance Score**（基于同伴互评的传播-聚合-选择）从候选池中选出贡献最大的 agent；Task Solving 阶段 agent 在**时序前馈网络（T-FFN）**中按 query 动态交互，带推理时 agent 选择与早停机制：「DyLAN enables agents to interact for multiple rounds in a dynamic architecture with inference-time agent selection and an early-stopping mechanism」[^7^]。MMLU 特定学科上团队优化提升最高 25.0%[^7^]。
- **即插即用程度**：中低。代码以「LLM 版 MLP（LLMLP）」风格组织，按 MATH/MMLU/HumanEval 分目录脚本运行[^7^]。
- **二次开发入口**：Agent Importance Score 计算与 T-FFN 结构代码；实现被多个后续工作（MASLab、Reinforced Collaboration 等）作为基线复现，移植性已被验证[^24^]。
- **局限**：2024-05 后停更；通信结构是分层前馈的受限拓扑；团队优化阶段需要试跑成本。

### 2.5 MAS-Zero —— 零监督、推理时自进化 MAS 设计

- **仓库**：https://github.com/SalesforceAIResearch/MAS-Zero （118 stars；Apache-2.0；Python；Salesforce AI Research；项目页 https://mas-design.github.io/ 含 1000+ 已发现 MAS 设计集）[^11^][^12^][^13^]
- **核心机制**：首个**推理时**自进化框架，不需要验证集。Meta-agent 承担三角色（设计/评估/验证）：MAS-Init（以 CoT、Self-Consistency、Debate、Self-Refine 等人工策略为 building blocks）→ MAS-Evolve（把 MAS 设计表述为**代码生成**，meta-design 分解任务+提出 sub-MAS，meta-feedback 评估可解性与完备性，经验库存档迭代）→ MAS-Verify（自验证从全部候选中选答案，可动态退化为单 agent）：「the first self-evolved, inference-time framework for automatic MAS design … without requiring a validation set」[^12^][^13^]。平均准确率提升最高 16.69%（reasoning）/16.66%（coding）/5.45%（agentic），且处于准确率-成本 Pareto 前沿[^12^]。
- **即插即用程度**：中高。官方代码已随 v4 论文放出（「Code: https://github.com/SalesforceAIResearch/MAS-Zero」[^11^]），最近提交 2026-06，维护活跃。
- **二次开发入口**：building blocks 集合（可增删策略）、meta-feedback 提示、经验库；支持闭源与开源 backbone（GPT-4o、32B、70B）[^12^]。
- **领域定制方式**：向 building blocks 注入领域策略/工具；约束集合 `{M(i)}` 可限定可用架构[^12^]。
- **局限**：推理时 meta 迭代增加 token 消耗（论文自认「incurs higher token usage during testing」[^12^]）；自验证在无客观答案的开放域可靠性下降。

### 2.6 ADAS / Meta Agent Search —— 代码空间中的 agent 自动发明

- **仓库**：https://github.com/ShengranHu/ADAS （~1.6k stars；Apache-2.0；Python；ICLR 2025，NeurIPS 2024 Open-World Agent Workshop Outstanding Paper）[^9^]
- **核心机制**：meta agent 以**代码**（一个 `forward()` 函数）定义整个 agentic 系统，基于不断增长的「发现存档（archive）」迭代编程出新 agent，评估-入档-再生成，理论上可表达任意 prompt/工具/控制流组合：「agents can be defined in code and new agents can be automatically discovered by a meta agent programming ever better ones in code」[^14^]。DROP F1 +13.6、MGSM +14.4%，且跨域/跨模型迁移性强[^14^]。
- **即插即用程度**：中。每个 domain 一个自包含文件夹，入口 `python {DOMAIN}/search.py`[^9^]。
- **二次开发入口**：README 明确给出新领域适配四步：改 `evaluate_forward_fn()`、给 meta agent 加基础函数、改 prompt 中的领域信息、跑搜索[^9^]。
- **领域定制方式**：自定义评估函数 + 领域基础函数库。
- **局限**：2025-01 后停更；**执行 LLM 生成的不可信代码**，README 明确安全警告[^9^]；搜索需大量验证集评估；被发现系统复杂度高、可读性差。

### 2.7 EvoAgentX —— 工程化程度最高的自进化 workflow 平台 ★推荐底座

- **仓库**：https://github.com/EvoAgentX/EvoAgentX （~3.2k stars；MIT；Python；arXiv 2507.03616）[^3^][^15^]
- **核心机制**：五层架构（basic components / agent / workflow / **evolving** / evaluation）。evolving 层集成 TextGrad、AFlow、MIPRO（README 另列 EvoPrompt），迭代优化 agent prompt、工具配置与 **workflow 拓扑**[^15^]。`WorkFlowGenerator` 从一句自然语言目标自动生成多 agent workflow 图[^3^]。HotPotQA F1 +7.44、MBPP pass@1 +10、MATH +10、GAIA 最高 +20%[^15^]。
- **即插即用程度**：**最高**。`pip install evoagentx`；LiteLLM/OpenRouter 接入任意模型；内置工具库（代码解释器、搜索、数据库、浏览器、MCP 工具）；支持 workflow 图可视化/存取、HITL 人在环审批、长短期记忆[^3^]。
- **二次开发入口**：优化器插件化（roadmap 明确「Modularize Evolution Algorithms … plug-and-play modules」[^3^]）；`SequentialWorkFlowGraph` / 自定义优化器类；欢迎 PR 新算法[^3^]。
- **领域定制方式**：自带 benchmark 与标准化评估，可用自有数据集驱动进化；可把既有开源 MAS（Open Deep Research、OWL）接入做 prompt+拓扑优化[^15^]。
- **局限**：进化算法是「离线优化 + 静态部署」模式（AFlow/MCTS 类），不是在线持续进化；进化需要带标准答案的验证集；社区规模仍小于 AutoGen/CrewAI。

### 2.8 AFlow —— MCTS 搜索 agentic workflow 图

- **仓库**：https://github.com/FoundationAgents/AFlow （~580 stars；MIT；Python；ICLR 2025；MetaGPT 团队）[^27^]
- **核心机制**：把 workflow 表示为代码（节点=LLM 调用，边=调用关系），用**蒙特卡洛树搜索**在预定义算子集（AnswerGenerate、Custom、Ensemble、Review&Revise、Programmer、ScEnsemble 等）上扩展/评估/回传，自动发现优于人工设计的 workflow。
- **即插即用/二开**：被 EvoAgentX 与 MASLab 双双内置为优化算法，工程接入路径成熟[^3^][^24^]；算子集可直接扩充领域算子。
- **局限**：需验证集与多轮 rollout，成本较高；搜索空间受预定义算子约束（MASS 论文的批评点[^20^]）。

### 2.9 MaAS —— Agentic Supernet，按 query 采样专属架构

- **仓库**：https://github.com/bingreeky/MaAS （281 stars；无 LICENSE 文件；Python；ICML 2025）[^10^]
- **核心机制**：不追求单一最优系统，而是优化一个**概率化的 agentic supernet**（架构的连续分布），对每个 query 采样难度/领域适配的 agentic 系统：「requires only 6~45% of the inference costs of existing handcrafted or automated multi-agent systems, (II) surpasses them by 0.54%~11.82%, (III) enjoys superior cross-dataset and cross-LLM-backbone transferability」[^10^]。
- **二开/定制**：operator 图 + supernet 控制器；适合「成本敏感、query 难度差异大」的领域。
- **局限**：无 license；训练 supernet 本身需多轮评估；2025-11 后低维护。

### 2.10 G-Designer —— 用 VGAE 生成任务自适应通信拓扑

- **仓库**：https://github.com/yanweiyue/GDesigner （98 stars；无 LICENSE 文件；Python；ICML 2025）[^16^][^17^]
- **核心机制**：把 MAS 建模为 multi-agent network，用**变分图自编码器**编码 agent 节点 + 任务虚拟节点，解码出任务自适应通信拓扑；MMLU 84.50%、HumanEval pass@1 89.90%，HumanEval token 消耗最多降 95.33%，对抗攻击下仅 0.3% 精度下降[^16^]。
- **局限**：需要训练图自编码器（非纯推理时方法）；2024-12 后停更；无 license。

### 2.11 EvoMAC —— 面向软件开发的「文本反向传播」自进化协作网络

- **代码**：官方实现并入 **MASLab**（https://github.com/MASWorks/MASLab ，245 stars，无 LICENSE 文件）；rSDE-Bench 基准仓库 https://github.com/yuzhu-cai/rSDE-Bench （37 stars，Apache-2.0）[^23^][^24^]
- **核心机制**：仿神经网络训练——coding team 前馈生成代码，testing team 生成单元测试作为 target proxy，编译器执行产生文本环境反馈，updating team 用 **textual back-propagation** 同时更新「agent prompt 与 agent 间连接」：「enabling both agents and their connections to dynamically evolve during test-time for each given task」[^23^]。与工程场景（代码生成/审查 loop）高度契合。
- **局限**：依赖「可自动验证」的环境（编译器/单测）；无独立易用包，需经 MASLab 使用。

### 2.12 SwarmAgentic —— 语言化 PSO 从零生成整个 agent 系统

- **仓库**：https://github.com/YaoZ720/SwarmAgenticCode （149 stars；Apache-2.0；Python；EMNLP 2025）[^18^]
- **核心机制**：只需任务描述+目标函数，从零生成 agent 角色/职责/协作策略的候选种群，以**粒子群优化（PSO）为蓝本的语言化进化**（Failure-Aware Velocity：个人最优+全局最优+失败归因调整），迭代执行-诊断-更新：「achieving a +261.8% relative improvement over ADAS on the TravelPlanner benchmark」[^18^]。
- **二开/定制**：README 提供「Extending to New Domains」章节；种群、速度更新、失败分析 LLM 都可替换[^18^]。
- **局限**：种群×迭代×执行的 LLM 调用量大；评估需可量化目标函数。

### 2.13 FlowReasoner —— RL 训练的 query 级 meta-agent

- **仓库**：https://github.com/sail-sg/FlowReasoner （145 stars；无 LICENSE 文件；Python；Sea AI Lab）[^19^]
- **核心机制**：蒸馏 DeepSeek-R1 获得「生成 MAS 的推理能力」，再用外部执行反馈做 RL（性能/复杂度/效率多目标奖励），实现**每个 query 生成一个专属 MAS**；三基准平均超 o1-mini 10.52%[^19^]。
- **局限**：依赖 MetaGPT 代码栈 + A100 级 GPU 训练环境；无 license；2025-05 后停更；复现 RL 训练门槛高。

### 2.14 MASS —— prompt 与拓扑交替三阶段优化（代码未查到）

- arXiv 2502.02533（v2 2026-01）。先实证分析设计空间（prompt 影响大、有效拓扑仅占小比例），再提出三阶段：① block 级 prompt 优化（MIPRO）→ ② 剪枝拓扑空间中的 workflow 拓扑优化（influence 加权采样+拒绝采样）→ ③ workflow 级全局 prompt 优化[^20^]。**官方代码仓库经两次独立检索未查到**；其「先优化 prompt 再搜拓扑」的分阶段思想可作为自行实现的蓝本。

### 2.15 AgentDropout —— 动态裁剪冗余 agent 与通信边

- **仓库**：https://github.com/wangzx1219/AgentDropout （52 stars；无 LICENSE 文件；Python；ACL 2025）[^25^]
- **核心机制**：借鉴「高效团队角色动态调整」的管理学思想，优化通信图**邻接矩阵**，逐轮剔除冗余 agent（node dropout）与通信（edge dropout）：prompt token 平均 -21.6%、completion token -18.4%，性能 +1.14[^25^]。是「拓扑瘦身/降本」方向的补充件，可与任何生成式方法叠加。
- **局限**：作者自认「remains constrained by predefined agent roles and prompts」「token consumption remains relatively high」[^25^]。

### 2.16 MASLab —— 20+ MAS 方法统一代码库（横向评测/二开底座）

- **仓库**：https://github.com/MASWorks/MASLab （245 stars；无 LICENSE 文件；Python；上交/上海 AI Lab 等）[^24^]
- **价值**：统一实现并人工逐步校验了 20+ 方法（AutoGen、AgentVerse、LLM-Debate、GPTSwarm、DyLAN、EvoMAC、ChatDev、MetaGPT、MapCoder、OWL 等），10+ benchmark、8 个模型公平对比[^24^]。适合做**选型评估与二次开发底座**——在一个代码风格下对比多种拓扑进化方法，再把优胜者接到自有工程。
- **局限**：2025-07 后停更；无 license。

## 3. 通用框架中的自适应/自进化编排能力

### 3.1 AutoGen / AG2 —— CaptainAgent 运行时自适应组队

- microsoft/autogen（~61k stars，MIT）；分叉 ag2ai/ag2（~4.9k stars，Apache-2.0）。
- **CaptainAgent**：「an agent equipped with the capability to adaptively assemble a team of agents through retrieval-selection-generation process」——分解任务→为子任务推荐角色→从 agent 库检索/从零生成 agent→从工具库配工具→nested chat 协同→总结反思并决定是否调整团队，循环直至解决[^21^][^22^]。`pip install ag2[openai,captainagent]` 即用，支持自定义 expert library / tool library[^21^]。
- **评价**：这是「团队构成」层面的运行时自适应（组队），但**不做拓扑/结构的离线进化优化**；适合直接嵌入工程，配合 MAS-Zero/EvoAgentX 的离线进化形成互补。

### 3.2 AgentScope —— 动态消息中心 + RL 后训练生态

- agentscope-ai/agentscope（~29k stars，Apache-2.0；阿里/ModelScope）。
- 编排能力：`MsgHub` 发布-订阅消息中心支持**运行时动态增删参与者**（`hub.add(new_agent)`/`hub.delete(agent2)`）与手动广播控制；`sequential_pipeline`/`fanout_pipeline` 组合串并行[^26^]。Java 版提供 Pipeline/Routing/Skills/Subagents/Supervisor 五种多 agent 模式[^28^]。
- 进化生态：2025-11 起集成 **Trinity-RFT**（agentic RL 后训练，modelscope/Trinity-RFT，690 stars，Apache-2.0）与 **ReMe** 长期记忆（agentscope-ai/ReMe，Apache-2.0，定位「local-first, self-evolving personal knowledge base」）[^29^][^30^][^31^]。
- **评价**：框架本身**没有内置拓扑自动搜索**；其「进化」走的是 RL 后训练 + 记忆路线（权重/经验层），与本维度「结构自进化」正交，可作为生产部署层与 Trinity-RFT 联用。

### 3.3 CrewAI —— 仅反馈注入式「训练」，无结构进化

- crewAIInc/crewAI（~57k stars，MIT）。
- `crew.train()` 收集人工反馈存 pickle，下次运行注入 system prompt；`crew.test()`/`TaskEvaluator` 仅记录评估信息——社区讨论证实「mostly set up to collect data and log results without doing much with them afterward」[^32^]。
- **评价**：无团队构成/拓扑的自动进化能力；若主工程已用 CrewAI，自进化模块需外接（如 EvoAgentX 优化其 crew 的 prompt 与流程）。

## 4. 局限性与风险（跨方案）

1. **成本爆炸**：自动设计本质是「评估密集型搜索」。MaAS 论文的成本表显示：MATH 上 DyLAN 训练阶段 3816 万 token / $13.01，AFlow 6288 万 token / $22.50，GPTSwarm $7.02；即便最省的 MaAS 训练也需 $3.38 + 每 query 推理采样[^10^]。PSO/EA 类（SwarmAgentic、EvoAgent）种群×迭代×评估次数同样线性放大调用量；MAS-Zero 把成本转移到推理时，「incurs higher token usage during testing」[^12^]。对策：用 MaAS 的按难度分配、AgentDropout 的拓扑瘦身、G-Designer 的 token 感知目标（token -95.33%[^16^]）。
2. **协调失败模式**：Berkeley MAST（arXiv 2503.13657，1600+ 标注轨迹、14 种失败模式 3 大类）——(i) 规范与系统设计失败（违反任务/角色规范、步骤重复、丢失历史、不知终止条件）；(ii) agent 间错位（对话重置、不澄清、任务跑偏、信息隐瞒、无视他人输入、推理-动作不一致）；(iii) 验证与终止失败[^33^][^34^]。关键结论：「improvements in the base model capabilities will be insufficient … good MAS design requires organizational understanding; even organizations of sophisticated individuals can fail catastrophically if the organization structure is flawed」[^34^]；简单的 prompt/编排干预只带来 +14% 且不足以生产部署[^33^]。**含义：结构自进化有价值，但搜索到的结构必须配验证器与终止条件，否则失败模式照样出现。**
3. **评估依赖**：除 MAS-Zero（自验证）与 EvoMAC（编译器/单测）外，绝大多数方法需要带标准答案的验证集或量化目标函数；开放域（如工程管理、文档写作）评估信号弱，进化容易过拟合代理指标。
4. **安全**：ADAS/SwarmAgentic/MAS-Zero 一类「MAS-as-code」方法会执行 LLM 生成的不可信代码，ADAS README 有明确破坏性风险警告[^9^]；工程接入必须沙箱化。
5. **许可证**：7 个关键仓库无 LICENSE（见 §1 表），直接二次开发/商用存在法律风险；优先选 MIT/Apache-2.0 的 EvoAgentX、ADAS、MAS-Zero、GPTSwarm、DyLAN、AFlow、SwarmAgentic。
6. **维护断层**：DyLAN、G-Designer、ADAS、EvoAgent、MASLab 已停更半年以上；研究代码 API 固化在老模型接口，迁移新模型需自行适配（MASLab 的复现笔记记录了 LLM-Debate 官方代码「not readily executable」等问题[^24^]）。
7. **多 agent 不一定优于单 agent**：MAST 指出 MAS 相比单 agent/best-of-N 收益常常甚微[^33^]；MAS-Zero 也观察到简单系统经常很强，因此其「动态退化为简单系统」能力是重要设计原则[^12^]。

## 5. 针对「Cursor + GPT + superpower skill 工程」的选型建议

1. **底座（即插即用 + 二开）**：EvoAgentX（MIT、pip 装、活跃维护、HITL、工具/MCP 齐全）——把现有 skill 封装为其 workflow/agent 节点，用 AFlow/TextGrad 优化器离线进化 prompt+拓扑。
2. **推理时自适应层**：MAS-Zero（Apache-2.0、活跃）——无需验证集，逐任务实例设计/退化 MAS，适合开放域工程任务。
3. **运行时组队**：AG2 CaptainAgent——从 agent 库检索+生成团队，适合与 Cursor 中已有 skill 库对接。
4. **算法参考/实验场**：AgentSquare（模块 IO 抽象）、ADAS（代码空间 meta search）、MASLab（20+ 方法横评底座，先跑对比再选型）。
5. **降本件**：AgentDropout / MaAS 思想（按 query 难度分配算力 + 拓扑剪枝），防止自进化带来的成本爆炸。
6. **部署层**：AgentScope（生产编排）+ Trinity-RFT（后续权重层进化）作为长期演进方向。

## 6. 引用来源

[^1^]: Yuan, S. et al. "EvoAgent: Towards Automatic Multi-Agent Generation via Evolutionary Algorithms", NAACL 2025, arXiv:2406.14228. 摘录：「we introduce EVOAGENT, a generic method to automatically extend specialized agents to multi-agent systems via the evolutionary algorithm」「mutation, crossover, selection, etc.」「can be generalized to any LLM-based agent framework」。https://aclanthology.org/2025.naacl-long.315/ （访问 2026-08-20）
[^2^]: Shang, Y., Li, Y. et al. "Automatic LLM Agent Search in Modular Design Space"（AgentSquare）, arXiv:2410.06153, 2024-10-08. 摘录：「four fundamental modules with uniform IO interface: Planning, Reasoning, Tool Use, and Memory」「module evolution and recombination」「average performance gain of 17.2% against best-known human designs」「allowing new agentic systems to be integrated as plug-in modules」。https://arxiv.org/html/2410.06153v1 （访问 2026-08-20）
[^3^]: EvoAgentX GitHub README. 摘录：「Self-Evolution Engine … improves workflows using self-evolving algorithms」「Source code in this repository is made available under the MIT License」「[July 2025] 1,000 Stars Reached!」；EvoAgentX Talk 日志更新至 2026-06-07。https://github.com/EvoAgentX/EvoAgentX （访问 2026-08-20；stars≈3.2k、last-commit「last friday」来自 shields.io）
[^4^]: Zhuge, M. et al. "GPTSwarm: Language Agents as Optimizable Graphs", ICML 2024, arXiv:2402.16823. 摘录：「The graph connectivity (adjacency matrices) between agents can self-improve online」「We develop optimization methods for nodes and edges, enabling automatic improvements of agent prompts and inter-agent orchestration」。https://arxiv.org/html/2402.16823v3 （2024-08-22，访问 2026-08-20）
[^5^]: GPTSwarm GitHub README. 摘录：「It lets you build LLM-based agents from graphs. It enables the customized and automatic self-organization of agent swarms」「pip install gptswarm」；模块表 swarm.environment/graph/llm/memory/optimizer；LICENSE 为 MIT（raw LICENSE 核验）。https://github.com/metauto-ai/GPTSwarm （访问 2026-08-20；stars≈1k、last-commit「february」来自 shields.io）
[^6^]: siyuyuan/evoagent GitHub README. 摘录：运行命令 `python3 llm_evoagent.py --method evoagent --ind $IND`、TravelPlanner 脚本含 `GROUP_NUM`、`SELECT_STRATEGY`、`STRATEGY=evoagent`。https://github.com/siyuyuan/evoagent （2024-05-15 起，访问 2026-08-20；stars=169、无 LICENSE 文件、last-commit 2024-10，shields.io 核验）
[^7^]: SALT-NLP/DyLAN GitHub README 与论文 arXiv:2310.02170. 摘录：「DyLAN enables agents to interact for multiple rounds in a dynamic architecture with inference-time agent selection and an early-stopping mechanism」「an unsupervised metric termed Agent Importance Score」「agent team optimization in DyLAN increases accuracy by up to 25.0%」。https://github.com/SALT-NLP/DyLAN ；https://arxiv.org/html/2310.02170v2 （访问 2026-08-20；stars=212、MIT、last-commit 2024-05，shields.io 核验）
[^8^]: AgentSquare 仓库 https://github.com/tsinghua-fib-lab/AgentSquare （stars=230、无 LICENSE 文件、last-commit 2025-11，shields.io 核验 2026-08-20）
[^9^]: ShengranHu/ADAS GitHub README. 摘录：「a "meta" agent iteratively programs interesting new agents in code based on previous discoveries」；新领域适配四步（改 `evaluate_forward_fn()` 等）；安全警告「involves executing untrusted model-generated code … such code may still act destructively」。https://github.com/ShengranHu/ADAS （访问 2026-08-20；stars≈1.6k、Apache-2.0、last-commit 2025-01，shields.io 核验）
[^10^]: Zhang, G. et al. "Multi-agent Architecture Search via Agentic Supernet"（MaAS）, arXiv:2502.04180. 摘录：「optimizing the agentic supernet, a probabilistic and continuous distribution of agentic architectures」「requires only 6~45% of the inference costs … surpasses them by 0.54%~11.82%」；成本表：DyLAN 训练 $13.01、AFlow $22.50、GPTSwarm $7.02；「AgentSquare's … limitation to a single-agent search … 4% drop compared to MaAS」。https://www.arxiv.org/pdf/2502.04180 （访问 2026-08-20；仓库 bingreeky/MaAS stars=281、无 LICENSE、last-commit 2025-11）
[^11^]: MAS-Zero v4（arXiv:2505.14996v4, 2026-03-09）. 摘录：「Code: https://github.com/SalesforceAIResearch/MAS-Zero」。https://arxiv.org/html/2505.14996v4 （访问 2026-08-20；仓库 stars=118、Apache-2.0、last-commit 2026-06，shields.io 核验）
[^12^]: Ke, Z. et al. "MAS-Zero: Designing Multi-Agent Systems with Zero Supervision". 摘录：「the first self-evolved, inference-time framework for automatic MAS design … without requiring a validation set」「up to 16.69% on reasoning, 16.66% on coding, and 5.45% on agentic tasks」「incurs higher token usage during testing」。https://arxiv.org/html/2505.14996v3 （2025-12-01，访问 2026-08-20）
[^13^]: MAS-Zero 项目页. 摘录：「no validation set needed; Meta-level self-supervision on MAS design; Inference-time only」「1,000+ Discovered MAS Designs」。https://mas-design.github.io/ （访问 2026-08-20）
[^14^]: Hu, S., Lu, C., Clune, J. "Automated Design of Agentic Systems", ICLR 2025, arXiv:2408.08435. 摘录：「agents can be defined in code and new agents can be automatically discovered by a meta agent programming ever better ones in code」「improve F1 scores on … DROP by 13.6/100 and accuracy rates on … MGSM by 14.4%」。https://arxiv.org/abs/2408.08435 （访问 2026-08-20）
[^15^]: Wang, Y. et al. "EvoAgentX: An Automated Framework for Evolving Agentic Workflows", arXiv:2507.03616. 摘录：「integrates three MAS optimization algorithms, TextGrad, AFlow, and MIPRO, to iteratively refine agent prompts, tool configurations, and workflow topologies」「7.44% increase in HotPotQA F1, 10.00% … MBPP … 20.00% on GAIA」。https://arxiv.org/html/2507.03616 （访问 2026-08-20）
[^16^]: Zhang, G. et al. "G-Designer: Architecting Multi-agent Communication Topologies via Graph Neural Networks", ICML 2025 (PMLR 267). 摘录：「leveraging a variational graph auto-encoder … decodes a task-adaptive and high-performing communication topology」「reducing token consumption by up to 95.33% on HumanEval」「The code is available at https://github.com/yanweiyue/GDesigner」。https://proceedings.mlr.press/v267/zhang25cu.html （2025-10-06，访问 2026-08-20；仓库 stars=98、无 LICENSE、last-commit 2024-12）
[^17^]: G-Designer 论文 arXiv:2410.11782 相关工作. 摘录：「GPTSwarm conceptualizes a swarm of LLM agents as computational graphs and continuously optimizes its distribution, albeit at a relatively high training cost」。https://arxiv.org/pdf/2410.11782 （访问 2026-08-20）
[^18^]: SwarmAgentic 官方仓库 YaoZ720/SwarmAgenticCode 与论文 arXiv:2506.15672（EMNLP 2025）. 摘录：「maintains a population of candidate systems and evolves them via feedback-guided updates, drawing inspiration from Particle Swarm Optimization」「a +261.8% relative improvement over ADAS on the TravelPlanner benchmark」。https://github.com/YaoZ720/SwarmAgenticCode ；https://yaoz720.github.io/SwarmAgentic/ （访问 2026-08-20；stars=149、Apache-2.0、last-commit 2025-11）
[^19^]: Gao, H. et al. "FlowReasoner: Reinforcing Query-Level Meta-Agents", arXiv:2504.15257. 摘录：「one system per user query」「by distilling DeepSeek R1 … enhance it via reinforcement learning (RL) with external execution feedback」「surpasses o1-mini by 10.52% accuracy」「The code is available at https://github.com/sail-sg/FlowReasoner」；README：「We follow the MetaGPT to install … All experiments are conducted on NVIDIA A100 GPUs」。https://arxiv.org/html/2504.15257v1 ；https://github.com/sail-sg/FlowReasoner （2025-04-21，访问 2026-08-20；stars=145、无 LICENSE、last-commit 2025-05）
[^20^]: Zhou, H. et al. "Multi-Agent Design: Optimizing Agents with Better Prompts and Topologies"（MASS）, arXiv:2502.02533（v2 2026-01-31）. 摘录：「1) block-level (local) prompt 'warm-up' … 2) workflow topology optimization in a pruned set of topology space; 3) workflow-level (global) prompt optimization」「influential topologies only represent a small fraction of the full search space」。https://arxiv.org/abs/2502.02533 （访问 2026-08-20；官方代码两次独立检索**未查到**）
[^21^]: AG2 官方文档「Introducing CaptainAgent for Adaptive Team Building」. 摘录：「adaptively assemble a team of agents through retrieval-selection-generation process」「Step 1 … recommend several roles … generated from scratch or retrieved and selected from an agent library … equipped with predefined tools retrieved from a tool library」「pip install -U ag2[openai,captainagent]」。https://docs.ag2.ai/latest/docs/blog/2024/11/15/CaptainAgent/ （访问 2026-08-20）
[^22^]: Song, L. et al. "Adaptive In-conversation Team Building for Language Model Agents", arXiv:2405.19425（AG2 CaptainAgent 论文引用信息，见 AG2 文档页）。https://arxiv.org/abs/2405.19425 （访问 2026-08-20）
[^23^]: Hu, Y., Cai, Y. et al. "Self-Evolving Multi-Agent Collaboration Networks for Software Development"（EvoMAC）, arXiv:2410.16946. 摘录：「enabling both agents and their connections to dynamically evolve during test-time for each given task」「obtains text-based environmental feedback … leverages a novel textual back-propagation to update the MAC network」。https://arxiv.org/html/2410.16946 （2024-10-22，访问 2026-08-20）
[^24^]: Huang, K. et al. "MASLab: A Unified and Comprehensive Codebase for LLM-based Multi-Agent Systems", arXiv:2505.16988. 摘录：「integrates over 20 established methods across multiple domains, each rigorously validated」「MASLab: https://github.com/MASWorks/MASLab」「EvoMAC … We collaborate with the authors of EvoMAC, who provide their official implementation to be integrated into our framework」；LLM-Debate 官方代码「not readily executable」。https://arxiv.org/html/2505.16988v2 （2026-06-12，访问 2026-08-20；仓库 stars=245、无 LICENSE、last-commit 2025-07）
[^25^]: Wang, Z. et al. "AgentDropout: Dynamic Agent Elimination …", ACL 2025. 摘录：「optimizing the adjacency matrices of the communication graphs and eliminates them」「average reduction of 21.6% in prompt token consumption and 18.4% in completion token consumption」「We release our code at https://github.com/wangzx1219/AgentDropout」。https://aclanthology.org/2025.acl-long.1170/ （访问 2026-08-20；stars=52、无 LICENSE、last-commit 2026-06）
[^26^]: AgentScope MsgHub/pipeline 实践文档（CSDN，2025-09-01）. 摘录：「hub.add(new_agent)」「hub.delete(agent2)」「enable_auto_broadcast」。https://blog.csdn.net/gitblog_00497/article/details/151071895 （访问 2026-08-20）
[^27^]: FoundationAgents/AFlow 仓库（MetaGPT 团队官方 AFlow 实现；stars≈580、MIT、last-commit 2025-12，shields.io 核验 2026-08-20）。https://github.com/FoundationAgents/AFlow ；论文 arXiv:2410.10762（ICLR 2025，MCTS workflow 搜索，被 EvoAgentX/MASLab 内置）
[^28^]: AgentScope Java 官方文档「多智能体概览」. 摘录：模式表「Pipeline / Routing / Skills / Subagents / Supervisor」。https://java.agentscope.io/v1/zh/docs/multi-agent/overview.html （2026-06-02，访问 2026-08-20）
[^29^]: agentscope-ai/agentscope README News. 摘录：「[2025-11] 集成: 通过 Trinity-RFT 库实现智能体强化学习」「[2025-11] 集成: ReMe 增强长期记忆」「[2026-02] 支持实时语音交互」。https://github.com/agentscope-ai/agentscope （访问 2026-08-20；stars≈29k、Apache-2.0）
[^30^]: AgentScope Discussion #898（2025-11-04）. 摘录：「Agentic RL Support: Fine-tune agentic workflows built with AgentScope using Trinity-RFT with minimal code changes」。https://github.com/agentscope-ai/agentscope/discussions/898 （访问 2026-08-20）
[^31^]: agentscope-ai/ReMe README. 摘录：「A local-first, self-evolving personal knowledge base for AI agents」「本项目基于 Apache License 2.0 开源」。https://github.com/agentscope-ai/ReMe （访问 2026-08-20）
[^32^]: CrewAI 社区论坛「How does training & evaluation actually work in CrewAI?」（2024-11-12）. 摘录：「crew.train() … capture that feedback and store in a pickle file. And then the next time it runs, it will Inject that file into your system prompts」「it's mostly set up to collect data and log results without doing much with them afterward」。https://community.crewai.com/t/how-does-training-evaluation-actually-work-in-crewai/1341 （访问 2026-08-20）
[^33^]: Cemri, M. et al. "Why Do Multi-Agent LLM Systems Fail?"（MAST）, arXiv:2503.13657. 摘录：「14 unique failure modes … 3 categories: (i) specification and system design failures, (ii) inter-agent misalignment, and (iii) task verification and termination」「interventions yield a +14% improvement for ChatDev, they do not resolve all failure cases」「performance gains across popular benchmarks remain minimal compared to single-agent frameworks」。https://arxiv.org/abs/2503.13657 （2025-03-17，访问 2026-08-20；代码 github.com/multi-agent-systems-failure-taxonomy/MASFT）
[^34^]: MAST 论文（经 arXiv:2601.22290 转引）. 摘录：「improvements in the base model capabilities will be insufficient to address the full taxonomy. Instead, good MAS design requires organizational understanding; even organizations of sophisticated individuals can fail catastrophically if the organization structure is flawed」。https://www.arxiv.org/pdf/2601.22290 （访问 2026-08-20）

## 7. 其他已发现但未展开的相关工作（备查）

- ScoreFlow（score-based preference optimization，arXiv 2502.04305 系列；仓库检索未确认）
- MAS-GPT（训练单模型按 query 生成 MAS）；ScoreFlow/MAS-GPT 见 OpenReview 转引[^35^]
- Assemble Your Crew（自回归图生成拓扑，AAAI 2026）；OFA-MAS（MoE 图生成，WWW 2026）；Agent Q-Mix（QMIX 式 CTDE 拓扑决策，2026）；Lemon（反事实 RL 编排，2026）——均见 arXiv 引用记录[^36^]，开源情况未逐一核实
- IBM awesome-agentic-workflow-optimization 列表（持续追踪 workflow 优化文献，含 Cut the Crap、Adaptive Graph Pruning、DAGP 等拓扑瘦身工作）[^37^]

[^35^]: OpenReview 论文（ADAS 后续工作综述段落）. 摘录：「MAS-GPT (Ye et al., 2025) and ScoreFlow (Wang et al., 2025) develop meta-agents by training a model to dynamically generate multi-agent systems for a given query」。https://openreview.net/pdf?id=cnKYqIgNy5 （访问 2026-08-20）
[^36^]: arXiv:2605.14483 / 2605.02801 参考文献. 摘录：「Assemble your crew: automatic multi-agent communication topology design via autoregressive graph generation, AAAI 2026」「OFA-mas … ACM Web Conference 2026」「Agent Q-Mix … QMIX-style CTDE for decentralized communication and topology decisions」。https://arxiv.org/html/2605.14483v1 （2026-05-14，访问 2026-08-20）
[^37^]: IBM/awesome-agentic-workflow-optimization GitHub 列表（2026-03-20 更新）. https://github.com/IBM/awesome-agentic-workflow-optimization （访问 2026-08-20）

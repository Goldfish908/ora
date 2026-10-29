# 维度 10：Agent 自进化领域 —— 权威综述、Awesome 列表与选型方法论调研

- 调研日期：2026-08-20（所有 stars / 仓库元数据均以该日期查询为准）
- 调研方式：21 次独立 web 搜索（中英文混合）+ GitHub 页面 / raw 文件直采 + arXiv 原文页
- 适用场景：用户在 Cursor + GPT + superpower skill 工程体系中加入"开源、可直接使用、可二次开发、可做领域专用改进"的 Agent 自进化模块

---

## 0. 关键澄清（任务背景中的一处编号混淆）

任务背景称 "A Comprehensive Survey of Self-Evolving AI Agents (arXiv:2507.21046，配套框架 EvoAgentX)"。经核实：

- **arXiv:2507.21046** 实为 Gao et al. 的 *"A Survey of Self-Evolving Agents: What, When, How, and Where to Evolve on the Path to Artificial Super Intelligence"*（UIUC / Princeton 等团队，已被 **TMLR 2026** 接收）[^1^][^2^]。
- **《A Comprehensive Survey of Self-Evolving AI Agents: A New Paradigm Bridging Foundation Models and Lifelong Agentic Systems》** 实为 **arXiv:2508.07407**（Fang, Peng, Zhang, Wang, …, Meng；Glasgow / Aberdeen / MBZUAI 团队），**这篇才是 EvoAgentX 团队出品的配套综述**，配套仓库为 `EvoAgentX/Awesome-Self-Evolving-Agents`[^3^][^4^][^5^]。
- 两篇综述均是本领域被引最广的"权威综述"，下文均纳入对比。

---

## 1. 检索记录（≥15 次独立搜索）

| # | 查询词 | 结果要点 |
|---|--------|----------|
| 1 | "A Comprehensive Survey of Self-Evolving AI Agents arXiv 2507.21046" | 命中两篇综述的交叉引用，发现编号混淆 [^1^][^3^] |
| 2 | "EvoAgentX github stars license" | 未直接命中，改用 GitHub 实页直采（见 §4） |
| 3 | "A Survey of Self-Evolving Agents What When How Where framework" | 命中 arXiv:2507.21046 v4 原文页 [^2^] |
| 4 | "XMUDeepLIT Awesome-Self-Evolving-Agents github" | 经第三方快照仓库命中 README 全文 [^6^] |
| 5 | "EvoAgentX github.com/EvoAgentX self-evolving agentic workflow framework" | 命中框架论文 arXiv:2507.03616 [^7^] |
| 6 | "awesome self-evolving agents github list" | 命中 EvoAgentX/Awesome-Self-Evolving-Agents [^8^] |
| 7 | "LLM agent harness survey 2026 arXiv" | 命中 harness 综述 2606.20683 及相关两篇 [^9^] |
| 8 | "self-evolving agents 综述 awesome 列表 github" | 0 结果（中文检索不敏感，改用英文） |
| 9 | "awesome-agent-evolution github" | 命中 Shiyao-Huang/awesome-agent-evolution [^10^] |
| 10 | "agent self-improvement production experience eval set trajectory logging" | 0 结果，换关键词重试（#16–19 成功） |
| 11 | "自进化 agent 落地 评估集 轨迹 护栏 经验" | 0 结果（中文工程类内容少） |
| 12 | "where to do agent self-evolution prompt layer memory layer skill layer cost risk" | 0 结果，改由综述 §6 taxonomy 支撑 |
| 13 | "Self-Improvements in Modern Agentic Systems survey 2026 arXiv" | 命中 arXiv:2607.13104 [^11^] |
| 14 | "LLM agent evaluation best practices trajectory grading guardrails production" | 0 结果，换关键词 |
| 15 | "Anthropic building effective agents evals feedback loops production lessons" | 0 结果，直接打开 Anthropic 工程博客 [^12^] |
| 16 | "DSPy GEPA prompt optimization production self-improving agent" | 命中 DSPy/GEPA 定位描述 [^13^] |
| 17 | "agent memory layer self-evolution mem0 skill library Voyager production" | 命中记忆/技能层演化多篇 [^14^][^15^] |
| 18 | "Hamel Husain evals LLM agent eval-driven development error analysis" | 命中 eval 方法论体系 [^16^][^17^] |
| 19 | "LangSmith agent trajectory evaluation observability best practices" | 命中观测/轨迹工程实践 [^18^][^19^] |
| 20 | "OpenAI cookbook agents guardrails production evaluation" | 命中 guardrails 定义 [^20^] |
| 21 | "自进化智能体 工程实践 经验闭环 评测集 知乎" | 0 结果 |

另：GitHub REST API 因速率限制不可用，改用 `github.com` 页面 HTML、`raw.githubusercontent.com` 与 shields.io 徽标直采元数据。

---

## 2. 权威综述 Taxonomy 对比

### 2.1 五篇核心综述总览

| 综述 | 出处 / 状态 | 核心框架 | 对工程选型的价值 |
|------|------------|----------|------------------|
| Gao et al., *A Survey of Self-Evolving Agents* | arXiv:2507.21046，TMLR 2026 [^1^][^2^] | **What / When / How (+Where) to evolve**：What=模型、记忆、工具、工作流；When=SFT / RL / 推理时演化（intra-test-time / inter-test-time）；How=标量奖励、文本反馈、单/多智能体架构 | "何时演化"（训练期 vs 推理期）的时间轴划分，是判断"先离线优化还是先在线学习"的最佳框架 |
| Fang et al., *A Comprehensive Survey of Self-Evolving AI Agents* | arXiv:2508.07407，2025-08 [^3^][^4^] | 反馈回路四要素：**System Inputs / Agent System / Environment / Optimisers**；技术分三大方向：**单智能体优化 / 多智能体优化 / 领域专用优化** | 与 EvoAgentX 同团队，taxonomy 与开源代码一一对应，做"领域专用改进"时最贴合 |
| Ren et al., *Self-Improvements in Modern Agentic Systems: A Survey* | arXiv:2607.13104，2026-07 [^11^] | Agent = 基座模型 θ + 脚手架 Σ（prompt/memory/tools/control logic）；自改进=更新算子，按**更新目标**分：模型参数改进 vs 脚手架改进（prompt / memory / tool / full scaffolding） | 最新（2026-07），"在哪一层做自进化"的最清晰形式化（见 §5.1） |
| Xiang et al.（厦大 XMUDeepLIT）, *A Systematic Survey of Self-Evolving Agents: From Model-Centric to Environment-Driven Co-Evolution* | TechRxiv 2026 [^6^] | **Model-Centric**（推理演化/训练演化）→ **Environment-Centric**（知识/经验/架构/拓扑演化）→ **Model-Environment Co-Evolution**（多智能体策略共演化、环境训练） | 强调"环境侧"（经验、技能、拓扑）演化，与个人工程增强场景吻合 |
| *A Survey on Agent System and Harness Design* | arXiv:2606.20683，2026-06 [^9^] | 演进四范式：prompt engineering → context engineering → **harness engineering** → agent-native training；harness 分解为 6 个运行时职责；"agent 性能是 model–harness 配对的属性" | 把"自进化"放进 harness 工程语境，论证不必动权重、改 harness 即可进化 |

### 2.2 Taxonomy 对照（同一概念的四种切法）

| 层（本报告统一口径） | 2507.21046 (What) | 2508.07407 (Optimiser 目标) | 2607.13104 (Update target) | XMU survey |
|---|---|---|---|---|
| Prompt 层 | Prompt/workflow 演化 | 单智能体 prompt 优化（编辑式/进化式） | Prompt-based improvement（标量反馈、定性反馈、种群进化、文本梯度）[^11^] | 推理时演化 |
| 记忆/经验层 | Memory 演化 | Memory 优化 | Memory-based improvement（存储-读取-更新-遗忘 CRUD）[^11^] | 动态经验演化（离线经验编译/在线适应/终身演化） |
| 技能/工具层 | Tool 演化 | Tool 优化（推理时/功能优化） | Tool-based improvement（迭代精炼→技能库守门）[^11^] | 技能增强演化、工具增强演化 |
| 代码/脚手架层 | Architecture/workflow 演化 | 多智能体优化（拓扑、角色） | **Full scaffolding improvement**（ADAS、DGM、Gödel Agent、Live-SWE-Agent）[^11^] | 智能体拓扑演化 |
| 权重层 | Model 演化（SFT/RL） | 模型层优化 | Foundation Model Improvement（θ 更新）[^11^] | 训练型演化（合成驱动离线/探索驱动在线） |

> 原文佐证（2607.13104 §6）："Prompt-based improvement … provides a direct way to refine task communication … without altering the internal parameters of the foundation model"；"Full scaffolding improvement represents the deepest level of architectural intervention … the agent treats its entire operational logic and codebase as a mutable substrate"[^11^]。

---

## 3. Awesome 列表对比

| 列表 | 维护方 | 规模/结构 | 特点 | 适用 |
|------|--------|-----------|------|------|
| `EvoAgentX/Awesome-Self-Evolving-Agents` [^8^] | EvoAgentX 团队（配套 2508.07407） | 论文树：**单智能体优化**（LLM/prompt/记忆/工具）、**多智能体优化**、**领域专用优化**；带"Open-Source Framework"小节（EvoAgentX、MASLab）[^8^] | 与综述同步、每条目标注会议级别和代码链接；含演化树图（2023–2025） | 按技术脉络选算法 |
| `XMUDeepLIT/Awesome-Self-Evolving-Agents` [^6^] | 厦门大学 DeepLIT（配套 TechRxiv 2026 综述） | 三层 taxonomy（Model-Centric / Environment-Centric / Co-Evolution），下设 Benchmarks、Open Source Libraries、Applications（科学发现、软件工程、开放世界） | 2026-02 发布、更新活跃（2026-03 新增 ICLR 2026 LLA workshop 工作）；热点标注 🔥 指向 exploration-driven online self-evolving、skill augmented evolution、environment training | 找最新论文和基准 |
| `Shiyao-Huang/awesome-agent-evolution` [^10^] | 独立社区（aha team） | 168–187 stars（2026-06 快照，第三方目录数据；2026-08-20 未直接复核）、MIT | **不是纯链接堆叠，而是判断框架**："先问五件事：改了什么、为什么改、谁验证、是否保留、能否回滚"；提出 **Observe → Interpret → Modify → Verify → Retain** 闭环；区分系统改的是 prompt / memory / workflow / code / weights；附 Evolve-AGI Index 证据指数原型 [^10^] | **选型判断方法论首选** |
| `luo-junyu/Awesome-Agent-Papers` [^21^] | 个人维护（配套综述 2503.21460） | ~2.7k stars（2026-05 快照） | 通用 agent 论文集，含 "Agent Evolution: Self-improvement and learning capabilities" 分类 | 补充通用 agent 背景 |

> 原文佐证（awesome-agent-evolution README）："这份 Survey 不先堆链接，而是先给判断表：一个系统到底改变了 prompt、memory、workflow、code、weights，还是只换了说法。""读项目时不要先看名字、stars 或 demo；先看它有没有 Observe -> Interpret -> Modify -> Verify -> Retain 的闭环。"[^10^]

---

## 4. EvoAgentX 深度剖析

### 4.1 基本事实卡

| 项 | 值 | 来源与查询日期 |
|---|---|---|
| 名称 | EvoAgentX — "Building a Self-Evolving Ecosystem of AI Agents" | README [^22^] |
| 仓库 URL | https://github.com/EvoAgentX/EvoAgentX | [^22^] |
| Stars | **3,242**（页面 aria-label "3242 users starred this repository"），查询日期 **2026-08-20**；shields 徽标显示 3.2k | [^23^][^24^] |
| Forks | **292**（repo-network-counter title="292"），2026-08-20 | [^23^] |
| 提交数 | 1,171 commits，2026-08-20 | [^23^] |
| License | **MIT**（LICENSE 文件头 "MIT License, Copyright (c) 2025 EvoAgentX"）——满足"开源、可二次开发、可商用"要求 | [^25^] |
| 安装 | `pip install evoagentx` 或源码 `pip install -e .`（Python 3.11） | [^22^] |
| 论文 | arXiv:2507.03616（EMNLP 2025 Demo），前身 SEW 论文 arXiv:2505.18646 | [^7^][^26^] |
| 团队 | MBZUAI / University of Aberdeen / University of Glasgow | [^7^] |
| 文档/社区 | evoagentx.org、EvoAgentX.github.io/EvoAgentX 文档、Discord | [^22^] |

### 4.2 架构：五层模块化设计

论文原文："EvoAgentX employs a modular architecture consisting of five core layers: the basic components, agent, workflow, **evolving**, and evaluation layers … the evolving layer … integrates three state-of-the-art optimization algorithms, **TextGrad, AFlow, and MIPRO**, to iteratively refine agent prompts, tool configurations, and workflow topologies."[^7^]

- **Basic component 层**：配置管理（YAML/JSON 校验）、日志、文件处理、存储（缓存/检查点）；通过 LiteLLM / OpenRouter 接入多来源 LLM [^7^]。
- **Agent / Workflow 层**：`WorkFlowGenerator` 从一句自然语言 goal 自动生成多智能体工作流；`AgentManager` 实例化 agent；`SequentialWorkFlowGraph` 等图结构可 `save_module()`/`from_file()` 持久化 [^7^][^22^]。
- **Evolving 层（核心）**：代码目录 `evoagentx/optimizers/` 下实际包含 **6 个优化器**（超出论文所述 3 个）：`textgrad_optimizer.py`、`aflow_optimizer.py`、`mipro_optimizer.py`、`sew_optimizer.py`（自研工作流进化）、`evoprompt_optimizer.py`、`map_elites_optimizer.py`，另有 `optimizer.py`/`optimizer_core.py` 抽象基类和 `example_optimizer.py` 教学样例 [^27^]。
- **Evaluation 层**：内建 benchmark（HotPotQA、MBPP、MATH、GAIA）与标准化评估指标 [^7^]。

包目录结构（2026-08-20 实采）：`actions / agents / benchmark / core / evaluators / frameworks / hitl / memory / models / optimizers / prompts / rag / storages / tools / utils / workflow` [^28^]。

### 4.3 自进化工作流（如何"进化"）

1. **Workflow 优化**：AFlow / SEW 以 Monte Carlo 树搜索或自演化方案改写工作流拓扑 + 各 agent prompt；SEW 对比了 BPMN、CoRE、Python code、YAML、伪代码五种工作流表示 [^26^]。
2. **Prompt 优化**：TextGrad（"文本梯度"反向传播到 prompt）、MIPRO（贝叶斯式指令+few-shot 联合优化）、EvoPrompt（进化算法）[^7^][^27^]。
3. **Memory 优化**：`evoagentx/memory` 支持短期（ephemeral）与长期（persistent）记忆；README 明确 "both short-term and long-term memory modules, enabling your agents to remember, reflect, and improve across interactions" [^22^]。
4. **评估闭环**：优化以"你的数据集 + 目标指标"为驱动——"automatically evolve and optimize your agentic workflows using SOTA self-evolving algorithms, **driven by your dataset and goals**" [^22^]。

论文报告的进化收益：HotPotQA F1 63.58%→71.02%（+7.44，TextGrad）；MBPP pass@1 69%→79%（+10，AFlow）；MATH 66%→76%（+10，TextGrad）；GAIA 最高 +20% [^7^]。

### 4.4 工程化能力与二次开发入口

- **模型接入**：OpenAI、Qwen（阿里云）原生；Claude/DeepSeek/Kimi 等经 LiteLLM、SiliconFlow、OpenRouter；本地模型走 LiteLLM [^22^]。
- **工具生态**：内建代码解释器（Python/Docker 沙箱）、搜索（Google/DDGS/arXiv/RSS）、文件系统、MongoDB/PostgreSQL/FAISS、图像、浏览器自动化（BrowserToolkit/BrowserUseToolkit），且 **支持 MCP 工具接入**（docs/tutorial/mcp.md）[^22^]。
- **HITL（护栏）**：`HITLManager` + `HITLInterceptorAgent`，可对指定 agent 的指定 action 做 PRE_EXECUTION 人工批准/拒绝（APPROVE_REJECT），默认关闭、显式 `activate()` 开启 [^22^]。
- **二次开发入口**（对"领域专用改进"关键）：
  - 自定义 agent：`examples/customize_agent.py`；自定义 action：`examples/action_agent.py` [^29^]；
  - 自定义优化器：继承 `optimizer.py` 抽象，参照 `example_optimizer.py` [^27^]；
  - 自定义评测：`examples/benchmark_and_evaluation.py`、`evoagentx/evaluators` [^29^][^28^]；
  - 记忆增强：`examples/agent_with_memory_action.py`；MCP agent：`examples/mcp_agent.py`；Alita 式自进化 agent：`examples/alita_agent_example.py` [^29^]。
- **嵌入现有工程的方式**：作为 Python 库 `import evoagentx` 使用，workflow 以模块文件落盘可版本化；对 Cursor+GPT 体系而言，可将 EvoAgentX 的"优化器+评测器"作为**离线进化管线**（用 eval set 驱动优化 prompt/workflow，产出物落盘后再由 Cursor skill 体系加载），而非替换现有运行时。

---

## 5. 选型方法论："在哪一层做自进化"

### 5.1 五层成本-风险-收益对照（综合 [^11^][^10^][^6^][^9^]）

| 层 | 代表技术 | 成本 | 主要风险 | 收益/时效 | 工程界共识 |
|---|---|---|---|---|---|
| **Prompt 层** | TextGrad、GEPA、MIPRO、EvoPrompt、ACE | 低（仅推理 API 调用 + eval 算力） | 低；可回滚（prompt 是文本，天然可版本化）；可能过拟合 eval 集 | 快速见效（小时级），但"短命"——模型升级后需重做 [^11^] | **起步首选**；"prompt 优化是不动参数就能精炼任务沟通的直接方式" [^11^] |
| **记忆/经验层** | Reflexion、ExpeL、Mem0、ReasoningBank、Agent Workflow Memory | 低-中（存储 + 检索基础设施） | 中：错误经验被固化会反复污染后续行为（"memory decay / 记忆腐烂"）；检索噪声直接带崩规划 [^11^][^15^] | 跨会话累积，个人工程场景收益大 | 需要 CRUD 生命周期治理（衰减、合并、蒸馏）；Mem0 证明可生产级 [^14^] |
| **技能/工具层** | Voyager 技能库、CREATOR、Alita、SkillWeaver | 中（执行沙箱 + 验证器） | 中-高：不可靠工具入库后"corrupt the agent's future behavior through repeated retrieval" [^11^] | 能力可复制、可迁移；沉淀为团队资产 | 入库必须有"守门"：执行验证 + 迭代精炼后才允许进入技能库 [^11^] |
| **代码/脚手架层** | ADAS、Darwin Gödel Machine、Gödel Agent、Live-SWE-Agent、Agent Symbolic Learning | 高（自我改写 + 归档 + 验收测试算力） | 高：自指修改可能破坏系统本身；必须沙箱 + 回滚 + 验收测试 [^11^] | 收益上限最高（可重组架构），逼近递归自我改进 | 目前仅宜"bounded, verifiable loops"，在人定目标和安全协议内运行 [^11^] |
| **权重层** | SFT/RL（GRPO 等）、WebRL、自蒸馏 | 最高（GPU 训练管线 + 数据） | 最高：灾难性遗忘、奖励黑客、不可快速回滚 | 能力内化最彻底，但迭代周期以周计 | 团队无训练基础设施时不建议；个人工程场景几乎不适用 |

### 5.2 判断"是否真自进化"的五问（awesome-agent-evolution）[^10^]

1. **改了什么**（prompt / memory / workflow / code / weights，还是只换了说法）；
2. **为什么改**（驱动信号：标量奖励 / 文本反馈 / 执行结果）；
3. **谁验证**（验收测试 / LLM judge / 人工）；
4. **是否保留**（更新是否持久化、跨会话生效）；
5. **能否回滚**（版本化与撤销机制）。
并检查系统是否具备 **Observe → Interpret → Modify → Verify → Retain** 完整闭环 [^10^]。

### 5.3 Harness 视角的补充

Harness 综述主张："agent performance is a property of the **model–harness pairing**"，工程演进沿 prompt engineering → context engineering → **harness engineering** → agent-native training 四范式推进 [^9^]。其引用链中的 *Agentic Harness Engineering: observability-driven automatic evolution of coding-agent harnesses*（arXiv:2604.25850）进一步证明：**coding agent 的 harness（脚手架）可以基于可观测性数据自动演化**——这正是"代码/脚手架层自进化"在编码场景的工程化形态 [^9^]。

---

## 6. 工程落地方法论要点（轨迹记录 / eval 集 / 护栏）

### 6.1 轨迹记录（Trajectory / Trace）

- **术语与结构**（Anthropic《Demystifying evals for AI agents》）：task（输入+成功标准）、trial（一次尝试）、grader（评分逻辑）、**transcript/trace/trajectory（一次 trial 的完整记录：输出、工具调用、推理、中间结果）**、outcome（环境最终状态）、evaluation harness（端到端跑 eval 的基础设施）[^12^]。
- **第一天就接入观测**："You cannot evaluate what you cannot observe. Add tracing from day one."；"Pick the trace store before the first commit"，按 OpenTelemetry GenAI 规范埋点，prompt/completion 内容默认 opt-in + 入库脱敏 [^19^][^30^]。
- **轨迹即资产**：构建 "trace-to-eval flywheel"——低分生产轨迹 → 人工标注 → 写入离线 eval 集；"the single biggest accelerator of agent quality over time" [^18^]。LangChain 同样描述该闭环：生产轨迹 → 洞察 → eval 数据集 → 改进 prompt/工具/推理策略 → 回归测试锁定收益 [^18^]。

### 6.2 Eval 集建设

- **先做错误分析再写 eval**（Hamel Husain 方法论）：收集 100+ 条多样化 traces → open coding 逐条标注失败 → axial coding 聚类成 5–6 个失败模式 → 按频率排优先级；以"理论饱和"为停止条件 [^16^][^17^]。
- **起步规模**：20–50 个聚焦已知失败的 case；**用二元 pass/fail 而非 Likert 打分** [^30^]。
- **评分器组合**：确定性检查（schema、工具调用签名、延迟/token 上限）先行；LLM-as-judge 第二阶段引入，需用人工标注校准、以 **TPR/TNR** 衡量（绝不用 agreement）[^16^][^18^][^19^]。
- **能力评测 vs 回归评测**：capability eval 从低通过率起步用于爬坡；regression eval 保持近 100% 通过率防倒退；能力评测成熟后"毕业"为回归集 [^12^]。
- **非确定性度量**：pass@k（k 次至少成功一次）与 pass^k（k 次全部成功）刻画波动 [^12^]。
- **防过拟合**：数据分区、定期用生产数据校验 eval 有效性；"keep datasets from overfitting" [^16^][^17^]。

### 6.3 护栏（Guardrails）

- 部署三分法（Hamel 卡片 12）：**CI/CD**（pre-merge，防回归，block merge）、**在线监控**（异步 post-response，发现新失败、触发告警）、**Guardrails**（同步 pre-response，100% 流量，用单测/小分类器强制安全，失败则 block / retry / fallback）[^17^]。
- 采样策略：确定性检查跑 100% 流量，LLM judge 抽样 1–10%；高风险意图提高采样率 [^19^]。
- 告警对齐 agent 质量而非纯基础设施："the 2am page that matters is the trajectory regression, the tool-call-correctness drop … the spike in retried side-effecting calls" [^19^]。
- 面向攻击面："Probe for prompt injection, jailbreaks, and unsafe tool calls. Add guardrails and human checks that hold up under attack." [^16^]
- 工具层守门：技能/工具入库前必须经执行验证迭代精炼（Voyager 循环），防止错误复利 [^11^]。
- EvoAgentX 内置护栏对应物：HITL 审批拦截器（PRE_EXECUTION APPROVE_REJECT）+ Docker 沙箱解释器 + 内建 evaluation 层 [^22^]。

---

## 7. 对用户场景（Cursor + GPT + superpower skill）的映射建议（基于证据的推断）

1. **层位选择**：从 **prompt 层 + 记忆/经验层** 起步（成本最低、可回滚，符合五问框架的"改了什么/能否回滚"）；技能层用"验证后入库"策略沉淀 superpower skill 的改进；暂不做代码层（DGM 式自我改写）与权重层。
2. **框架选型**：EvoAgentX（MIT、3.2k stars、pip 安装、6 个优化器、内建 benchmark/evaluator、HITL）满足"开源、可直接使用、支持二次开发"；其优化器与评测器适合作为**离线进化管线**：用自建 eval set 驱动 TextGrad/AFlow/MIPRO 优化现有 prompt 与 workflow，产出物版本化后回灌 Cursor skill 体系。
3. **前置条件**：先建轨迹记录（trace store + OTel 埋点）与 20–50 条二元 eval 集，再开自进化——否则优化器没有可信目标函数（"先看数据，再写 eval" [^16^][^17^]）。
4. **护栏**：任何自动写入 prompt/记忆/技能库的更新走"Verify → Retain"两段式（先过回归 eval 再持久化），高风险动作挂 HITL 审批。

---

## 8. 未查到 / 存疑项

- `XMUDeepLIT/Awesome-Self-Evolving-Agents` 与 `EvoAgentX/Awesome-Self-Evolving-Agents` 的**当前 stars 数**：GitHub API 限流、页面动态加载，2026-08-20 未查到精确值（仅有 2026-05/06 第三方快照，未采用为结论）。
- `Shiyao-Huang/awesome-agent-evolution` stars 仅有第三方目录快照（168–187，2026-05/06），2026-08-20 未直接复核。
- 中文工程界（知乎/公众号）关于"自进化 agent 落地"的第一手经验文章：**未查到**高质量命中（2 次中文检索均 0 结果），落地方法论主要依据英文来源。
- 任务所称 "LLM Agent Harnesses 综述 (2026)" 未找到同名精确标题；最接近的为 *A Survey on Agent System and Harness Design*（2606.20683）及其引用的 *Agent Harness Engineering: a survey*（OpenReview 2026）、*Agent Harness for Large Language Model Agents: a survey*（Meng et al., 2026）、*Agentic Harness Engineering*（2604.25850）[^9^]。

---

## 参考文献

[^1^]: XMUDeepLIT Awesome-Self-Evolving-Agents "Related Survey Papers"："（TMLR 2026) A Survey of Self-Evolving Agents What, When, How, and Where to Evolve on the Path to Artificial Super Intelligence"，https://github.com/XMUDeepLIT/Awesome-Self-Evolving-Agents （经快照核实，2026-08-20）
[^2^]: Gao et al., *A Survey of Self-Evolving Agents: What, When, How, and Where to Evolve on the Path to ASI*, arXiv:2507.21046v4。摘要："organizing the field around three foundational dimensions — what to evolve, when to evolve, and how to evolve"，https://arxiv.org/html/2507.21046v4 （2026-08-20 访问）
[^3^]: Fang et al., *A Comprehensive Survey of Self-Evolving AI Agents: A New Paradigm Bridging Foundation Models and Lifelong Agentic Systems*, arXiv:2508.07407。摘要："four key components: System Inputs, Agent System, Environment, and Optimisers"，https://arxiv.org/abs/2508.07407 （2026-08-20 访问）
[^4^]: EvoAgentX README News："[Aug 2025] New Survey Released! … Read it on arXiv (2508.07407) … Check the repo (EvoAgentX/Awesome-Self-Evolving-Agents)"，https://github.com/EvoAgentX/EvoAgentX （2026-08-20 直采）
[^5^]: EvoAgentX/Awesome-Self-Evolving-Agents README（快照）：taxonomy 树 "single-agent optimisation, multi-agent optimisation, and domain-specific optimisation"，https://github.com/EvoAgentX/Awesome-Self-Evolving-Agents （2026-08-20）
[^6^]: XMUDeepLIT/Awesome-Self-Evolving-Agents README（快照 2026-05-20 采集）："Model-Centric Self-Evolution … Environment-Centric Self-Evolution … Model-Environment Co-Evolution"；配套综述 "A Systematic Survey of Self-Evolving Agents: From Model-Centric to Environment-Driven Co-Evolution"（TechRxiv 2026），https://github.com/XMUDeepLIT/Awesome-Self-Evolving-Agents
[^7^]: Wang, Liu, Fang, Meng, *EvoAgentX: An Automated Framework for Evolving Agentic Workflows*, arXiv:2507.03616v2（EMNLP 2025 Demo）。摘要含五层架构、TextGrad/AFlow/MIPRO、HotPotQA +7.44 F1 / MBPP +10 pass@1 / MATH +10 / GAIA +20%，https://arxiv.org/html/2507.03616v2 （2026-08-20 访问）
[^8^]: EvoAgentX/Awesome-Self-Evolving-Agents（同 [^5^]）
[^9^]: *A Survey on Agent System and Harness Design*, arXiv:2606.20683："tracing shifts from prompt engineering to context engineering, harness engineering, and agent-native training … agent performance is a property of the model–harness pairing"；引用 *Agentic Harness Engineering: observability-driven automatic evolution of coding-agent harnesses*（2604.25850），https://arxiv.org/html/2606.20683v1 （2026-08-20 访问）
[^10^]: Shiyao-Huang/awesome-agent-evolution README："想判断一个 AI Agent 是不是'真自进化'，先问五件事：改了什么、为什么改、谁验证、是否保留、能否回滚"；"Observe -> Interpret -> Modify -> Verify -> Retain"；stars 168（2026-06 快照），MIT，https://github.com/Shiyao-Huang/awesome-agent-evolution （2026-08-20 访问）
[^11^]: Ren et al., *Self-Improvements in Modern Agentic Systems: A Survey*, arXiv:2607.13104（2026-07-14）："a configuration coupling a foundation model with an operational scaffold of prompts, memory, tools, and control logic"；§6 Prompt/Memory/Tool/Full scaffolding improvement 与各类风险描述，https://arxiv.org/abs/2607.13104 （2026-08-20 访问）
[^12^]: Anthropic Engineering, *Demystifying evals for AI agents*：task/trial/grader/transcript/outcome 定义、三类 grader 对照表、capability vs regression evals、pass@k 与 pass^k，https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents （2026-08-20 访问）
[^13^]: arXiv:2510.27675："DSPy … compiles language model pipelines into self-improving programs. GEPA … uses reflective natural-language feedback and evolutionary search to iteratively refine prompts."（2026-08-20 检索命中）
[^14^]: *Elastic Memory for Self-Evolving LLM Agents via Knowledge Crystallization*, arXiv:2608.00303："A self-evolving LLM agent improves without weight updates by writing experience into external memory and retrieving it at inference time … Mem0 extracts and consolidates long-term memory at production scale"，https://arxiv.org/html/2608.00303v1
[^15^]: *The Path to Self-Evolving Clinical Systems*, arXiv:2607.11175："prompt optimization encodes short lived lessons, memory evolution accumulates structured knowledge that persists across sessions … Mem0 provides a production grade memory layer … VOYAGER pioneered the skill library concept"，https://arxiv.org/html/2607.11175v2
[^16^]: Maven 课程页（Hamel Husain & Shreya Shankar, AI Evals for Engineers，2026-07 更新）："Instrument a real agent so every run leaves a trace you can inspect … Group and prioritize failure modes … Design and validate LLM-as-judge … Probe for prompt injection … Add guardrails and human checks that hold up under attack"，https://maven.com/parlance-labs/evals （2026-08-20 访问）
[^17^]: Evals Flashcards 解析（转述 Hamel Husain 12 卡片）：错误分析 100+ traces、open/axial coding、理论饱和；卡片 12 部署三分法 CI/CD vs Online Monitoring vs Guardrails 对照表，https://blog.aihao.tw/2026/02/17/evals-flashcards/ （2026-08-20 访问）；方法论原始出处 hamelsmu/evals-skills，https://github.com/hamelsmu/evals-skills
[^18^]: LangChain, *AI Agent Observability: Tracing, Testing, and Improving Agents*："Production evaluations also serve as guardrails … The pipeline that takes low-score production traces … is the single biggest accelerator of agent quality over time"，https://www.langchain.com/resources/agent-observability （2026-08-20 访问）
[^19^]: Reactify Solutions, *AI agent evaluation and observability in 2026*（LangSmith/Langfuse/Phoenix/Braintrust 对比）："Pick the trace store before the first commit … Wire the deterministic eval gate on PR #1 … Build the trace-to-eval flywheel before you ship the agent … sampling 1–10% of traces against the judge while running 100% of deterministic checks"，https://www.reactify-solutions.com/articles/agent-evaluation-observability-2026 （2026-08-20 访问）
[^20^]: OpenAI Agents SDK（经 aurelio-labs/cookbook 转述）："Guardrails: Run input validations and checks in parallel to your agents, breaking early if the checks fail."，https://github.com/aurelio-labs/cookbook （2026-08-20 检索命中）
[^21^]: luo-junyu/Awesome-Agent-Papers（快照）："Agent Evolution: Self-improvement and learning capabilities of agents"，~2.7k stars，https://github.com/luo-junyu/Awesome-Agent-Papers
[^22^]: EvoAgentX README（raw 直采，2026-08-20）：Key Features（Agent Workflow Autoconstruction / Built-in Evaluation / Self-Evolution Engine / Plug-and-Play / Memory Module / HITL）、"driven by your dataset and goals"、HITL 代码示例，https://github.com/EvoAgentX/EvoAgentX/blob/main/README.md
[^23^]: GitHub 仓库页面 HTML 直采（2026-08-20）：aria-label="3242 users starred this repository"；repo-network-counter title="292"（forks）；"1,171 Commits"，https://github.com/EvoAgentX/EvoAgentX
[^24^]: shields.io 徽标直采（2026-08-20）：github/stars/EvoAgentX/EvoAgentX = "3.2k"，https://img.shields.io/github/stars/EvoAgentX/EvoAgentX
[^25^]: EvoAgentX LICENSE（raw 直采，2026-08-20）："MIT License … Copyright (c) 2025 EvoAgentX"，https://raw.githubusercontent.com/EvoAgentX/EvoAgentX/main/LICENSE
[^26^]: *SEW: Self-Evolving Agentic Workflows for Automated Code Generation*, arXiv:2505.18646（实现即 EvoAgentX 仓库；比较 BPMN/CoRE/Python/YAML/伪代码五种工作流表示），https://arxiv.org/pdf/2505.18646
[^27^]: GitHub 目录直采（2026-08-20）：evoagentx/optimizers/ 含 aflow_optimizer.py、evoprompt_optimizer.py、map_elites_optimizer.py、mipro_optimizer.py、sew_optimizer.py、textgrad_optimizer.py、example_optimizer.py、optimizer.py、optimizer_core.py、engine/，https://github.com/EvoAgentX/EvoAgentX/tree/main/evoagentx/optimizers
[^28^]: GitHub 目录直采（2026-08-20）：evoagentx 包 16 个模块目录，https://github.com/EvoAgentX/EvoAgentX/tree/main/evoagentx
[^29^]: GitHub 目录直采（2026-08-20）：examples/ 含 customize_agent.py、action_agent.py、benchmark_and_evaluation.py、agent_with_memory_action.py、mcp_agent.py、alita_agent_example.py、sew_optimizer.py 等，https://github.com/EvoAgentX/EvoAgentX/tree/main/examples
[^30^]: Arnab Roy, *A Synthesis of LLM Evaluation*："Observability first … Start with 20-50 cases focused on known failures. Use binary pass/fail over Likert scales. Never stop reading traces."，https://www.aroy.sh/posts/llm-agent-evals/ （2026-08-20 访问）

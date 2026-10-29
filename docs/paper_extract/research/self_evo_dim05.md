# 维度05：经验/记忆驱动的自进化（Experience/Memory-Driven Self-Evolution）开源方案调研

- 调研日期：**2026-08-20**
- 调研方法：21 次独立搜索（中英文混合，web_search）+ GitHub 页面直接抓取核实 stars/license（GitHub API 限流，改用 `curl github.com/<repo>` 读取 `aria-label="N users starred"` 与 raw LICENSE 文件）+ arXiv 原文核对。
- stars 除特别注明外，均为 **2026-08-20 直接从 github.com 页面抓取**的实测值。

---

## 一、总体结论（速览）

| 方案 | Stars(2026-08-20) | License | 即插即用 | 自进化机制 |
|---|---|---|---|---|
| **Hermes Agent** | **233,263** | MIT | ★★★★★（独立 agent，skill 可被借鉴） | 内置学习闭环：自动创建/改进 skill + 持久记忆 |
| Hermes Self-Evolution | 5,090 | 未查到（依赖 DSPy/GEPA=MIT, Evolver=AGPL） | ★★★（优化器可复用） | DSPy+GEPA 进化 skill/prompt/工具描述 |
| Mem0 | 63,657 | Apache-2.0 | ★★★★★（记忆层 SDK/MCP） | 记忆抽取 ADD/UPDATE/DELETE；2026-04 改单遍 ADD+多信号检索 |
| Letta (MemGPT) | 24,310 | Apache-2.0 | ★★★★★（记忆优先 agent 框架/服务） | OS 式分层记忆，agent 自编辑 core/archival memory |
| Zep/Graphiti | 30,119 | Apache-2.0 | ★★★★★（记忆层 SDK/MCP，支持 Cursor） | 时序知识图谱，实体消解、双时态失效（知识更新） |
| A-MEM | 944 | MIT | ★★★★（Python 库） | Zettelkasten 笔记 + 链接生成 + **记忆演化**（旧记忆被新记忆改写） |
| SimpleMem/EvolveMem | 3,706 | MIT | ★★★★（MCP，明确支持 Cursor） | 语义无损压缩 + **检索机制本身自进化**（AutoResearch 闭环） |
| EverMemOS/EverOS | 12,231 | Apache-2.0 | ★★★★（本地记忆运行时） | 仿生记忆 OS（详见 arXiv 2601.02163） |
| Memento | 2,566 | MIT | ★★★（深研 agent 框架，Case Bank 可借鉴） | 案例库 CBR + 记忆增强 MDP，免微调持续学习 |
| ExpeL | 236 | Apache-2.0 | ★★（研究代码，思想易移植） | 经验池→insight 提取（ADD/UPVOTE/DOWNVOTE/EDIT）→检索复用 |
| Reflexion | 3,235 | MIT | ★★（研究代码，模式极易复制） | 口头强化：失败→自评→反思文本入情景记忆→重试 |
| AWM | 459 | Apache-2.0 | ★★（web agent 专用） | 从轨迹归纳可复用 workflow，离线/在线两模式 |
| Synapse | 70 | **NTU 双重许可（仅非商用）** | ★★ | 轨迹即范例 + 向量记忆检索 |
| SOAR | 56 | MIT | ★（需微调，非即插即用） | 进化搜索+hindsight 学习，用成功程序微调自身 |

**针对用户场景（Cursor + GPT + superpower skill 管理工程）的最直接落点**：① 记忆层选 mem0 / Graphiti / SimpleMem（均有 MCP，可直接挂 Cursor）；② 经验→skill 沉淀借鉴 Hermes 的 SKILL.md（agentskills.io 标准）闭环或其 Self-Evolution 的 GEPA 优化器；③ ExpeL 的 insight 提取流程适合以 superpower skill 形式手工复刻。

---

## 二、逐项详录

### 1. ExpeL（AAAI 2024 Oral，清华 LeapLab）

- **仓库**：https://github.com/LeapLabTHU/ExpeL ｜ **stars：236**（2026-08-20 抓取）｜ **License：Apache-2.0**（LICENSE 文件首行 "Apache License Version 2.0"）｜ **语言：Python 3.9**[^1^][^3^]
- **核心机制**：三阶段——(1) 在训练任务上收集成功/失败轨迹入经验池（失败经 Reflexion 重试）；(2) LLM 从成败对中提取跨任务 insights，对 insight 列表执行 **ADD / UPVOTE / DOWNVOTE / EDIT** 四种操作，强调"提取常见失败模式或最佳实践"；(3) 推理时按任务相似度检索 insights + 成功 few-shot 轨迹指导决策[^1^]。论文实测随经验积累性能持续提升，并出现"世界模型信念更新"（如 ALFWorld 中改变对锅位置的先验）等涌现行为[^1^]。
- **即插即用程度**：低。仓库是 HotpotQA/ALFWorld/WebShop/FEVER 四个 benchmark 的复现代码（README 明确 "This repository contains code for reproducing results"）[^3^]。但机制纯 prompt 工程，**insight 提取 prompt 可低成本移植**为 Cursor skill（工程任务复盘→生成 insight 清单→注入后续会话）。
- **二次开发入口**：`train.py`（经验收集）、`insight_extraction.py`（insight 提取，`agent.max_num_rules`、`agent.success_critique_num` 可调）、`eval.py`（`agent.fewshot_strategy=task_similarity` 检索策略）[^3^]。
- **领域定制**：换 benchmark 目录 + 改 insight prompt 模板；insight 本质是自然语言规则库，可直接人工增删。

### 2. Reflexion（NeurIPS 2023）及开源现状

- **仓库**：https://github.com/noahshinn/reflexion ｜ **stars：3,235**（2026-08-20 抓取，仓库未归档）｜ **License：MIT**（"MIT License Copyright (c) 2023 Noah Shinn"）｜ **语言：Python**[^2^]
- **核心机制**：Actor（LM）产生轨迹 → Evaluator（规则/单元测试/环境二值奖励）→ Self-reflection（LM）生成反思文本存入 **episodic memory** → 下一轮 trial 携带反思重试。编程任务用自生成单元测试做外部反馈[^2^]。
- **开源现状**：官方仓库仅含 HotPotQA/ALFWorld/编程三类实验 notebook 与脚本（`ReflexionStrategy.{NONE,LAST_ATTEMPT,REFLEXION,LAST_ATTEMPT_AND_REFLEXION}` 四种策略枚举）[^2^]，README 自述 GPT-4 API 成本使个人难以完整复现；生态上 Reflexion 已成"模式"被广泛重实现（LangChain/LangGraph 均有官方 Reflexion 实现）。**无活跃维护迹象**（最后实质性更新在 2023-2024），作为算法范式而非可用框架对待。
- **即插即用程度**：作为记忆层低；作为**会话内反思循环**模式极易嵌入任何 agent（约 100 行代码）。
- **局限**：反思只存在单任务 episodic buffer，**无跨任务持久化**——这正是 ExpeL/AWM/Memento 要补的缺口。

### 3. Agent Workflow Memory (AWM)

- **仓库**：https://github.com/zorazrw/agent-workflow-memory ｜ **stars：459**（2026-08-20 抓取）｜ **License：Apache-2.0**（LICENSE 首行确认）｜ **语言：Python**[^4^]
- **核心机制**：从历史轨迹**归纳可复用 routines（workflows）**，检索注入后续任务的 prompt。**离线模式**：训练轨迹一次性拼接喂给 LLM 生成 workflow 库；**在线模式**：测试时边做边归纳、动态扩充[^4^]。Mind2Web/WebArena 上相对成功率 +24.6%/+51.1%，跨任务/跨站点/跨领域泛化 8.9→14.0 绝对点[^4^]。
- **即插即用程度**：代码面向 web navigation（Mind2Web/WebArena 评测）。Arize  glossary 明确指出其架构**不依赖特定框架**——"需求只是：历史运行记录 + 成功信号 + workflow 存储 + 检索注入，可以建在任何 agent 栈上"[^5^]。对工程 agent，workflow ≈ 沉淀的 SOP/runbook，与 Cursor 的 rules/skill 文件天然同构。
- **风险**："从一次侥幸成功归纳出的 workflow 会变成 agent 自信地套用到不适用任务上的坏习惯"，需按 workflow 跟踪成功率并淘汰过期项[^5^]。
- **领域定制**：workflow 以自然语言/步骤序列表示，领域定制=换轨迹来源 + 调整归纳 prompt。

### 4. Synapse（ICLR 2024）

- **仓库**：https://github.com/ltzheng/Synapse ｜ **stars：70**（2026-08-20 抓取）｜ **License：⚠ NTU-NTUITIVE 双重许可——仅限非商业用途**（"Non-Commercial Use Only… You may not use or distribute this Software or any derivative works in any form for commercial purposes"；商用需联系 boan@ntu.edu.sg）｜ **语言：Python 3.10**[^6^][^7^]
- **核心机制**：state abstraction（LLM 过滤任务无关状态信息）→ **trajectory-as-exemplar prompting**（完整抽象轨迹做 few-shot）→ **exemplar memory**（任务元数据 embedding 存 FAISS，相似检索泛化到新任务）。MiniWoB++ 99.2% 成功率、Mind2Web 步级成功率相对 +56%[^6^]。
- **即插即用**：面向 computer control（MiniWoB++/Mind2Web），记忆即检索式示范库；思想可用，**商用代码不可直接用**（许可限制）。

### 5. SOAR（进化式程序合成自改进）

- **仓库**：https://github.com/flowersteam/SOAR ｜ **stars：56**（2026-08-20 抓取）｜ **License：MIT**（LICENSE.md 首行 "The MIT License (MIT)"）｜ **语言：Python**[^8^]
- **核心机制**：与任务提示中"从成功轨迹合成 program"相符——LLM 在进化循环中 sample & refine 候选程序，**hindsight 学习阶段把搜索尝试（含成功解）转化为 problem-solution 对来微调 LLM 自身**，形成"更好模型→更有效搜索→更好训练数据"的自改进飞轮；ARC-AGI 公开测试集解出 52%[^8^]。
- **即插即用程度**：低——依赖对 Qwen2.5-Coder 7B/14B/32B 做**参数微调**，不是免微调的记忆层；适合有自有模型训练管道的场景，不适合纯 API + Cursor 工作流直接复用。
- **二次开发**：进化搜索 + hindsight relabeling 代码均开源，可将其"成功轨迹→训练样本"的数据合成部分单独借用。

### 6. Memento（华为诺亚/UCL，免微调持续学习）

- **仓库**：https://github.com/Agent-on-the-Fly/Memento ｜ **stars：2,566**（2026-08-20 抓取）｜ **License：MIT**（"MIT License Copyright (c) 2025 Agent-on-the-Fly"）｜ **语言：Python 3.11+**[^9^][^10^]
- **核心机制**：形式化为 **Memory-augmented MDP**；planner-executor 架构 + **Case Bank** 存成功/失败轨迹（最终步 `(s_T, a_T, r_T)` 元组），支持非参数 CBR（检索）与参数化 CBR（可微案例选择策略）。"Learn from experiences, not gradients"[^10^]。GAIA 验证集 87.88% Pass@3（Top-1）、测试集 79.40%；OOD 任务 +4.7~9.6 绝对点[^9^]。
- **即插即用**：中等。非参数 CBR 推理代码已开源（2025-08-30），executor 走 **MCP 协议**，支持任意 OpenAI 兼容端点与本地 vLLM；但整个框架是 deep research agent，嵌入现有工程需拆解其 Case Bank + 检索模块[^10^]。
- **二次开发入口**：`server/` 下新增 FastMCP 工具、`interpreters/` 继承 `BaseInterpreter` 扩展执行后端[^10^]。
- **重要经验**：README 实测 "**Small, high-quality memory works best**: Retrieval **K=4** yields peak F1/PM"[^10^]——检索噪声随 K 增大明显劣化。

### 7. Hermes Agent（Nous Research）——重点核实

- **仓库**：https://github.com/NousResearch/hermes-agent ｜ **stars：233,263**（**2026-08-20 直接抓取 GitHub 页面** `aria-label="233263 users starred"`）｜ **License：MIT**（README "License MIT — see LICENSE"）｜ **语言：Python（主），TypeScript（Web 仪表盘）**[^11^][^12^]
- **stars 核实（回应"网上有夸张说法"）**：GitHub 官方页面实测 233,263（2026-08-20）。第三方营销页 hermes-agent.us 称 222,714（2026-07-30）[^13^]、star-history 232.3k 全球 #19[^14^]、gitup-arena 222.4k（2026-07-30）[^15^]、gitstarclub 216.5k（2026-07-19）[^16^]——**多源一致，"20 万+"并非夸张，是真实数据**。但需注意其增长异常陡峭：2025-07-22 建库[^17^]，2026-04-13 中文报道仅 16,819 stars[^18^]，4 个月涨约 21 万；且 GitUp/forgeregistry 显示 open issues 高达 1.6 万~2.4 万[^15^][^17^]。stars 真实性无异议，但 stars≠成熟度的常规警示在此尤为适用。
- **自进化机制（README 原文）**："the only agent with a built-in learning loop — it **creates skills from experience, improves them during use, nudges itself to persist knowledge, searches its own past conversations**, and builds a deepening model of who you are across sessions"；具体为 agent-curated memory + 定期 nudge、复杂任务后自动创建 skill、skill 使用中自我改进、FTS5 会话检索 + LLM 摘要、Honcho 用户建模；skill 兼容 **agentskills.io 开放标准**[^12^]。2026-04-30 版本加入"autonomous background Curator"自动维护 skill 库[^19^]。
- **即插即用程度**：它是**完整独立 agent（CLI/TUI/消息网关），不是可嵌入的记忆库**——不能直接当记忆层插进 Cursor agent。但其 skill 文件格式（SKILL.md，≤15KB）与 superpower skill 同构，**闭环设计（用中改进 + 后台策展）可直接借鉴**；文档齐全（Architecture/Skills System/Memory 章节）[^12^]。
- **二次开发**：`uv pip install -e ".[all,dev]"` + `scripts/run_tests.sh`；40+ 工具、7 种终端后端、MCP 集成[^12^]。

### 8. Hermes Agent Self-Evolution（skill 进化优化器）

- **仓库**：https://github.com/NousResearch/hermes-agent-self-evolution ｜ **stars：5,090**（2026-08-20 抓取）｜ **License：未查到 LICENSE 文件**（main 分支无 LICENSE/LICENSE.md；README 标注所依赖的 DSPy+GEPA 为 MIT、Darwinian Evolver 为 AGPL v3 外部 CLI）｜ **语言：Python**[^20^]
- **核心机制**：**DSPy + GEPA（Genetic-Pareto Prompt Evolution，ICLR 2026 Oral）** 对 skill 文件（SKILL.md）、工具描述、系统 prompt、代码做反思式进化搜索；无需 GPU 训练，每次优化约 $2-10 API 成本[^20^]。**护栏**：变体必须 100% 过 pytest、skill ≤15KB、工具描述 ≤500 字符、语义不漂移、一律走 PR 人工评审[^20^]。
- **进度**：Phase 1（skill 进化）已实现；Phase 2-5（工具描述/系统 prompt/代码/持续循环）Planned[^20^]。
- **对用户价值**：这是把"经验→skill 改进"做成**可复用优化器**的项目，`python -m evolution.skills.evolve_skill --eval-source sessiondb` 可直接消费 Claude Code/Copilot/Hermes 的真实会话历史——**理论上可以指向任何存放 skill 文件的目录做进化**，是二次开发的最佳切入口之一[^20^]。

### 9. MemGPT / Letta

- **仓库**：https://github.com/letta-ai/letta ｜ **stars：24,310**（2026-08-20 抓取；第三方 2026-06-25 记录为 22K+[^21^]）｜ **License：Apache-2.0**（LICENSE 首行确认；第三方核实一致[^21^]）｜ **语言：Python（含 TS SDK）**[^21^]
- **核心机制**：OS 式分层记忆——core memory（persona/human 块，agent 可用工具**自编辑**）+ archival memory（长文本外部存储，分页检索）；agent 自主决定何时写/换出上下文，即"记忆自管理"[^21^]。
- **自进化属性**：记忆内容由 agent 主动改写（self-editing memory），跨会话人格/用户画像持续更新；但无自动"经验→规则"提炼，需自行在其 archival memory 上实现。
- **即插即用**：高。开源核心 + REST API + Python/TS SDK + ADE；记忆可跨 provider 迁移[^21^]。可作为独立记忆服务挂在任何 agent 后。
- **二次开发**：letta-ai/letta 源码开放，memory block 类型、工具均可自定义；托管版另有计费（不影响开源自托管）[^21^]。

### 10. A-MEM（Agentic Memory）

- **仓库**：https://github.com/WujiangXu/AgenticMemory ｜ **stars：944**（2026-08-20 抓取）｜ **License：MIT**（"MIT License Copyright (c) 2025 Wujiang Xu …"）｜ **语言：Python**；生产版另见 https://github.com/agiresearch/A-mem[^22^][^23^]
- **核心机制（arXiv 2502.12110）**：Zettelkasten 式原子笔记（内容+上下文描述+关键词+标签+embedding）；(1) **链接生成**——新笔记检索 top-k 邻居，LLM 判断是否建立语义链接，形成演化中的记忆图；(2) **记忆演化（memory evolution）**——"new memories are integrated, they can trigger updates to the contextual representations and attributes of existing historical memories"，即**旧记忆会被新经验改写**，记忆网络持续自组织[^22^][^24^]。写入侧成本较高（每次插入多次 LLM 调用）[^25^]。
- **即插即用**：较高，纯 Python 库，记忆接口清晰（add/search）；LoCoMo 等 benchmark 评测代码同仓库。
- **风险**：第三方分析明确警告"**don't silently rewrite high-influence memories**"——静默改写带来版本/审计与安全问题，二开时应加版本化与审批[^26^]。
- **领域定制**：笔记属性 schema、链接/演化 prompt 均可改。

### 11. Mem0

- **仓库**：https://github.com/mem0ai/mem0 ｜ **stars：63,657**（2026-08-20 抓取；2026-07-29 第三方记录 62,121[^27^]）｜ **License：Apache-2.0**（LICENSE 确认，第三方核实一致[^27^]）｜ **语言：Python + TypeScript SDK**[^27^]
- **核心机制**：LLM 从对话中抽取候选记忆 → 基于语义相似度执行 ADD/UPDATE/DELETE 自适应操作[^28^]；**2026-04 "New Memory Algorithm"** 改为单遍 ADD-only 抽取 + 多信号检索（语义+BM25+实体匹配并行融合），LongMemEval 从 ~49% 升至 93.4%[^27^][^29^]。
- **即插即用**：**最高**。Python/TS SDK、CLI（`mem0 add/search`）、MCP 原生（`mem0 init --agent`），可直接作为 Cursor 的记忆层[^27^]。
- **自进化属性**：记忆随新对话持续增删改（UPDATE/DELETE 即知识更新），但无"轨迹→skill/规则"的程序性经验提炼；属陈述性记忆层。
- **局限**：批评者指出抽取式记忆会丢信息（"extraction loses information"），旧算法 LongMemEval 仅 ~49%[^29^]。

### 12. Zep / Graphiti

- **仓库**：https://github.com/getzep/graphiti ｜ **stars：30,119**（2026-08-20 抓取；第三方 2026-07-30 记录 29,431[^30^]）｜ **License：Apache-2.0**（LICENSE 确认，第三方核实一致[^30^]）｜ **语言：Python（另有 zep-js TS SDK）**[^30^]
- **核心机制**：**时序知识图谱**（bi-temporal triplet：事件时间 + 摄入时间），三层子图（episode/semantic entity/community），实体消解、混合检索（vector+BM25+graph）、**事实带有效期窗口自动失效**——天然支持"知识更新"（旧事实被新事实取代而非共存冲突）[^30^][^31^]。
- **即插即用**：高。graphiti-core PyPI 包 + **官方 MCP server（stdio 支持 Claude Desktop，SSE/HTTP 明确支持 Cursor IDE / VS Code Copilot）**；后端 Neo4j/FalkorDB/Neptune，Docker Compose 一键起[^30^]。
- **自进化属性**：图随 episode 摄入持续演化（实体消解合并、社区检测、时态失效），属结构级知识更新；无程序性 skill 提炼。
- **领域定制**：自定义实体/边类型（Pydantic schema）、episode JSON 摄入。

### 13. SimpleMem / EvolveMem（2026 新星，检索机制自进化）

- **仓库**：https://github.com/aiming-lab/SimpleMem ｜ **stars：3,706**（2026-08-20 抓取；arXiv 引文记录 3.2K[^32^]）｜ **License：MIT**（LICENSE 首行确认）｜ **语言：Python（PyPI `simplemem`）**[^33^][^34^]
- **核心机制**：三阶段——语义结构化压缩（原子事实+多视图索引）、在线语义合成（去冗余）、意图感知检索规划；LoCoMo 平均 F1 +26.4%、推理 token 降约 30×[^33^]。**2026-05-14 发布 EvolveMem（v3.0）**："the retrieval infrastructure itself now self-evolves through LLM-driven closed-loop diagnosis"——**Evaluate→Diagnose→Propose→Guard→Repeat** 闭环，LLM 诊断逐题失败并提出配置变更，回归自动回滚；LoCoMo 相对最强基线 +25.7%，且进化出的配置跨 benchmark 正迁移[^34^]。
- **即插即用**：高。**MCP 协议支持，README 明示兼容 Claude、Cursor、LM Studio**[^35^]；`simplemem.optimize(...)` 可对自己数据跑自进化调优[^34^]。
- **亮点**：是调研中唯一把**记忆系统自身的检索/融合策略**纳入进化对象的开源实现，与用户"领域专用改进"诉求高度匹配。

### 14. EverMemOS / EverOS（EverMind，仿生记忆 OS）

- **仓库**：https://github.com/EverMind-AI/EverMemOS（README 已更名 EverOS）｜ **stars：12,231**（2026-08-20 抓取）｜ **License：Apache-2.0**（LICENSE 首行确认）｜ **语言：Python**[^36^]
- **核心机制**：论文 arXiv 2601.02163《EverMemOS: Bio-inspired memory operating system for AI agents》[^32^]；README 自述"Python library and local-first memory runtime for agents… one portable memory layer across coding assistants, apps, devices"，存储对话、文件与 agent 经验[^36^]。
- **即插即用**：较高（本地优先运行时 + 文档站 docs.evermind.ai）。详细机制（记忆巩固/遗忘建模）本次未深入核对原文，**细节待补充阅读**。
- **说明**：repo 处于品牌迁移期（EverMemOS→EverOS），检索时注意别名。

---

## 三、局限性横评（记忆污染 / 遗忘 / 检索噪声）

1. **记忆污染（memory poisoning）**：抽取/演化式记忆把改写权交给 LLM，恶意或错误内容一旦入库会持续影响后续检索——已有专门防御研究（SuperLocalMemory，"Bayesian trust defense against memory poisoning"，arXiv 2603.02240）[^32^]；A-MEM 类"静默改写旧记忆"需版本化+人工审批，第三方建议 "don't silently rewrite high-influence memories"[^26^]。
2. **检索噪声**：Memento 实测检索 K=4 时性能峰值，**小而精的记忆优于大而全**[^10^]；mem0 旧两阶段算法 LongMemEval 仅 ~49% 表明抽取损失可致命，2026-04 多信号融合才升到 93.4%[^29^]。
3. **坏习惯固化**：AWM 从侥幸成功的轨迹归纳 workflow 会被自信误用，需按 workflow 追踪成功率、定期过期淘汰[^5^]；Hermes 用 pytest 全过 + PR 评审做进化护栏[^20^]。
4. **遗忘设计普遍缺失**：多数系统只做"加"不做"忘"；学术侧 MemoryBank（艾宾浩斯遗忘曲线）、H-Mem、MemoryOS 等提供分层/衰减设计[^28^]，Graphiti 用双时态失效窗口实现"旧知识自动过期"[^30^]。
5. **写入成本**：A-MEM 每次插入多次 LLM 调用（笔记构建+链接+演化）[^25^]；Hermes/GEPA 类进化每轮 $2-10[^20^]——持续自进化不是免费的。
6. **Reflexion 式反思无跨任务持久化**，单任务结束后经验即丢，必须搭配 ExpeL/AWM/Memento 式沉淀层[^1^][^2^]。

---

## 四、参考来源

[^1^]: ExpeL: LLM Agents Are Experiential Learners, arXiv:2308.10144v2 (2023-12-18), https://arxiv.org/html/2308.10144v2 — "the agent dynamically modifies an existing list of insights using operations ADD, UPVOTE, DOWNVOTE, and EDIT"；访问 2026-08-20。
[^2^]: GitHub - noahshinn/reflexion, https://github.com/noahshinn/reflexion — "This repo holds the code, demos, and log files for Reflexion"；stars 3,235 与 MIT LICENSE 于 2026-08-20 抓取。
[^3^]: GitHub - LeapLabTHU/ExpeL, https://github.com/LeapLabTHU/ExpeL — "[AAAI 2024 (Oral)] Official implementation of the ExpeL Agent"；stars 236 与 Apache-2.0 LICENSE 于 2026-08-20 抓取。
[^4^]: Agent Workflow Memory, arXiv:2409.07429 (2024-09-11), https://arxiv.org/html/2409.07429v1 — "AWM substantially improves the baseline results by 24.6% and 51.1% relative success rate on Mind2Web and WebArena"；仓库 zorazrw/agent-workflow-memory stars 459、Apache-2.0 于 2026-08-20 抓取。
[^5^]: Agent Workflow Memory (AWM) - Arize Glossary (2026-08-14), https://arize.com/glossary/agent-workflow-memory-awm/ — "The requirements are a record of past runs, a reliable signal for which runs succeeded, a store for induced workflows, and a retrieval step"；"a workflow induced from a lucky run becomes a bad habit"。
[^6^]: Synapse: Trajectory-as-Exemplar Prompting with Memory for Computer Control, ICLR 2024, https://proceedings.iclr.cc/paper_files/paper/2024/file/52f050499cf82fa8efb588e263f6f3a7-Paper-Conference.pdf — MiniWoB++ 99.2%、Mind2Web 相对 +56%；访问 2026-08-20。
[^7^]: ltzheng/Synapse LICENSE（NTUITIVE Dual License）, https://raw.githubusercontent.com/ltzheng/Synapse/main/LICENSE — "Non-Commercial Use Only"；stars 70 于 2026-08-20 抓取。
[^8^]: Self-Improving Language Models for Evolutionary Program Synthesis: A Case Study on ARC-AGI (SOAR), arXiv:2507.14172v2 (2026-03-16), https://arxiv.org/html/2507.14172v2 — "a hindsight learning phase that converts search attempts into valid problem-solution pairs used to fine-tune the LLM… enabling SOAR to solve 52% of the public test set"；"Our code is open-sourced at: github.com/flowersteam/SOAR"；stars 56、MIT 于 2026-08-20 抓取。
[^9^]: Memento: Fine-tuning LLM Agents without Fine-tuning LLMs, arXiv:2508.16153 (2025-08-25), https://arxiv.org/abs/2508.16153 — GAIA val 87.88% Pass@3、test 79.40%、OOD +4.7~9.6pt；访问 2026-08-20。
[^10^]: GitHub - Agent-on-the-Fly/Memento, https://github.com/Agent-on-the-Fly/Memento — "Learn from experiences, not gradients"；"Small, high-quality memory works best: Retrieval K=4 yields peak F1/PM"；stars 2,566、MIT 于 2026-08-20 抓取。
[^11^]: GitHub - NousResearch/hermes-agent 页面抓取, https://github.com/NousResearch/hermes-agent — `aria-label="233263 users starred"`，抓取于 2026-08-20。
[^12^]: Hermes Agent README, https://github.com/NousResearch/hermes-agent — "it creates skills from experience, improves them during use, nudges itself to persist knowledge, searches its own past conversations… Compatible with the agentskills.io open standard"；"License MIT"；访问 2026-08-20。
[^13^]: hermes-agent.us（第三方营销页，2026-07-30）, https://hermes-agent.us/ — "222,714 stars / Forks: 42,762"。
[^14^]: star-history.com NousResearch/hermes-agent, https://www.star-history.com/nousresearch/hermes-agent — "232.3k Stars · Global Rank #19"；访问 2026-08-20。
[^15^]: GitUp Arena - NousResearch/hermes-agent (2026-07-30), https://www.gitup-arena.dev/repos/NousResearch/hermes-agent/ — "222.4k stars, Global Rank #20, Python"。
[^16^]: GitStarClub - NousResearch/hermes-agent (数据截至 2026-07-19), https://gitstarclub.com/NousResearch/hermes-agent — "216.5k GitHub stars… June 2026 recorded +28.4k stars and ended at 201.2k"。
[^17^]: github-traction-nousresearch-hermes-agent.md (2026-06-01), https://github.com/AlekseiUL/hermes-researcher-agent/blob/main/examples/github-traction-nousresearch-hermes-agent.md — "Created: 2025-07-22… Stars / forks / watchers: 175206 / 29815 / 689；Open issues: 15996；License: MIT"。
[^18^]: CSDN《Hermes Agent的GitHub解析》(2026-04-13), https://blog.csdn.net/u011095039/article/details/160114838 — "GitHub 16,819 Stars，MIT开源"（当时数据，用于增长曲线对照）。
[^19^]: Hermes Agent News, https://hermes-ai.net/news/ (2026-07-20) — "Hermes Crosses 100K GitHub Stars"(2026-04-16)；"v2026.4.30: Autonomous Background Curator"。
[^20^]: GitHub - NousResearch/hermes-agent-self-evolution README, https://raw.githubusercontent.com/NousResearch/hermes-agent-self-evolution/main/README.md — "uses DSPy + GEPA… No GPU training required… ~$2-10 per optimization run"；"Full test suite must pass 100%… PR review, never direct commit"；stars 5,090 于 2026-08-20 抓取；LICENSE 文件未查到。
[^21^]: Letta (formerly MemGPT) - aipedia.wiki (2026-06-25), https://aipedia.wiki/tools/letta/ — "License Apache-2.0；letta-ai/letta · 22K+ stars；Memory model: Typed blocks: core (persona, human) · archival (long-form)"；2026-08-20 实测 24,310 stars。
[^22^]: A-MEM: Agentic Memory for LLM Agents, arXiv:2502.12110 (2025-02-17), https://arxiv.org/abs/2502.12110 — "this process enables memory evolution - as new memories are integrated, they can trigger updates to the contextual representations and attributes of existing historical memories"。
[^23^]: GitHub - WujiangXu/AgenticMemory, https://github.com/WujiangXu/AgenticMemory — stars 944、MIT 于 2026-08-20 抓取；生产系统 agiresearch/A-mem 见 paperswithcode 页面 https://paperswithcode.com/paper/a-mem-agentic-memory-for-llm-agents 。
[^24^]: arXiv:2605.29960 对 A-Mem 的机制综述, https://arxiv.org/pdf/2605.29960 — "A-Mem further updates ('evolves') previously stored notes… by prompting the LLM to revise their context/keywords/tags in light of the new note"。
[^25^]: arXiv:2605.30711, https://arxiv.org/pdf/2605.30711 — "it still issues multiple LLM calls per insertion (note construction, link generation, and evolution), placing the bulk of its computational cost on the write side"。
[^26^]: lhl/agentic-memory A-Mem 参考笔记 (2026-02-21), https://github.com/lhl/agentic-memory/blob/main/references/xu-a-mem.md — "it raises strong versioning/audit and safety questions (don't silently rewrite high-influence memories)"。
[^27^]: openmemory/docs/research/04-opensource-ecosystem.md (2026-07-29), https://github.com/Bilal140202/openmemory/blob/main/docs/research/04-opensource-ecosystem.md — "mem0ai/mem0，License Apache-2.0 (verified from LICENSE file)，Stars 62,121… single-pass ADD-only extraction… multi-signal retrieval… `mem0 init --agent`"；2026-08-20 实测 63,657。
[^28^]: arXiv:2601.07582 记忆系统综述, https://arxiv.org/pdf/2601.07582 — "Mem0 adopts a two-stage pipeline of memory extraction and update… (addition, update, or deletion)"；另载 MemoryBank/H-Mem/MemoryOS 遗忘曲线设计。
[^29^]: MemPalace 论文 (arXiv:2604.21284) 对 mem0/Zep 的评测, https://arxiv.org/pdf/2604.21284 — "Its original LongMemEval performance (~49%)… in April 2026, Mem0 released a 'token-efficient memory algorithm'… raising their LongMemEval score to 93.4%"。
[^30^]: Zep (Graphiti) - memoryatlas.dev (2026-07-23), https://www.memoryatlas.dev/frameworks/zep — "29,431 stars, license Apache-2.0 confirmed"；"Graphiti MCP server… SSE/HTTP (Cursor IDE, VS Code with Copilot)"；2026-08-20 实测 30,119。
[^31^]: arXiv:2601.07582, https://arxiv.org/pdf/2601.07582 — "Zep leverages a temporal knowledge graph engine with a three-tiered subgraph structure comprising episodic, semantic entity, and community layers… bi-temporal modeling"。
[^32^]: arXiv:2603.14588 参考文献, https://arxiv.org/pdf/2603.14588 — "[2] aiming-lab/SimpleMem, 3.2K stars"；"[6] SuperLocalMemory: Privacy-preserving multi-agent memory with Bayesian trust defense against memory poisoning"；"[15] EverMemOS: Bio-inspired memory operating system for AI agents, arXiv:2601.02163, 2026"。
[^33^]: SimpleMem: Efficient Lifelong Memory for LLM Agents, arXiv:2601.02553 (2026-01-05), https://arxiv.org/html/2601.02553v1 — "achieving an average F1 improvement of 26.4% while reducing inference-time token consumption by up to 30×；Code: github.com/aiming-lab/SimpleMem"。
[^34^]: GitHub - aiming-lab/SimpleMem README, https://github.com/aiming-lab/SimpleMem — "EvolveMem (v3.0) — Self-Evolving Memory via AutoResearch… Evaluate → Diagnose → Propose → Guard → Repeat… +25.7% relative (LoCoMo)… evolved configurations transfer positively across benchmarks"；stars 3,706、MIT 于 2026-08-20 抓取。
[^35^]: SimpleMem v0.1.0 Release (2026-05-21), https://github.com/aiming-lab/SimpleMem/releases — "MCP protocol support — compatible with Claude, Cursor, LM Studio, and more"。
[^36^]: GitHub - EverMind-AI/EverMemOS (README 现名 EverOS), https://raw.githubusercontent.com/EverMind-AI/EverMemOS/main/README.md — "EverOS is a Python library and local-first memory runtime for agents and makers"；stars 12,231、Apache-2.0 于 2026-08-20 抓取。

---

## 五、未查到 / 待补充

- **hermes-agent-self-evolution 的 LICENSE**：仓库内未找到 LICENSE 文件（README 仅列出依赖引擎的许可），标注未查到。
- **EverMemOS/EverOS 的自进化机制细节**（记忆巩固、遗忘建模）：本次仅核到仓库与论文题录（arXiv 2601.02163），未读全文。
- **Reflexion 生态的现代复现**（LangGraph 官方 reflexion 实现等）的独立 stars 未逐一核实。
- **Zep 主仓库 getzep/zep**（非 graphiti）stars 未单独核实；graphiti 为其开源核心。

# 维度 07：软件工程/编码 Agent 的自进化（Self-Evolving SWE/Coding Agents）开源方案深度调研

- **调研日期**：2026-08-20（所有 stars 均为该日查询，GitHub API 对本机限流，stars 通过 GitHub 仓库页面抓取核实）
- **用户场景**：在自己的工程中以 Cursor + GPT + superpower skill 管理工程，希望引入"Agent 自进化模块"。要求：开源、可直接使用、支持二次开发与领域专用改进；重点关注仓库级理解、issue 驱动、测试驱动验证的落地能力。
- **调研方法**：共执行 26 次独立搜索（中英混合），覆盖 arXiv 论文、GitHub 仓库/官方文档、技术评测站；另直接访问 arXiv 摘要页与 9 个 GitHub 仓库页核实 stars/license。

## 搜索记录（26 次独立查询）

1. `SE-Agent self-evolving trajectory optimization NeurIPS 2025 GitHub`
2. `Live-SWE-agent software engineering agent self-evolve runtime`
3. `OpenHands OpenDevin experience reuse microagents GitHub`（0 结果，改用其他关键词）
4. `SWE-agent Princeton trajectory experience replay GitHub`（0 结果，改用其他关键词）
5. `Self-play SWE-RL arXiv 2025`
6. `SWE-Exp experience-driven software engineering agent arXiv`
7. `self-evolving coding agent github 2026`
8. `SWE agent experience replay repository-level issue resolution`
9. `SE-Agent github SWE-bench Verified trajectory evolution revision recombination refinement`
10. `SWE-Exp github experience bank issue resolution repository`
11. `OpenHands microagents repo knowledge memory GitHub All-Hands-AI`
12. `mini-SWE-agent GitHub SWE-agent 100 lines`
13. `自进化 coding agent 开源 2026 经验复用 GitHub`（中文）
14. `Self-play SWE-RL arXiv 2512.18552 superintelligent software agents`
15. `OpenHands plugin system custom agents extensions development`
16. `SWE-agent license MIT stars GitHub SWE-agent/SWE-agent`
17. `github SE-Agent "2508.02085" code repository StepFun`（0 结果）
18. `github SWE-Exp "experience-driven software issue resolution" code repository`
19. `OpenHands memory condensation experience replay "agent skill" self-improvement documentation`（0 结果）
20. `"SE-Agent" github.com self-evolution trajectory repository Lin Guo`
21. `SICA self-improving coding agent Robeyns github`
22. `Darwin Gödel Machine github SakanaAI self-improving agents`
23. `SWE-bench illusion memorization contamination criticism 2025`
24. `OpenHands microagents documentation repo-specific instructions .openhands`
25. `GenericAgent lsdefine github self-evolving skill crystallization`
26. `Live-SWE-agent 自进化 工具合成 解读 知乎 中文` / `OpenHands 经验复用 skills AGENTS.md 记忆 中文` / `Self-play SWE-RL code release github Meta FAIR available` / `hermes-agent NousResearch stars skill learning self-improvement`（中文 2 次 + 英文 2 次）

---

## 0. 总览对比表（stars 查询日期：2026-08-20）

| 方案 | 仓库 | Stars | License | 语言 | 自进化机制 | SWE-bench 表现 | 即插即用 | 适配"管理自己的工程" |
|---|---|---|---|---|---|---|---|---|
| **Live-SWE-agent** | [OpenAutoCoder/live-swe-agent](https://github.com/OpenAutoCoder/live-swe-agent) | 452 | MIT | Python | 运行时即时自造/自改工具（on-the-fly tool synthesis + 步级反思） | Verified 75.4–79.2%；Pro 45.8%（SOTA 级） | 高（mini-SWE-agent 上增量改造） | ★★★★★ |
| **OpenHands** | [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands) | 84,549 | MIT | Python/TS | Skills/插件体系 + agent-memory（AGENTS.md 知识沉淀）+ Automations | CodeAct 系列 Verified ~53%+（随版本变化，未核实最新值） | 极高（产品化） | ★★★★★ |
| **SWE-Exp** | [cslsolow/SWE-Exp](https://github.com/cslsolow/SWE-Exp) | 44 | Apache-2.0 | Python | 四阶段经验库（轨迹收集→经验萃取→检索→复用），双 Agent | Verified 41.6%（DS-V3）/ 73%（Claude 4 Sonnet，论文 v2） | 中（研究代码，需自建经验库） | ★★★★ |
| **SE-Agent** | [JARVIS-Xs/SE-Agent](https://github.com/JARVIS-Xs/SE-Agent) | 286 | MIT | Python | 轨迹级进化算子：Revision / Recombination / Refinement | Verified 61.2%（Claude 3.7）/ 80.0%（Claude 4 Sonnet） | 中高（作为 SWE-agent 插件模块） | ★★★★ |
| **SWE-agent / mini-SWE-agent** | [SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent) / [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) | 20,087 / 6,629 | MIT / MIT | Python | 本体无内建经验复用；轨迹是一等公民（可复现/微调/作 RL 数据）；是多数自进化方案的基座 | mini >74% Verified（官方 README 口径 65–74%+） | 高 | ★★★★（作为基座） |
| **SICA** | [MaximeRobeyns/self_improving_coding_agent](https://github.com/MaximeRobeyns/self_improving_coding_agent) | 386 | MIT | Python | 自指改进：Agent 直接编辑自身代码库 + 基准验证循环 | 50 题子集 17%→53% | 中（研究原型，Docker 运行） | ★★★ |
| **Darwin-Gödel Machine (DGM)** | [jennyzzt/dgm](https://github.com/jennyzzt/dgm) | 2,239 | Apache-2.0 | Python | 开放式进化：自我修改代码 + 基准实证 + Agent 档案库 | SWE-bench 20%→50%；Polyglot 14.2%→30.7% | 低（离线进化成本高） | ★★ |
| **Self-play SWE-RL (SSR)** | 未查到公开代码（Meta FAIR 论文） | — | — | — | 自博弈 RL：同一模型既注入 bug 又修 bug，无需人工数据 | SWE-bench Verified/Pro 上超过人工数据 RL（论文口径） | 低（需 RL 训练基础设施） | ★（方法论参考） |
| **SWE-Replay** | 未查到公开代码 | — | — | — | 测试时轨迹回收：在关键中间步分叉复用已采样轨迹 | Verified 成本降 17.4%、解决率 +3.8% | 低 | ★★（方法论参考） |
| **GenericAgent** | [lsdefine/GenericAgent](https://github.com/lsdefine/GenericAgent) | 13,810 | MIT | Python | 技能结晶：任务执行路径固化为 Skill 写入 5 层记忆 | 无 SWE-bench 数据 | 高（pip 安装） | ★★★（通用 OS 控制，非 SE 专用） |
| **Hermes Agent + Self-Evolution** | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) / [hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution) | 233,265 / 未查 | MIT / MIT | Python/TS | 闭环学习：经验→Skill 自动生成与使用中自改进；GEPA 进化搜索优化 skill/prompt/代码 | 无公开 SWE-bench 数据 | 高 | ★★★★ |

---

## 1. SE-Agent（自进化轨迹优化，NeurIPS 2025）

- **论文**：SE-Agent: Self-Evolution Trajectory Optimization in Multi-Step Reasoning with LLM-Based Agents，arXiv:2508.02085（v1 2025-08-04，v6 2025-11-03；NeurIPS 2025 接收，见 Awesome-Issue-Solving 列表标注 "NeurIPS'25"）[^1^][^2^]
- **仓库**：https://github.com/JARVIS-Xs/SE-Agent ，**286 stars（2026-08-20），MIT License，Python**（README 明确 "This project is licensed under the MIT License"）[^3^]
- **核心自进化机制**：在轨迹（trajectory）层面做进化，而非改模型权重。先以 5 种规划策略 + 变异生成 10 条多样"pilot trajectories"，再迭代三种算子：**Revision**（反思驱动的单轨迹定向改进）、**Recombination**（跨轨迹 Crossover / Transfer / Restructuring 重组）、**Refinement**（多维奖励 TaskCompletion+ReasoningQuality+Efficiency 评估，质量-多样性平衡选精英）[^4^][^5^]。论文原文："SE-Agent is designed to be seamlessly integrated as a plug-and-play module within existing frameworks. Here, we choose SWE-Agent as the basis for subsequent experiments."[^5^]
- **基准表现**：SWE-bench Verified 上跨 5 个 LLM 相对提升最高 55%；Claude-3.7-Sonnet 达 61.2%；Claude-4-Sonnet 达 80.0%（基于 2025-05-22 版 SWE-Agent 基线 66.6%）；消融显示去掉任一算子 Pass@1 均下降；独有解决 12 个其他框架均无法解决的实例[^1^][^5^]
- **即插即用程度**：★★★★。作为 SWE-Agent 之上的插件模块；仓库提供 `SE/README.md` 框架文档、`SE/operators.md` 算子开发指南、`instruction.md` 使用说明、`pytest` 测试与 demo 模式[^3^]
- **二次开发入口**：`SE/operators.md`（算子级扩展，可自写进化算子）；配置候选轨迹数、API 成本预算
- **领域定制方式**：改 planning 策略 prompt、奖励函数维度；对自有仓库可把"通过内部测试"纳入 Refinement 奖励
- **局限**：每个 issue 要跑 10 条轨迹 × 多轮进化，API 成本数倍于单发 agent；进化基于同一 issue 内的轨迹池，**不跨 issue 积累经验**（与 SWE-Exp 互补）

## 2. Live-SWE-agent（边干活边自进化，2025-11）

- **论文**：Live-SWE-agent: Can Software Engineering Agents Self-Evolve on the Fly? arXiv:2511.13646（2025-11-17，被引 77）[^6^]
- **仓库**：https://github.com/OpenAutoCoder/live-swe-agent ，**452 stars（2026-08-20），MIT License，Python**；2025-11-17 发布 1.0.0[^7^]
- **核心自进化机制**：首个"运行时即时自进化"SWE agent。从仅有 bash 的 mini-SWE-agent 出发，在解题循环中**自主合成、修改、执行自定义工具**（编辑器、代码搜索、领域分析器，形式为可执行脚本）；关键设计仅两处：(1) 初始 prompt 加入工具创建指令与示例；(2) 每次环境反馈后附加轻量"step-reflection"消息，显式询问"现在创建/修改一个工具是否能加速进展"。原文："This mechanism leaves the underlying scaffold unchanged, requires no offline training, and is agnostic to the underlying LLM."[^8^]
- **基准表现**：SWE-bench Verified 75.4%（无论文外 test-time scaling，v3 摘要口径 77.4%）；Claude Opus 4.5 后端 79.2%、Gemini 3 Pro 77.4%（官方 leaderboard）；SWE-Bench Pro 45.8%（发布时最佳已知结果）；对比离线自改进 agent：Verified-60 子集 65.0% vs DGM 53.3%，且零离线成本。消融：去掉工具创建 62.0% → 仅 prompt 提示 64.0%（平均造 2.92 个工具）→ 完整反思机制 76.0%（3.28 个工具）[^6^][^7^][^9^]
- **即插即用程度**：★★★★★。本质是"prompt 补丁 + mini-SWE-agent"，可移植到任何 agent loop；官方维护模型 leaderboard
- **二次开发入口**：初始 prompt / 反思消息模板（论文附录 D 全文给出）；工具可序列化保存（论文 Future Work 明确提出 "serializing, retaining, and reusing synthesized tools ... as persistent skills"，尚未内置，是二次开发最自然的切入点）[^10^]
- **领域定制方式**：在初始 prompt 中注入领域工具示例（如你工程的构建/测试命令）；工具天然"按需生成、可为特定 issue 专用"
- **局限**：弱模型（GPT-5-Nano）上用不好工具创建反而掉点，强模型才有最高 22.6% 相对增益[^11^]；工具默认不跨任务持久化；agent 自写自执行代码，必须在沙箱中运行

## 3. OpenHands（原 OpenDevin）：经验复用与插件/技能体系

- **仓库**：https://github.com/OpenHands/OpenHands （原 All-Hands-AI/OpenHands，已迁移组织），**84,549 stars（2026-08-20），MIT License，Python + TypeScript**[^12^]
- **自进化/经验复用机制**（OpenHands 本体不是"自进化 agent"，但提供了**最完整的经验沉淀基础设施**）：
  1. **Skills 体系**（原 Microagents 升级）：`KnowledgeMicroagent` → 关键词触发型 Knowledge Skill；`RepoMicroagent` → 常驻型 Repository Skill。官方推荐在仓库根放 `AGENTS.md`（项目目的、安装、结构、开发规范，始终注入 system prompt）；旧路径 `.openhands/microagents/` 仍兼容但已废弃，新标准为 `.agents/skills/`[^13^]
  2. **agent-memory 技能**：官方扩展目录中的 `agent-memory` skill——"Persist and retrieve repository-specific knowledge using AGENTS.md files"，提供 `/remember` 命令，把会话中学到的仓库知识写回 AGENTS.md[^14^]
  3. **Extensions 注册中心**：[OpenHands/extensions](https://github.com/OpenHands/extensions)（MIT），含 `add-skill`（从 GitHub 导入 skill）、`agent-creator`（用 Markdown 无代码创建子 agent）、`agent-sdk-builder`、`code-review`、`pr-review`、`qa-changes`（真实运行代码验证 PR）、`onboarding`（评估仓库 agent-readiness 并生成 AGENTS.md）等[^14^]
  4. **Automations / Agent Canvas**：定时或 webhook 触发的无人值守任务（PR triage、夜间安全扫描、docs 同步），agent 可在 Docker/VM/云后端运行[^12^]
- **基准表现**：OpenHands CodeAct 系列长期在 SWE-bench Verified 上榜（2024 年 CodeAct 2.1 约 53%；2025-2026 各版本随模型更新，本次未核实最新确切数字，标注"未查到权威最新值"）
- **即插即用程度**：★★★★★（`npm i -g @openhands/agent-canvas` 或 Docker 一键；模型无关 BYOM）[^12^]
- **二次开发入口**：OpenHands Software Agent SDK（自定义工具/LLM 配置/会话）、skills 目录、MCP 集成、REST API
- **领域定制方式**：AGENTS.md + 仓库级 skills + 自定义 MCP 工具 + automations 模板；与"superpower skill"理念天然同构，可直接迁移
- **局限**：经验复用依赖人工/`/remember` 触发写 AGENTS.md，**不是自动从轨迹蒸馏**（自动化蒸馏需接 SWE-Exp/SAGE 类研究方案）；无沙箱模式运行时 agent 拥有宿主机完整文件系统权限（官方文档明确警告）[^12^]

## 4. SWE-agent / mini-SWE-agent（Princeton & Stanford）：轨迹机制与基座价值

- **仓库**：https://github.com/SWE-agent/SWE-agent **20,087 stars**；https://github.com/SWE-agent/mini-swe-agent **6,629 stars（均为 2026-08-20），均 MIT License，Python**[^15^][^16^]
- **与自进化的关系**：本体**不内建经验复用**；其价值在于：
  - **轨迹是一等公民**：mini-SWE-agent "Every step appends to a flat message list, making the trajectory identical to what the model sees — a property that makes it trivially debuggable and straightforward to use as a fine-tuning dataset"[^17^]
  - **是自进化方案的标准基座**：Live-SWE-agent 直接以 mini-SWE-agent 为起点[^8^]；SE-Agent 以 SWE-Agent 为底座[^5^]
  - 配套生态：SWE-smith（训练数据生成）、SWE-ReX（沙箱执行）、SWE-Gym（训练 agent 与验证器）构成"从自己仓库造经验数据→微调/RL"的链路[^18^]
  - 全量 SWE-agent 行为由单 YAML 配置（工具、任务定义、模型路由、上下文策略），研究友好[^19^]
- **基准表现**：mini-SWE-agent 官方口径 "100 line AI agent that still gets 65% on SWE-bench verified"，2026 年报道称同一前沿模型下 >74%、超 Claude Code 脚手架 6 个百分点[^18^][^17^]
- **即插即用程度**：★★★★★（`pip install mini-swe-agent`）
- **二次开发/领域定制**：mini 版 ~100 行核心，任意改；YAML 定义工具与任务；可用 SWE-smith 从**自己的仓库**合成 issue-修复任务做领域适配
- **局限**：无内建跨任务记忆；全量 SWE-agent 配置复杂，官方已建议新用户从 mini 入手[^19^]

## 5. SWE-Exp（经验驱动 issue 修复，2025-07）

- **论文**：SWE-Exp: Experience-Driven Software Issue Resolution，arXiv:2507.23361（v1 2025-07-31，v2 2026-02）[^20^]
- **仓库**：https://github.com/cslsolow/SWE-Exp （原 YerbaPage/SWE-Exp，已迁移），**44 stars（2026-08-20），Apache-2.0，Python**；基于 SWE-Search/moatless-tree-search 扩展[^21^]
- **核心自进化机制**：**多面经验库（experience bank）+ 四阶段流水线**：(1) 无经验跑轨迹收集；(2) 经验萃取——先抽 issue 类型作检索键，再由 ExpAgent 从成功/失败轨迹分别蒸馏"Comprehension 经验"（问题理解/诊断模式）与"Modification 经验"（修改策略/避坑）；(3) 两阶段检索——multilingual-e5-large-instruct  embedding 余弦相似度取 top-10，再由 reranker agent 选 k=1；(4) 复用——Instructor（战略）+ Assistant（执行）双 agent 架构注入经验。防泄露措施："we exclude all experiences originating from the same code repository and generated after the target instance"[^22^][^21^]
- **基准表现**：SWE-bench Verified 41.6% Pass@1（DeepSeek-V3，v1 口径，开源框架 SOTA）；v2 报告 Claude 4 Sonnet 73%[^20^][^22^]。消融：去 Comprehension 经验 -3.2%、去 Modification 经验 -2.6%、去双 agent -2.2%[^22^]
- **即插即用程度**：★★★。研究代码，`workflow.py --experience` 可跑通完整管线，但要先在目标分布上跑 Stage 1-2 建库
- **二次开发入口**：`moatless/experience/` 模块（exp_agent、select_agent、instructor、prompts 全部可读可改）[^21^]
- **领域定制方式**：**最契合"管理自己的工程"**——在自己仓库的历史 issue/PR 上跑轨迹→蒸馏出本仓库专属经验库（如"本项目的参数校验惯例"），后续 issue 修复自动检索复用
- **局限**：依赖 MCTS 底座，计算量大；经验质量依赖底座 agent 先能解出一部分题（冷启动）；仓库小、文档以论文复现为导向

## 6. Self-play SWE-RL 与 SWE-RL（Meta FAIR，2025-02 / 2025-12）

- **论文**：SWE-RL（arXiv:2502.18449，NeurIPS 2025）；Toward Training Superintelligent Software Agents through Self-Play SWE-RL（arXiv:2512.18552，2025-12-20，Meta FAIR）[^23^][^24^]
- **代码**：**未查到公开仓库**（截至 2026-08-20；多轮检索无官方代码链接）
- **核心机制**：SSR（Self-play SWE-RL）中同一 LLM 分饰两角——**bug 注入者**（在沙箱仓库中制造带测试补丁的形式化 bug 规约）与**修复者**，共享参数、联合 RL 训练，形成难度自适应的对抗课程；完全摆脱人工 issue/测试数据，"仅需代码仓库与依赖"[^24^][^25^]
- **基准表现**：论文称在 SWE-bench 系列上显著超过基于人工数据的 RL（具体数字以论文为准；二手综述称 "significant performance improvements over human-data RL"）[^25^]
- **落地评估**：对个人工程场景**不可直接用**——需要 RL 训练基础设施与可执行测试环境；但方法论可借鉴："在自己仓库上自动注入 bug + 自动修复" 可作为生成领域训练/评测数据的方式（开源近似：SWE-smith、R2E-Gym、SWE-Replay 思路）
- **风险/伦理**：alphaxiv 综述指出 "Allowing an AI to learn how to 'inject bugs' and 'weaken tests' is a double-edged sword … must be developed within secure, sandboxed environments"[^26^]

## 7. SWE-Replay（测试时轨迹回收，2026-02）

- **论文**：SWE-Replay: Efficient Test-Time Scaling for Software Engineering Agents，arXiv:2601.22129（2026-02-05）[^27^]
- **代码**：**未查到公开仓库**
- **机制**：回收已采样轨迹，在"关键中间步"（按仓库探索潜力与推理重要性选择，而非 LLM-as-Judge）分叉复用，平衡探索/利用
- **表现**：SWE-bench Verified 成本降最高 17.4%、解决率升最高 3.8%；在 Pro 与 Multilingual 上泛化一致[^27^]
- **落地评估**：作为"同一 issue 多次尝试时降本"的策略可参考；对个人场景价值中等

## 8. 补充方案（同属"编码 agent 自进化"谱系，高相关）

### 8.1 SICA（Self-Improving Coding Agent，ICLR 2026）
- 仓库：https://github.com/MaximeRobeyns/self_improving_coding_agent ，**386 stars，MIT，Python**[^28^]
- 机制：首个完全自指 coding agent——消除 meta-agent 与 target-agent 界限，agent 直接编辑自身完整 Python 代码库；循环 = 基准评测 → 最优者晋升 → 档案分析子 agent 提改进 → 开发者子 agent 实现 → 独立验证
- 表现：SWE-bench Verified 50 题随机子集 17%→53%（15 轮迭代）；自主发明了 Smart Editor、AST Symbol Locator 等工具[^29^]
- 局限：离线迭代成本高；重要负结果——对强推理模型（o3-mini-high），脚手架反而可能**打断**内部推理链（AIME/GPQA 上无增益）[^29^]

### 8.2 Darwin-Gödel Machine（DGM，ICLR 2026）
- 仓库：https://github.com/jennyzzt/dgm ，**2,239 stars，Apache-2.0，Python**[^30^]
- 机制：达尔文式开放进化 + 哥德尔机思想：agent 自我修改代码并用编码基准实证每步改动，维护不断增长的 agent 档案库，从中采样 parents 生成新变体
- 表现：SWE-bench 20.0%→50.0%；Polyglot 14.2%→30.7%；发现的改进可跨模型（Claude 3.5→o3-mini/3.7）与跨语言迁移[^30^][^31^]
- 局限：80 轮迭代 × 多并行的离线进化，成本极高；实验全程沙箱 + 人工监督[^30^]

### 8.3 GenericAgent（技能结晶，2026 热门）
- 仓库：https://github.com/lsdefine/GenericAgent ，**13,810 stars，MIT，Python**[^32^]
- 机制：~3K 行种子代码 + 9 原子工具 + ~100 行 agent loop；**技能结晶**——"New task → Autonomous exploration → Execution path crystallization → Memory storage → Direct reuse next time"；5 层记忆（L0 元规则 / L1 索引 / L2 全局事实 / L3 任务技能 SOP / L4 会话归档）；`code_run` 可运行时自造工具并固化为永久工具；宣称仓库自身 388 个 commit 全由 agent 完成[^33^]
- 基准：无 SWE-bench 数据（通用 OS 控制 agent，非 SE 专用）
- 落地评估：技能结晶 + 分层记忆的设计对"个人工程管家"很有参考价值，代码极小易于二开；但浏览器/OS 级控制能力超出编码场景需要，且缺少测试驱动验证闭环

### 8.4 Hermes Agent + hermes-agent-self-evolution（Nous Research，2026）
- 仓库：https://github.com/NousResearch/hermes-agent **233,265 stars（2026-08-20），MIT，Python/TS**；配套 https://github.com/NousResearch/hermes-agent-self-evolution （MIT）[^34^][^35^]
- 机制：内置闭环学习——复杂任务后自动创建 skill（agentskills.io 开放标准）、skill 使用中自改进、周期性记忆提醒、FTS5 跨会话召回；配套自进化项目用 **DSPy + GEPA（遗传-帕累托 prompt 进化）**对 skills/工具描述/系统 prompt/代码做反思式进化搜索，每个变体须过 pytest 全量通过与体积门限（skill ≤15KB、工具描述 ≤500 字符），单次优化约 $2–10、无需 GPU[^35^][^36^]
- 局限：无公开 SWE-bench 成绩；有批评指出其"自改进"实为"文本上的进化搜索"而非权重学习[^37^]；面向个人助理而非仓库级 issue 修复

### 8.5 综述资源
- Self-Evolving Coding Agents 综述（arXiv:2608.03392，2026-08）与配套清单 https://github.com/zhouhao1024/Awesome-Self-Evolving-Coding-Agents ：以"什么在进化（框架/记忆/技能/工具/模型/协作结构）× 何时进化 × 什么软件证据驱动"组织全领域[^38^]
- Awesome-Issue-Solving（ZhonghaoJiang）：按 Scaffold/Memory/Self-Evolution 分类的 issue 修复文献表[^2^]

---

## 9. 落地到"管理我自己的工程"场景的分析

用户场景三要素的匹配度：

1. **仓库级理解**：SWE-Exp（经验库含仓库专属修改惯例）、OpenHands AGENTS.md/Skills、SWE-smith（从自有仓库合成任务）最直接；Live-SWE-agent 的领域专用分析工具（如论文中为 MARC 文件格式现场造分析器[^9^]）证明运行时适应单仓库可行。
2. **Issue 驱动**：SWE-agent/mini-SWE-agent、OpenHands、SWE-Exp、SE-Agent 全是 issue→patch 原生架构，可直接对接 GitHub Issues/Linear。
3. **测试驱动验证**：SWE-bench 式 F2P 测试验证是所有方案的内置闭环；OpenHands `qa-changes` 插件（真实运行代码验证 PR）、hermes-agent-self-evolution 的"pytest 全过才接受变体"门控，是工程化最成熟的两例[^14^][^36^]。

**推荐组合（按投入由小到大）**：
- **L0（本周可上）**：OpenHands + AGENTS.md + agent-memory（`/remember`）+ 自建 skills——零研究风险，先把"经验写盘"跑起来。
- **L1（轻量自进化）**：mini-SWE-agent + Live-SWE-agent 的 prompt 补丁（工具创建指令 + 步级反思），并自行实现论文 Future Work 建议的**工具序列化复用**（把生成的好工具存进你工程的 `.agents/skills/` 或 superpower skill 目录）——这是把 Live-SWE-agent 从"单次进化"变成"跨任务积累"的关键二开点，代码量小。
- **L2（经验库）**：照 SWE-Exp 四阶段范式，在自己仓库的历史 issue/修复轨迹上蒸馏"理解经验 + 修改经验"，用 e5 embedding + LLM rerank 检索注入 Cursor/OpenHands 的系统 prompt；注意复用其防泄露策略（排除同仓库晚于目标实例的经验）。
- **L3（重型，研究向）**：SE-Agent 算子接到现有 agent 上提升单 issue 成功率（成本高）；SICA/DGM 式自我改代码仅建议在沙箱副本中实验。

## 10. 局限性与风险记录

1. **Eval 泄露/记忆化争议**：
   - "The SWE-Bench Illusion"（arXiv:2506.12286）：SOTA 模型仅凭 issue 描述即可达 76% 的 buggy 文件路径识别率，非 SWE-bench 仓库上仅 53%；SWE-bench 上连续 5-gram 重叠最高 35% vs 其他基准 18%——头部分数含显著记忆成分[^39^]
   - OpenAI 已宣布不再评测 SWE-bench Verified（训练数据污染 + 有缺陷的测试奖励投机），推荐 SWE-bench Pro[^40^]
   - SWE-bench+：32.67% 成功 patch 的 issue 文本中直接存在解法泄露；SWE-bench issue #465 暴露 git history 可访问 gold patch[^41^]
   - UTBoost：Verified 中 169 个错误 patch 被误判为正确，修正测试后 24.4% 的榜单排名变动[^40^]
   - ⇒ 对本文所有 SWE-bench 数字应打折看待；评估自己的工程时，用**私有/新产生 issue** 验证更可靠。
2. **成本**：SE-Agent 默认 10 条候选轨迹 + 多轮进化；DGM 80 轮离线进化；SSR 需 RL 设施；SWE-Exp 需先跑全量轨迹建库。Live-SWE-agent 是唯一"零离线成本"且成本仅略增的方案[^9^]。
3. **安全风险**：
   - 自改代码/自造工具的 agent 必须沙箱运行（SICA README 强调 "always run the agent in the provided Docker container"[^28^]；OpenHands 无沙箱模式官方警告 agent 有宿主机完整文件系统权限[^12^]）
   - SSR 的"注毒/削弱测试"能力是双刃剑[^26^]
   - 自进化产物（skills、AGENTS.md、工具脚本）需要审计与回滚机制——可参考 hermes-agent-self-evolution 的"pytest 门控 + 体积上限 + PR 审阅"模式[^36^]，或社区 Evolution Ledger 类"假设→变更→评测→回滚"追加式审计轨迹[^42^]
4. **能力依赖**：Live-SWE-agent 在弱模型上退化[^11^]；SICA 发现强推理模型上复杂脚手架可能反而有害[^29^]——自进化模块的收益高度依赖底座模型，需以自家模型实测为准。
5. **经验库维护**：技能/经验膨胀会带来检索噪声与冲突（社区已提出技能冲突与记忆混乱问题[^43^]），SWE-Skills-Bench（2026）等工作正在系统评估"skills 是否真有用"。

---

## 参考来源

[^1^]: arXiv:2508.02085 SE-Agent 摘要页，https://arxiv.org/abs/2508.02085 （2025-08-04，访问 2026-08-20）。摘录："integrating SE-Agent delivers up to 55% relative improvement, achieving state-of-the-art performance among all open-source agents on SWE-bench Verified."
[^2^]: ZhonghaoJiang/Awesome-Issue-Solving，https://github.com/ZhonghaoJiang/Awesome-Issue-Solving （访问 2026-08-20）。SE-Agent 标注 "NeurIPS'25"；SWE-Exp 标注 @Memory/@Self-Evolution 分类。
[^3^]: JARVIS-Xs/SE-Agent README，https://github.com/JARVIS-Xs/SE-Agent （访问 2026-08-20）。摘录："This project is licensed under the MIT License"；提供 SE/operators.md、instruction.md、pytest。Stars 286（2026-08-20 页面抓取）。
[^4^]: SE-Agent 实验设计案例（arXiv:2608.03501 附录 C.1），https://arxiv.org/html/2608.03501v1 （2026-08-04）。详述初始池 N=10、Revision/Recombination/Refinement 与奖励构成。
[^5^]: SE-Agent HTML v6，https://arxiv.org/html/2508.02085v6 （2025-11-03）。摘录："SE-Agent is designed to be seamlessly integrated as a plug-and-play module within existing frameworks"；80.0% with Claude-4-Sonnet（基线 66.6%）。
[^6^]: arXiv:2511.13646 摘要页，https://arxiv.org/abs/2511.13646 （2025-11-17，Cited by 77）。摘录："can achieve an impressive solve rate of 77.4% without test-time scaling … 45.8% [on SWE-Bench Pro]"。
[^7^]: OpenAutoCoder/live-swe-agent README，https://github.com/OpenAutoCoder/live-swe-agent （访问 2026-08-20）。News：Claude Opus 4.5 79.2%、Gemini 3 Pro 77.4%、Pro 45.8%、1.0.0 发布。Stars 452；MIT License（页面抓取，2026-08-20）。
[^8^]: Live-SWE-agent HTML v3 §1-2，https://arxiv.org/html/2511.13646v3 （2025-11-24）。摘录："A lightweight step-reflection prompt repeatedly asks the agent whether creating or revising a tool would accelerate progress … leaves the underlying scaffold unchanged, requires no offline training, and is agnostic to the underlying LLM."
[^9^]: Live-SWE-agent HTML v1，https://arxiv.org/html/2511.13646v1 （2025-11-17）。消融：62.0% → 64.0%（2.92 工具）→ 76.0%（3.28 工具）；Verified-60 65.0% vs DGM 53.3%；MARC 文件分析器案例。
[^10^]: emergentmind Live-SWE-agent 主题页，https://www.emergentmind.com/topics/live-swe-agent （2025-11-19）。Future work："serializing, retaining, and reusing synthesized tools and emergent strategies as persistent 'skills' across tasks."
[^11^]: themoonlight 论文评述，https://www.themoonlight.io/en/review/live-swe-agent-can-software-engineering-agents-self-evolve-on-the-fly （2025-11-19）。弱模型 GPT-5-Nano 退化；强模型最高 22.6% 相对增益。
[^12^]: OpenHands/OpenHands README，https://github.com/All-Hands-AI/OpenHands （重定向至 OpenHands/OpenHands；访问 2026-08-20）。Agent Canvas、Automations、Docker/quickstart；警告 "the agent will have full access to your filesystem!"。Stars 84,549（2026-08-20 页面抓取）。MIT License 另有佐证：NousResearch/hermes-agent issue #477（2026-03-06）称 "OpenHands (formerly OpenDevin) is an MIT-licensed, open-source … platform"。
[^13^]: 掘金/51CTO《拆解 OpenHands（14）Microagents》，https://juejin.cn/post/7616650313060401203 （2026-03-13）。摘录："KnowledgeMicroagent is the legacy name for what is now called a Knowledge Skill … The recommended approach is to create an AGENTS.md … Legacy paths (.openhands/microagents/) are still supported but deprecated in favor of .agents/skills/"。
[^14^]: OpenHands/extensions 目录，https://github.com/OpenHands/extensions （访问 2026-08-20）。agent-memory："Persist and retrieve repository-specific knowledge using AGENTS.md files … `/remember`"；另有 add-skill、agent-creator、qa-changes、onboarding 等。MIT License。
[^15^]: SWE-agent/SWE-agent，https://github.com/SWE-agent/SWE-agent （访问 2026-08-20）。Stars 20,087；MIT（README："MIT. Check LICENSE."）；NeurIPS 2024。
[^16^]: SWE-agent/mini-swe-agent，https://github.com/SWE-agent/mini-swe-agent （访问 2026-08-20）。Stars 6,629；MIT（stackquadrant 2026-03 同步数据：3.3k stars、MIT、v2.2.7，https://stackquadrant.com/repos/mini-swe-agent ）。
[^17^]: byteiota《mini-swe-agent: 100 Lines That Beat Claude Code on SWE-bench》，https://byteiota.com/mini-swe-agent-100-lines-that-beat-claude-code-on-swe-bench/ （2026-07-20）。摘录："Every step appends to a flat message list, making the trajectory identical to what the model sees … straightforward to use as a fine-tuning dataset"；"scores over 74% on SWE-bench Verified … beats Claude Code's framework by six percentage points"。
[^18^]: github.com/SWE-agent 组织页，https://github.com/SWE-agent （访问 2026-08-20）。摘录："mini-SWE-agent, a 100 line AI agent that still gets 65% on SWE-bench verified!"；生态含 SWE-smith、SWE-ReX、sb-cli。
[^19^]: copilot-alternatives SWE-agent 页，https://copilot-alternatives.com/alternative/swe-agent/ （访问 2026-08-20）。摘录："The entire agent behavior is governed by a single YAML configuration file"；"The SWE-agent team now recommends mini-swe-agent for most use cases."
[^20^]: SWE-Exp alphaxiv 页，https://www.alphaxiv.org/abs/2507.23361 （2026-02-02）。四阶段流水线与经验分类描述。
[^21^]: cslsolow/SWE-Exp（原 YerbaPage/SWE-Exp），https://github.com/YerbaPage/SWE-Exp （重定向；访问 2026-08-20）。Stars 44；Apache-2.0（页面抓取，2026-08-20）。README 完整给出 Stage 1–4 命令与 `moatless/experience/` 结构；"built upon … @aorwall/moatless-tree-search"。
[^22^]: SWE-Exp HTML v2，https://arxiv.org/html/2507.23361v2 （2026-02-02）。摘录："achieves a Pass@1 resolution rate of 73% using Claude 4 Sonnet"；"To prevent data leakage, we exclude all experiences originating from the same code repository and generated after the target instance"；消融 -3.2%/-2.6%/-2.2%。v1 摘要（liner 评述，2025-07-31）："41.6% Pass@1 … under open-source agent frameworks"，https://liner.com/review/sweexp-experiencedriven-software-issue-resolution 。
[^23^]: SWE-RL 引用记录（arXiv:2502.18449，NeurIPS 2025），见 arXiv:2602.10356 参考文献："Wei, Y., … Swe-rl: Advancing Ilm reasoning via reinforcement learning on open software evolution."
[^24^]: Self-play SWE-RL alphaxiv 页，https://www.alphaxiv.org/abs/2512.18552 （访问 2026-08-20）。arXiv:2512.18552（2025-12-20）。摘录（HTML v2）：框架"iteratively inject, repair, and validate software bugs of increasing complexity"。
[^25^]: emergentmind SSR 论文页，https://www.emergentmind.com/papers/2512.18552 （2025-12-21）。摘录："eliminates dependency on human-curated data … Empirical results on SWE benchmarks demonstrate significant performance improvements over human-data RL."
[^26^]: alphaxiv SSR 伦理节，https://www.alphaxiv.org/abs/2512.18552 （2026-06-01 更新）。摘录："Allowing an AI to learn how to 'inject bugs' and 'weaken tests' is a double-edged sword … must be developed within secure, sandboxed environments."
[^27^]: SWE-Replay HTML v2，https://arxiv.org/html/2601.22129v2 （2026-02-05）。摘录："reduces computational costs by up to 17.4% while improving resolve rates by up to 3.8% on SWE-Bench Verified … consistent generalizability towards … SWE-Bench Pro and SWE-Bench Multilingual."
[^28^]: MaximeRobeyns/self_improving_coding_agent，https://github.com/MaximeRobeyns/self_improving_coding_agent （访问 2026-08-20）。Stars 386；MIT（页面抓取）。README："always run the agent in the provided Docker container."
[^29^]: SICA 论文（arXiv:2504.15228）与综述引文，https://arxiv.org/pdf/2504.15228 ；https://arxiv.org/html/2608.08466v1 （2026-08-03，附录 B.2.1）。摘录："performance improves from 17% to 53% … on a random subset of SWE Bench Verified"；负结果："Agent Framework Saturation … scaffolding may interrupt rather than augment internal reasoning chains."
[^30^]: DGM HTML v3，https://arxiv.org/html/2505.22954v3 （2026-03-12）。摘录："increasing performance on SWE-bench from 20.0% to 50.0%, and on Polyglot from 14.2% to 30.7% … All code is open-sourced at https://github.com/jennyzzt/dgm"；80 轮迭代；沙箱+人工监督。
[^31^]: Sakana AI DGM 博客，https://sakana.ai/dgm/ （2025-05-30）。跨模型/跨语言迁移描述。
[^32^]: lsdefine/GenericAgent，https://github.com/lsdefine/GenericAgent （访问 2026-08-20）。Stars 13,810；MIT（README："Distributed under the MIT License"）。
[^33^]: sotaaz《Self-Evolving AI Agents — The New Paradigm of 2026》，https://sotaaz.com/post/self-evolving-agents-en （2026-04-19）。Stars 4,300+（2026-04 口径，现已 13,810）；5 层记忆表；"Of 388 commits, none were manually typed in a terminal by a human."
[^34^]: NousResearch/hermes-agent，https://github.com/NousResearch/hermes-agent （访问 2026-08-20）。Stars 233,265；MIT（页面抓取）。摘录："A closed learning loop — Agent-curated memory with periodic nudges. Autonomous skill creation after complex tasks. Skills self-improve during use."
[^35^]: NousResearch/hermes-agent-self-evolution，https://github.com/NousResearch/hermes-agent-self-evolution （访问 2026-08-20）。摘录："uses DSPy + GEPA … No GPU training required … ~$2-10 per optimization run"；"gates every variant on full pytest pass and size limits (skills ≤ 15 KB, tool descriptions ≤ 500 chars)"（另见 arXiv:2605.22794 参考文献条目）。MIT。
[^36^]: 同 [^35^]；流程图 "Best variant ──► PR against hermes-agent"。
[^37^]: Towards AI《Hermes Agent Doesn't Learn. It Mutates Strings.》，https://pub.towardsai.net/hermes-agent-doesnt-learn-24fb958f18d7 （2026-06-26）。批评其"self-improvement"为文本进化搜索。
[^38^]: Self-Evolving Coding Agents 综述，https://arxiv.org/pdf/2608.03392 （2026-08）。清单：https://github.com/zhouhao1024/Awesome-Self-Evolving-Coding-Agents 。摘录："we develop an object-centered taxonomy that characterizes what evolves … when evolution occurs and what software-specific evidence drives it."
[^39^]: SWE-Bench Illusion 数据转引，https://github.com/Chipagosfinest/software-factory/blob/main/docs/swe-bench-ecosystem.md （2026-04-27）与 MDPI 综述（2026-06-15，https://www.mdpi.com/1999-5903/18/6/326 ）。原文 arXiv:2506.12286。摘录："up to 76% accuracy identifying buggy file paths using only issue descriptions … only 53% on repos not in SWE-bench … 35% consecutive 5-gram overlap vs 18%"。
[^40^]: 同 [^39^] 文档 §3.1-3.2：OpenAI 退出 SWE-bench Verified（https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/ ）；UTBoost："176 incorrect patches in Lite and 169 in Verified … 24.4% of Verified leaderboard rankings changed"。
[^41^]: arXiv:2603.21454 §2，https://arxiv.org/html/2603.21454v1 （2026-03-23）。摘录："SWE-bench+ … finding 32.67% of successful patches involved direct solution presence … Issue #465 revealed git history leakage enabling models to access gold patches."
[^42^]: GitHub Topics: self-evolution，https://github.com/topics/self-evolution?l=javascript （2026-08-03 快照）。含 "Evolution Ledger — append-only, tamper-evident audit trail for AI agent self-evolution: hypothesis → change → eval → rollback" 等社区项目（质量未逐一核实）。
[^43^]: GenericAgent 实作笔记（rocky-ai.one-wall.art，2026-04-17），https://rocky-ai.one-wall.art/posts/046-lsdefine-genericagent 。提出技能树膨胀后的记忆精度/技能冲突问题；另见 SWE-Skills-Bench（arXiv:2603.15401，2026）"Do agent skills actually help in real-world software engineering?"。

---

### 附：未查到/待核实项
- Self-play SWE-RL（arXiv:2512.18552）与 SWE-Replay（arXiv:2601.22129）的公开代码仓库：未查到。
- OpenHands 当前版本在 SWE-bench Verified 的权威最新数字：未查到（各版本随模型变化）。
- hermes-agent-self-evolution 仓库 star 数：未单独核实（主仓 233,265 已核实）。
- SE-Agent 的 NeurIPS 2025 正式论文集链接：以 Awesome-Issue-Solving 列表 "NeurIPS'25" 标注与 arXiv v6 为准，未打开 OpenReview 页面核实。

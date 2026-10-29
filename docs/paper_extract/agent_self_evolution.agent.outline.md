# Agent 自进化开源方案调研报告：可直接集成与二次开发的选型指南

## 摘要（约 400 字，无编号）
### 核心结论
#### 自进化可在五个层面落地，2026 年「Skill 形态」已取代「重型框架」成为即插即用的最佳载体
#### 验证环（evaluator/eval 集）是所有自进化方案的公共地基，应先于任何框架建设
#### 推荐「三层装配」：Skill 经验层 + GEPA/OpenEvolve 优化层 + mem0 记忆层，全部 MIT/Apache 可二开

## 1. 调研背景、需求与评估框架（约 1200 字，1 表）
### 1.1 用户需求与场景界定
#### 1.1.1 用户场景：Cursor + GPT + superpower skill 管理自有工程，目标是加入可二开、可领域定制的自进化模块
#### 1.1.2 三个硬性约束：开源可直接使用、支持二次开发、支持领域专用改进
### 1.2 自进化的五层技术模型
#### 1.2.1 prompt/记忆/技能/代码/权重五层的成本-风险-收益结构（表：五层对比）
#### 1.2.2 权威综述 taxonomy：What/When/How/Where 框架（arXiv:2507.21046）与 2026 年「参数 vs 脚手架」更新
### 1.3 评估维度与调研方法
#### 1.3.1 五维评估：即插即用程度、二次开发入口、领域定制方式、影响力（stars/论文）、license 安全性

## 2. 方案全景：五条技术路线与演进脉络（约 1500 字，1 表）
### 2.1 五层路线总览与代表方案地图
#### 2.1.1 每层 3-5 个代表方案一览（表：路线×代表方案×一句话定位）
### 2.2 2023-2026 学术与工程演进脉络
#### 2.2.1 从 Voyager 技能库（2023）到 Agent Skills 标准（2025-12）的范式转移
#### 2.2.2 2026 年生态「哑铃型」结构：极轻 skill 补丁与极重权重训练两端成熟，中间框架层风险最高

## 3. 路线一：Skill 形态的自进化组件——与用户现有工作流零冲突（约 2500 字，2 表）
### 3.1 Agent Skills 开放标准与运行时兼容性
#### 3.1.1 agentskills.io 标准（2025-12 发布）已被 Cursor/Claude Code/Codex/OpenCode 等约 40 个运行时采纳；Cursor 2.4 原生支持 SKILL.md
### 3.2 自进化 skill 代表方案
#### 3.2.1 Hermes-Mind-Skill：Cursor 原生 hooks，任务后反思→人工确认→沉淀 SKILL.md（MIT）
#### 3.2.2 pskoett self-improvement：纠错/失败自动记录 .learnings 并晋升为规则（约 280★）
#### 3.2.3 darwin-skill 棘轮式 skill 优化器与官方 skill-creator 的 eval 基建
#### 3.2.4 superpowers 生态（2026-06 底超 20 万★，MIT）及其 meta-skill writing-skills 的自进化边界
### 3.3 本路线对比与接入方式
#### 3.3.1 对比表：各 skill 的机制/兼容性/二开方式；接入 Cursor 的具体路径（.cursor/rules、.claude/skills 兼容读取）

## 4. 路线二：单点优化器——对 prompt/skill/代码做可验证优化（约 2800 字，2 表，1 图）
### 4.1 GEPA：反思式进化优化器
#### 4.1.1 GEPA 独立库（约 6.2k★，ICLR 2026 Oral）：GEPAAdapter 可优化任意文本组件，单任务约 $20 级成本
### 4.2 DSPy：prompt 程序化优化的事实标准
#### 4.2.1 DSPy（约 3.4-3.7 万★，MIT）：Signature/Module/Optimizer 体系，MIPROv2+GEPA 双优化器，v3.x 活跃维护
### 4.3 OpenEvolve 与 ShinkaEvolve：进化式代码优化
#### 4.3.1 OpenEvolve（约 7k★，Apache-2.0）：evaluator 接口四形态接入（pip/CLI/库/Docker），MAP-Elites 岛屿进化，每迭代 $0.01-0.6
#### 4.3.2 ShinkaEvolve（Sakana AI）：150 次评估达 SOTA 的样本效率，适合预算受限场景
### 4.4 AFlow 与 EvoAgentX：工作流结构优化
#### 4.4.1 AFlow（ICLR'25，MCTS 搜索 workflow）与 EvoAgentX（3.2k★，MIT，内置六种优化器）作为集成底座
### 4.5 本路线对比
#### 4.5.1 对比表：优化对象/接入成本/优化成本/活跃度（图：优化对象-成本定位图）

## 5. 路线三：框架级自进化系统（约 2800 字，2 表）
### 5.1 技能库自进化
#### 5.1.1 GenericAgent（13.8k★，MIT）：约 3K 行种子代码 + 技能结晶机制，二开成本最低
#### 5.1.2 SkillClaw（2.4k★，MIT，代理模式兼容任意 OpenAI 接口）与 AutoSkill（559★，无 LICENSE 警示）
#### 5.1.3 Voyager 范式（7.2k★，MIT）的历史地位与领域绑定局限
### 5.2 编码 Agent 运行时自进化
#### 5.2.1 Live-SWE-agent（452★，MIT）：即插即用程度最高，单 YAML 的 prompt 补丁实现运行时自造工具，SWE-bench Verified 75-79%
#### 5.2.2 OpenHands（84.5k★，MIT）：AGENTS.md + Skills + /remember 经验沉淀，产品化最成熟
#### 5.2.3 SE-Agent（286★，Verified 80%）与 SWE-Exp（44★，Apache-2.0，四阶段经验库）
### 5.3 自我修改代码（研究向，谨慎落地）
#### 5.3.1 DGM（2.2k★，Apache-2.0，SWE-bench 20%→50%）与 SICA（386★，MIT，17%→53%）
#### 5.3.2 Gödel Agent（209★，MIT，monkey-patch 自指修改）、ADAS（1.6k★，Apache-2.0）、STOP（52★）
### 5.4 本路线对比
#### 5.4.1 对比表：机制/stars/license/基准表现/落地风险

## 6. 路线四：记忆与经验自进化（约 1800 字，1 表）
### 6.1 经验学习方法
#### 6.1.1 ExpeL（236★，Apache-2.0）、Agent Workflow Memory（459★）、SOAR：从轨迹蒸馏可复用经验
### 6.2 记忆系统横评
#### 6.2.1 mem0（63.6k★，Apache-2.0，MCP 可直接挂 Cursor）与 Graphiti/Zep（30.1k★，时序知识图谱）
#### 6.2.2 Hermes Agent（233k★ 数据存疑，MIT）：持久化 skill 系统与 GEPA 进化闭环
### 6.3 记忆失效模式
#### 6.3.1 记忆污染/遗忘/检索噪声（K=4 峰值现象）与工程对策（表：失效模式×对策）

## 7. 路线五：权重级自进化——了解思想，暂不落地（约 1000 字，1 表）
### 7.1 代表工作
#### 7.1.1 SEAL（1.8k★，MIT）、Absolute Zero（1.9k★，MIT）、R-Zero（835★，无 LICENSE）、TTRL（1.1k★，MIT）
### 7.2 可落地性评估
#### 7.2.1 资源门槛（最低 2×80GB GPU，主流 8×A100，SWE-RL 用 512×H100）与非权重路线的 1-2 个数量级差距（表：资源需求对比）

## 8. 综合对比矩阵与选型建议（约 2200 字，3 表，1 图）
### 8.1 总对比矩阵
#### 8.1.1 Top 12 方案横向对比：stars/license/即插即用/二开入口/领域定制/风险（大表+图）
### 8.2 针对用户场景的推荐组合：三层装配
#### 8.2.1 L1 经验自进化层（skill 形态）+ L2 单点优化层（GEPA/OpenEvolve）+ L3 记忆层（mem0 MCP）
### 8.3 渐进落地路线图
#### 8.3.1 L0 轨迹埋点 → L1 eval 集（20-50 条二元判断）→ L2 经验晋升闭环 → L3 优化器纵深

## 9. 风险、护栏与二次开发注意事项（约 1500 字，1 表）
### 9.1 供应链安全
#### 9.1.1 Snyk 测得 13.4% skill 含 critical 安全问题、ClawHavoc 真实投毒事件；自进化会固化污染经验放大爆炸半径
### 9.2 许可证陷阱
#### 9.2.1 CC 非商用（HyperAgents、SWE-RL、Synapse）与无 LICENSE 灰区（AutoSkill、R-Zero、AgentSquare 等）清单
### 9.3 进化失效模式
#### 9.3.1 eval 污染（DGM 伪造测试日志）、沙箱逃逸（STOP）、无验证环的技能进化无效（CoEvoSkills 实验）
### 9.4 护栏设计
#### 9.4.1 晋升前审查 + 沙箱执行 + git 版本化可回滚 + 第三方 skill 先扫描（表：风险×护栏）

## 10. 结论与核心洞察（约 1000 字）
### 10.1 六条跨维度洞察
#### 10.1.1 至 10.1.6：Skill 形态合流、验证环地基、哑铃型生态、Observe-Verify-Retain 闭环标准化、供应链安全一阶化、三层装配推荐

# References
## agent_self_evolution_outline_references_raw.md
- **Type**: Citation collection
- **Description**: 写作阶段各章引用汇集
- **Path**: /mnt/agents/output/agent_self_evolution_outline_references_raw.md

## research/self_evo_dim01.md ~ dim10.md
- **Type**: Research dimension reports
- **Description**: 十个维度的深度调研原始材料
- **Path**: /mnt/agents/output/research/

## research/self_evo_cross_verification.md
- **Type**: Cross-verification
- **Description**: 置信度分级与冲突处理
- **Path**: /mnt/agents/output/research/self_evo_cross_verification.md

## research/self_evo_insight.md
- **Type**: Insights
- **Description**: 六条跨维度洞察
- **Path**: /mnt/agents/output/research/self_evo_insight.md

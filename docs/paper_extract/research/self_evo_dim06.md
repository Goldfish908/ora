# 维度 06：即插即用的 Agent Skill 生态 —— 与 superpowers 同形态的「自进化」skill/插件调研

- 调研日期：2026-08-20（所有 stars 除特别注明外均为该日前后最近可查数据，注明来源日期）
- 独立检索次数：25+ 次（中英文混合，覆盖官方文档、GitHub、arXiv、目录站）
- 说明：GitHub REST API 在调研环境中被限流（`API rate limit exceeded`，2026-08-20 实测），部分 stars 采用二手来源并注明日期；一处（pskoett-ai-skills）为直接打开仓库页实测。

---

## 1. Agent Skills 开放规范（agentskills.io）现状

**事实**：
- Agent Skills 由 Anthropic 创建，2025-12-18 作为开放标准发布；规范已从 `anthropics/skills` 迁出，由厂商中立的 GitHub 组织 `agentskills/agentskills` 治理（Apache-2.0 / CC-BY-4.0）；`anthropics/skills` 中的 spec 文件现为 87 字节 stub："The spec is now located at https://agentskills.io/specification"[^1^]。
- 技能 = 一个目录，必须有 `SKILL.md`（YAML frontmatter + Markdown 指令），可选 `scripts/`、`references/`、`assets/`。Frontmatter 共 6 个字段：`name`、`description` 必填；`license`、`compatibility`、`metadata`、`allowed-tools` 可选。**规范不含凭证、MCP 配置或记忆字段**；渐进式披露（元数据 ~100 tokens → 激活时读正文 → 按需读文件）是规范的一部分[^1^]。
- 跨厂商采纳：截至 2026-06，agentskills.io 客户端展示页列出约 40 个采纳方，包括 Claude Code、Claude.ai、OpenAI Codex（`~/.codex/skills`，`--enable skills`）、ChatGPT（`/home/oai/skills`）、GitHub Copilot、VS Code、**Cursor**、Gemini CLI、Goose、OpenCode、Roo Code、Amp、Factory、Kiro、JetBrains Junie、Mistral Vibe、Spring AI、Databricks、Snowflake 等[^2^][^3^][^4^]。
- 校验工具：`skills-ref validate ./my-skill`（agentskills/agentskills 仓库内的参考实现）[^4^]。
- 注意：Claude Code 私有扩展字段（`when_to_use`、`allowed-tools`、`context`、`agent`、`shell` 等）只在 Claude Code 内生效，复制到其他工具会被静默忽略——"跨平台可移植"只针对 agentskills.io 规范字段[^5^][^6^]。

## 2. obra/superpowers 仓库

- URL：https://github.com/obra/superpowers ；作者 Jesse Vincent（Prime Radiant）；**License: MIT**（README 明示）[^7^]。
- Stars：265.4k（awesome-agent-skills 目录，2026-08-01 数据）[^8^]；agentconn 报道 2026-04-11 单日 +1,589 star、总量 147k+[^9^]；skillsllm 2026-08 榜单显示 234,966 stars / 20,863 forks[^10^]。2026-08-20 当天 GitHub API 限流，未能取得 API 精确值（**未查到精确当日值**，量级：~25 万 stars）。
- 结构：一套"agentic skills framework + 软件开发方法论"。技能库分四组[^7^]：
  - Testing：`test-driven-development`（RED-GREEN-REFACTOR）
  - Debugging：`systematic-debugging`（4 阶段根因流程）、`verification-before-completion`
  - Collaboration：`brainstorming`、`writing-plans`、`executing-plans`、`dispatching-parallel-agents`、`requesting-code-review`、`receiving-code-review`、`using-git-worktrees`、`finishing-a-development-branch`、`subagent-driven-development`
  - **Meta（与自进化最相关）**：`writing-skills`（按最佳实践创建新 skill，含 TDD 式测试方法论）、`using-superpowers`（系统引导）
- 与自进化的关联：superpowers 本身**没有**"从错误中自动学习/沉淀经验"的 skill；其自进化相关部分是 meta-skill `writing-skills`——教 agent 用 RED-GREEN-REFACTOR 方式创建和测试新 skill（先跑无 skill 的压力场景记录失败行为 → 写最小 skill → 堵住 agent 的新借口，直到无懈可击）[^11^]。社区已有移植（Reasonix 版 `superpowers-writing-skills`）和抽取（`spark` skill，从 brainstorming 抽出，MIT）[^12^][^13^]。
- 跨运行时安装（README 实测，2026-08-20）：Claude Code（`/plugin install superpowers@claude-plugins-official`）、**Cursor（Agent 聊天里 `/add-plugin superpowers` 或插件市场搜索）**、Codex、OpenCode、Gemini CLI、Copilot CLI、Kimi、Grok 等 15 个 harness[^7^]。
- 衍生仓库：`obra/superpowers-skills`（社区可编辑技能库，736★）、`obra/superpowers-marketplace`（1.2k★）、`obra/superpowers-lab`（405★，实验性新技能）[^8^]。
- 二次开发：fork 后按 `writing-skills` 规范写新 skill 目录即可；官方不一般接受新 skill 贡献，鼓励自建扩展（部署清单、ADR、安全审查、onboarding 等）[^14^]。

## 3. 与自进化直接相关的现成 skill（同形态、可直接安装）

以下均与 superpowers 同形态（SKILL.md 目录，可放进 skills 目录即插即用），按与用户场景（Cursor + GPT + 自进化）的贴合度排序：

### 3.1 JustinGastby/Hermes-Mind-Skill ★最贴合用户需求
- URL：https://github.com/JustinGastby/Hermes-Mind-Skill ；License: **MIT**；stars 未查到（2026-07-22 在 ruanyf/weekly 自荐，较新）[^15^]。
- 核心机制：**专为 Cursor 与 Claude Code 设计的轻量自我进化闭环**。用原生 Hooks（postToolUse 计数 + stop 事件）：任务中工具调用达阈值（默认 5 次）→ 提醒 agent 反思 → `distill-skill` 草拟简短 Skill 提案 → **用户确认后才写入 SKILL.md** → 下次同类任务直接复用。另带 `curate-skills`：定期体检、归档（非删除，可恢复）久未使用/重叠的旧技能。几十行 Node.js（无 Node 回退 jq/纯 bash），无服务端、无网络调用，人在回路[^16^]。
- Cursor 兼容性：**原生支持**（安装脚本把 hook 拷到 `.cursor/hooks/`、skill 拷到 `.cursor/skills/`，不覆盖已有 hooks.json，落 `*.hermes-mind-skill.json` 供手动合并）[^16^]。
- 二次开发：改 `THRESHOLD`、`STALE_DAYS`、`CURATOR_INTERVAL_HOURS` 常量；hooks 与 SKILL.md 全可读可改。

### 3.2 pskoett/self-improving-agent（+ 多 agent 原版 pskoett-ai-skills）
- URL：https://github.com/pskoett/self-improving-agent ；多 agent 版：https://github.com/pskoett/pskoett-ai-skills/tree/main/skills/self-improvement
- Stars：**pskoett-ai-skills 280★ / 45 forks（2026-08-20 直接打开仓库页实测）**；OpenClaw 目录显示 self-improving-agent 17k 下载[^17^][^18^]。
- 核心机制：事件驱动捕获——(1) 命令/操作意外失败；(2) 用户纠正（"No, that's wrong…"）；(3) 用户要求不存在的能力；(4) 外部 API 失败；(5) agent 发现自己知识过时；(6) 发现重复任务的更优解——写入 `.learnings/LEARNINGS.md`、`ERRORS.md`、`FEATURE_REQUESTS.md`（带 [LRN-YYYYMMDD-XXX] 编号），重大任务前回顾，并把可泛化的条目"晋升"到 AGENTS.md / SOUL.md / TOOLS.md 等持久工作区文件[^18^][^19^]。
- 兼容性：主仓是 OpenClaw-only；**多 agent 版（pskoett-ai-skills/skills/self-improvement）面向 Claude Code、Codex、GitHub Copilot 等**——Cursor 读 SKILL.md，可直接拷目录使用，但 hook 部分需按 Cursor hooks 机制自行适配[^17^]。
- 衍生：`RangeKing/self-evolving-agent`——在其之上升级为"目标驱动能力进化"（课程、评估、迁移验证后才晋升，`.evolution/` 目录，提供从 `.learnings/` 无损迁移脚本）[^20^]。

### 3.3 alchaincyf/darwin-skill（达尔文.skill）—— Skill 的自动优化器
- URL：https://github.com/alchaincyf/darwin-skill ；2026-04-14 开源；安装 `npx skills add alchaincyf/darwin-skill`；stars 未查到（GitHub API 限流；作者博客 2026-06-20 发布正式版）[^21^][^22^]。
- 核心机制：把 SKILL.md 当作"可训练资产"，受 Karpathy autoresearch 启发 + 微软 SkillLens（rubric）/SkillOpt（validation-gated edits）。五阶段：Evaluate（9 维加权 rubric，满分 100，结构+实测）→ Improve（每轮只改得分最低维度，git commit）→ Validate（2 个独立子 agent 重新评分 + test-prompts.json 复测）→ Confirm（人在回路看 diff）→ Keep or Revert（**棘轮机制：分数只能上升，退步即 git revert**）。单轮涨幅 <1 分自动早停[^22^]。
- 兼容性：任何支持 SKILL.md 的宿主（Claude Code、Codex、OpenClaw、Trae、CodeBuddy 等）；**在 Cursor 中作为普通 skill 目录可用**（优化动作=编辑文件+git 操作，Cursor Agent 均可执行）[^21^]。
- 安全提示（作者自述）：须在 git 仓库内运行并先 commit/stash；审查 checkpoint diff，尤其 skill 涉及 shell/git/凭证时[^22^]。

### 3.4 Anthropic 官方 skill-creator（anthropics/skills 内）
- URL：https://github.com/anthropics/skills/tree/main/skills/skill-creator ；母仓库 anthropics/skills ~149k★（2026-06-11 GitHub API，二手）/ ~167k★（LimeDock，日期不明）[^23^][^24^]；License：示例技能 Apache-2.0（docx/pdf/pptx/xlsx 四个文档技能为 source-available 非开源）[^24^]。
- 核心机制：meta-skill——访谈意图 → 写 SKILL.md → 生成测试用例与断言 → 并行跑 with-skill/baseline 对照 → grader 子 agent 评分 → 浏览器 viewer 展示 → 优化 description 提升触发召回（含 train/test split 优化循环）[^25^][^26^]。
- 衍生：`brysonreece/better-skill-creator`（7 阶段、5 模板、预检清单）；`yaniv-golan/skill-creator-plus`（修 bug + Cowork 支持）；`antongulin/opencode-skill-creator`（OpenCode 移植）[^27^][^28^][^29^]。
- 安装：`/plugin install example-skills@anthropic-agent-skills`（Claude Code）；`npx skills add anthropics/skills --skill skill-creator`（Cursor 等亦可经 skills CLI 装入）[^24^][^30^]。

### 3.5 openclaw/skills 的 self-optimization（可跨 agent）
- URL：https://github.com/openclaw/skills/blob/main/skills/alethean-kaw/self-optimization/SKILL.md [^31^]
- 机制：错误检测 hook（PostToolUse→error-detector.sh）+ 激活器 hook，把教训记到 `.learnings/`，链接重复条目，稳定规则晋升为仓库指引，广泛模式抽取成新 skill。官方给出 **Claude Code/Codex 的 hooks 配置示例**和 Copilot instructions 写法；Cursor 可照其 hook 思路用 `.cursor/hooks` 适配[^31^]。

### 3.6 其他自进化/学习类项目（补充）
| 项目 | 机制 | 备注 |
|---|---|---|
| sentient-agi/EvoSkill（arXiv:2603.02766） | 从失败轨迹演化技能变体：Proposer→Generator→Evaluator（held-out 集）→Frontier（git 分支版本化 Top-N 程序）；支持 Claude Code/OpenCode/OpenHands/Goose/Codex | 偏研究/重框架，需 benchmark CSV[^32^] |
| Adit-Jain-srm/skill-forge v1.2 | SkillOpt 自改进环（rollout/reflect/aggregate/select/update/evaluate）+ TF-IDF 路由 + 索引记忆；多 harness（Cursor/Claude Code/Codex/Gemini/Copilot）；`npx skills add Adit-Jain-srm/skill-forge` | 参考了 microsoft/SkillOpt[^33^] |
| openJiuwen-ai/jiuwenclaw | 运行时技能自演化：SignalDetector（规则，不调 LLM）→ SkillEvolutionManager → SkillOptimizer 写 `evolutions.json` → solidify 合并回 SKILL.md；`/evolve` 手动触发 | 独立 runtime，非纯 skill[^32^] |
| onurpolat05/ALBA | 9 skill + 6 hook + 3 层 git 记忆；`error-logger` hook 自动记录错误与学习；纯 markdown、MIT、模板仓 | Claude Code 为主[^34^] |
| hugo662/claudify | 1,727 skill + 自改进知识库（agent 提名 learnings→auditor 验证→规则传播）；号称支持 Cursor | 一次性付费、闭源成分，注意[^35^] |
| openclaw/skills 的 cognitive-memory / ml-evolution-agent | 认知多存储记忆（编码/巩固/衰减/回忆/睡眠反思）；ML 竞赛自进化 agent（HCC 四层记忆） | OpenClaw 生态，6.3k 下载[^36^][^37^] |
| 浙大-阿里 Open Skill（学术） | 开放世界获取 → 无泄漏迭代进化（Generator/Verifier 闭环）→ 零样本评估；SkillsBench 完成率 25%→43.6%，第 3 轮迭代即超人工 skill；进化出的 skill 迁移到小模型仍 +35~44% | 方法论参考，非即插即用[^38^] |
| Datawhale hello-agents Extra10 | 「Agent 自进化」教学章节，把 Hermes-Mind-Skill / darwin-skill / JiuwenClaw / EvoSkill 归纳为"技能资产化闭环"四阶段路线 | 很好的中文综述[^32^] |

## 4. Skills 市场 / 目录站

| 站点 | 规模（自述，注明日期） | 特点 | URL |
|---|---|---|---|
| skills.sh（Vercel） | 83,627 skills / 8M+ installs（2026-04）；支持 18+ agent | `npx skills add owner/repo`，按安装量排行，提供 API；Claude Code/Cursor/Codex/Copilot 一键装 | https://skills.sh [^39^][^40^] |
| skillsllm.com | 4,493 skills / 10 类（2026-08-20 实测页面）；曾称 1600+ 安全审核 | 面向 Claude Code/Codex/ChatGPT；含 skill-manager（SkillDock）管理多工具同步 | https://skillsllm.com [^10^][^41^] |
| SkillsMP | 351k（2026-04）→ ~1.9M（2026-06，爬 GitHub 自动聚合） | 最大目录；无质量门，"安装前自查" | https://skillsmp.com [^42^][^43^] |
| ClawHub | ~3,286 skills / 1.5M 下载（2026-04） | OpenClaw 官方市场，版本化+回滚；曾遭 ClawHavoc 攻击 | https://clawhub.ai [^39^][^44^] |
| Skills Directory | ~96,903 索引（2026-07）；自带 50+ 规则安全扫描 | 自动索引+社区提交 | https://www.skillsdirectory.com [^42^][^45^] |
| anthropics/skills | 官方示例+文档技能；partner 目录（Atlassian/Figma/Canva/Stripe/Notion/Zapier/Sentry 等） | `/plugin marketplace add anthropics/skills` | https://github.com/anthropics/skills [^24^][^2^] |
| royalpinto007/awesome-agent-skills | 人工精选、带 stars 与安全意识 | 含安全扫描器条目 | https://github.com/royalpinto007/awesome-agent-skills [^8^] |
| 其他 | mcpservers.org/agent-skills（ZIP 下载）、mcpmarket、AugmentClaude（532 人工精选）、LobeHub（30 万+）、claudemarketplaces.com（2,500+ 插件市场） | — | [^42^][^46^][^47^] |

## 5. MCP 生态中的记忆/学习/反思类 server

| 项目 | URL / 安装 | stars（注明日期） | License | 核心机制 | Cursor 兼容 |
|---|---|---|---|---|---|
| @modelcontextprotocol/server-memory（官方知识图谱记忆） | `npx -y @modelcontextprotocol/server-memory` | 目录站称 80.5k★（2026-04，explainx 聚合，存疑偏高） | MIT（MCP servers monorepo） | 实体/关系/观察三元组知识图谱，跨会话持久；9 工具；本地 JSONL 存储 | ✅ Cursor MCP 一键配置 [^48^][^49^] |
| mem0（+ OpenMemory MCP） | https://github.com/mem0ai/mem0 | 55.2k★（2026-05-09）→ 62.9k★（2026-08-10，theaiagentindex） | Apache-2.0 | 单 pass ADD-only 抽取 + 实体链接 + 三路融合检索（semantic+BM25+entity）；提供 Library/Server/Cloud/CLI/**MCP/Agent Skills**（仓内含 `.claude-plugin/`、`.cursor-plugin/`） | ✅ 官方 .cursor-plugin [^50^][^51^] |
| Zep / Graphiti | https://github.com/getzep/graphiti | Zep 29.7k★（2026-08-10） | Apache-2.0 | 时序知识图谱，原生 point-in-time 查询（合规审计优势）；MCP server；自托管需 Neo4j | ✅ MCP [^51^][^52^] |
| thedotmack/claude-mem | `/plugin marketplace add thedotmack/claude-mem` | 27.7k★（2026-02）→ 78.2k★（2026-05 二手聚合，存疑） | **AGPL-3.0**（ragtime/ 目录 PolyForm Noncommercial） | 5 个生命周期 hook 捕获工具调用→AI 压缩成语义观察→SQLite FTS5→新会话按需注入；渐进披露省 ~10x token；7 个 MCP 搜索工具 | 插件为 Claude Code 形态；Cursor 需经其 MCP/适配层，**非即插即用** [^53^][^54^] |
| clopca/open-mem | `bunx open-mem-cursor --project …` | 未查到 | 未查到 | OpenCode 原生，**提供 Cursor 适配器与通用 MCP**；FTS5+向量+知识图谱混合检索，~96% 压缩，会话末自动生成 AGENTS.md | ✅ 官方 Cursor adapter [^55^] |
| syntax-syndicate/engram | https://github.com/syntax-syndicate/engram-agent-memory | 未查到 | 未查到 | agent 自主决定记什么（mem_save），Go 单二进制 + SQLite FTS5，agent-agnostic MCP | ✅ 任意 MCP 客户端 [^56^] |
| MemOS | https://github.com/MemTensor/MemOS | 未查到 | 未查到 | "自进化记忆 OS"，混合检索（关键词+向量+图） | MCP [^57^] |
| dustinspace217/mcp-memory-server | fork 自官方 memory server | 未查到 | MIT（保留原 LICENSE） | SQLite+sqlite-vec 语义搜索、时序版本化、L0/L1 上下文层、session-start 简报 | ✅ [^58^] |

## 6. Cursor 侧的支持方式与自进化挂载方案

**Cursor 对 Skills 的原生支持**（官方文档 cursor.com/docs/skills，2026-08-20 查阅）[^59^]：
- Cursor 2.4 起编辑器与 CLI 均支持 Agent Skills；启动时自动发现，agent 按 description 判断相关性，也可 `/` 手动调用。
- 加载目录（优先级）：`.agents/skills/`、`.cursor/skills/`（项目级）；`~/.agents/skills/`、`~/.cursor/skills/`（用户级）；**兼容读取 `.claude/skills/` 和 `.codex/skills/`（项目与用户级）**——即 superpowers/self-improvement 等 Claude 形态 skill 放进 `.claude/skills/` 后 Cursor 直接可见。
- 内置相关 skill：`/create-skill`（生成 SKILL.md）、`/migrate-to-skills`（把 dynamic rules 和 slash commands 转成 Skills）、`/create-rule`、`/create-hook`、`/loop`（定时重复跑 prompt 或 skill——可作自进化"心跳"）。
- 安装 superpowers：Agent 聊天输入 `/add-plugin superpowers` 或插件市场搜索[^7^]。

**Rules / AGENTS.md**[^60^][^61^][^62^]：
- `.cursor/rules/*.mdc`：frontmatter（description/globs/alwaysApply）组合出 4 种激活模式（Always / Auto-attach by globs / Agent-decided / Manual）。`.cursorrules` 单文件已废弃（Agent 模式不读）。
- Cursor 原生读 AGENTS.md（根目录+嵌套）。2026 主流分层：AGENTS.md=项目上下文（跨工具单一事实源）、Rules=行为约束、Skills=可调用工作流、MCP=实时数据。
- 关键自进化洞察：**聊天中的纠正不会持久化到未来会话**——要固化纠正，必须写成 rule（"Do X, not Y, because Z" 祈使句式）或 skill[^63^]。这正是自进化 skill 的切入点。

**把自进化机制挂进 Cursor 工作流的推荐组合**（基于以上事实的方案设计）：
1. 即插即用首选：**Hermes-Mind-Skill**（MIT，原生 Cursor hooks + skills，任务后反思→人确认→沉淀 SKILL.md）[^16^]。
2. 经验捕获层：**pskoett-ai-skills/self-improvement** 拷入 `.cursor/skills/`（或 `.claude/skills/` 双共享），纠正/失败自动记 `.learnings/`，定期晋升到 `.cursor/rules/*.mdc` 或 AGENTS.md[^17^][^19^]。
3. 技能优化层：**darwin-skill**（`npx skills add`，棘轮式优化已有 skill 质量）+ Anthropic **skill-creator**（新 skill 的 eval 流程）[^21^][^25^]。
4. 记忆底座（可选 MCP）：官方 server-memory（轻量知识图谱）或 mem0（带 .cursor-plugin）[^48^][^50^]。
5. 心跳：Cursor 内置 `/loop` 定期跑"回顾 .learnings/ 并晋升"的 prompt，模拟 OpenClaw heartbeat 模式[^59^][^19^]。

## 7. 生态争议与风险（重要）

- **Snyk ToxicSkills（2026-02-05）**：扫描 ClawHub + skills.sh 共 3,984 个 skill，**13.4%（534 个）含至少一个 critical 级安全问题，36.82%（1,467 个）含任意级别缺陷**；人工确认 76 个恶意 payload（凭证窃取、后门、数据外泄），发表时仍有 8 个在架[^64^]。
- **ClawHavoc 供应链攻击（2026-01）**：3 天内 341 个恶意 skill 涌入 ClawHub，通过伪造"前置依赖安装说明"投递 Atomic macOS Stealer；Bitdefender 称 ClawHub 约 20% 包恶意[^65^][^66^]。
- **Cato CTRL MedusaLocker（2025-12）**：把 Claude Skill 武器化投递勒索软件，隐藏 helper 脚本与已批准主脚本并行运行——"同意鸿沟"[^45^]。
- **学术基准**：Skill-Inject（arXiv:2602.20156）测得对前沿模型攻击成功率 80%；MalSkillBench（arXiv:2606.07131）运行时验证恶意 skill 基准[^67^][^68^]。
- **结构性风险**：SKILL.md 获得与系统提示同级的权威，却无签名/审核/来源验证；Trail of Bits 演示所有公开 skill 扫描器（ClawHub、Cisco、skills.sh）均可在一小时内绕过[^69^][^8^]。
- **防御工具**：obielin/skillguard（pip，31+ 规则，检测 prompt injection/外泄/"致命三要素"）、cfitzgerald-pd/skillcop（LLM 扫描 hook）、skill-audit（npx，SARIF 输出）、Sentry getsentry/skills 的 skill-scanner、OWASP Agentic Skills Top 10[^70^][^71^][^8^]。
- **"just markdown" 质疑**：部分开发者认为 skills 只是打包提示词的设计模式而非技术；另有"标准捕获"担忧——agentskills.io 被视为 Anthropic 继 MCP 后定义 AI 标准的第二步棋[^2^]。
- **质量噪声**：SkillsBench 分析 47,150 个公开 skill，平均质量 6.2/12；精选 skill 平均提升通过率 16.2 个百分点——目录大≠质量好[^43^]。
- **遥测注意**：superpowers 默认从官网加载 logo 做使用统计（可用 `SUPERPOWERS_DISABLE_TELEMETRY` 关闭）[^7^]。

## 8. 结论（面向"直接能用 + 可二次开发"）

1. **同形态自进化 skill 已存在且可直接装**：Hermes-Mind-Skill（Cursor 原生、MIT、人在回路）与 self-improvement（多 agent 版 280★）是最贴近"superpowers 同形态"的两个；darwin-skill 提供"像训练模型一样优化 skill"的棘轮闭环；skill-creator 提供官方 eval 基建。
2. **规范层面无记忆/凭证字段**，自进化只能靠"skill + hooks + 工作区文件（.learnings/、AGENTS.md、.cursor/rules）+ 可选 MCP 记忆"拼装——这恰是社区主流做法。
3. **安全是真实威胁**（13.4% critical、真实窃密事件），引入任何第三方 skill 前应先跑 skillguard/skill-audit，并把自进化写盘动作（如 darwin-skill 的 git 操作）置于人在回路确认之下。

---

## 引用

[^1^]: agentmuxai/agentmux 调研报告（2026-07-16，多轮交叉验证）："Created by Anthropic, released as an open standard (announced 2025-12-18), now governed in a vendor-neutral GitHub org (agentskills/agentskills, Apache-2.0/CC-BY-4.0)… Frontmatter has exactly six fields (name, description required…) No fields for credentials, MCP config, or memory"。https://github.com/agentmuxai/agentmux/blob/main/docs/specs/REPORT_ARMORY_BUNDLE_STANDARD_RESEARCH_2026_07_16.md
[^2^]: rywalker.com《Anthropic Skills》（2026-02-22 更新至 2026-06）："as of June 2026 the agentskills.io client showcase lists ~40 adopters, including GitHub Copilot, VS Code, Cursor, OpenAI Codex, Gemini CLI, Goose, OpenCode…"。https://rywalker.com/research/anthropic-skills
[^3^]: inference.sh《Agent Skills: The Open Standard》（2026-08-01）："The specification lives on GitHub at github.com/agentskills/agentskills… ChatGPT's code interpreter environment now includes a /home/oai/skills folder… The Codex CLI accepts skills through the --enable skills flag and reads from ~/.codex/skills"。https://inference.sh/blog/skills/agent-skills-overview
[^4^]: strapi.io（2026-02-10）："On December 18, 2025, Anthropic released Agent Skills as an open standard… The specification and reference library live at github.com/agentskills/agentskills… `skills-ref validate ./my-skill`"。https://strapi.io/blog/what-are-agent-skills-and-how-to-use-them
[^5^]: cnblogs 综述（2026-08-01）："Claude Code 自己扩展的字段（如 when_to_use、allowed-tools、context、agent、shell 等）只在 Claude Code 内生效，复制到别的软件会被忽略"。https://www.cnblogs.com/know-data/p/22137667
[^6^]: agentpatterns-ai 标准页（2026-03-28）："tools extend the standard with non-portable frontmatter fields… Skills that rely on these extensions lose portability quietly"。https://github.com/agentpatterns-ai/website/blob/main/standards/agent-skills-standard.md
[^7^]: obra/superpowers README（2026-08-20 直接打开）：技能清单、"Cursor: In Cursor Agent chat, install from marketplace: /add-plugin superpowers"、"License: MIT"、telemetry 说明。https://github.com/obra/superpowers
[^8^]: royalpinto007/awesome-agent-skills（2026-08-01）："obra/superpowers *265.4k… obra/superpowers-marketplace *1.2k… obra/superpowers-skills *736… obra/superpowers-lab *405… Trail of Bits: every public skill scanner… is bypassable in under an hour"。https://github.com/royalpinto007/awesome-agent-skills
[^9^]: agentconn（2026-04-11）："picked up 1,589 GitHub stars in a single day… now has over 147,000 total stars since Jesse Vincent first published it in October 2025"。https://agentconn.com/blog/obra-superpowers-agentic-skills-framework-guide/
[^10^]: skillsllm.com 首页（2026-08-20 实测）："An agentic skills framework & software development methodology that works. 234,966 / 20,863"；站点自述 "4,493 Skills / 10 Categories"。https://skillsllm.com/
[^11^]: obra/superpowers-skills meta/writing-skills SKILL.md（2025-10-03）："RED-GREEN-REFACTOR for Skills… Run pressure scenario with subagent WITHOUT the skill… Write skill that addresses those specific rationalizations… Re-test until bulletproof"。https://github.com/obra/superpowers-skills/blob/main/skills/meta/writing-skills/SKILL.md
[^12^]: christopherarter/superpowers-reasonix（2026-06-13）：11 个移植技能含 superpowers-writing-skills。https://github.com/christopherarter/superpowers-reasonix
[^13^]: wishworldbetter/seedex-skills（2026-05-21）："The spark skill is extracted from obra/superpowers (MIT licensed)… npx skills add wishworldbetter/seedex-skills --skill spark"。https://github.com/wishworldbetter/seedex-skills
[^14^]: termdock（2026-03-17）："Includes a writing-skills skill that teaches the agent how to create new skills following best practices… Your custom skills compose with existing ones"。https://www.termdock.com/en/blog/superpowers-framework-agent-skills
[^15^]: ruanyf/weekly issue #10834（2026-07-22）：工具自荐 Hermes-Mind-Skill，"用 Cursor / Claude Code 原生的 Hooks + Skills 拼出一套「任务后自我反思、经你确认再沉淀为可复用 Skill」的轻量自我进化闭环"。https://github.com/ruanyf/weekly/issues/10834
[^16^]: JustinGastby/Hermes-Mind-Skill README（2026-08-20 直接打开）："先问，你确认了才真正写文件… 安装脚本会把 hook 脚本拷贝到 .cursor/hooks/ 或 .claude/hooks/… 不会覆盖，而是落一份 *.hermes-mind-skill.json 供你手动合并… License: MIT"。https://github.com/JustinGastby/Hermes-Mind-Skill
[^17^]: pskoett/self-improving-agent README（2026-01-31 更新）："This version is OpenClaw-only. To use the skill with other agents (Claude Code, Codex, GitHub Copilot, …), use the original multi-agent version instead: pskoett/pskoett-ai-skills/tree/main/skills/self-improvement"；pskoett-ai-skills 仓库页实测 280 stars / 45 forks（2026-08-20）。https://github.com/pskoett/self-improving-agent
[^18^]: openclawdirectory.dev："self-improving-agent — Captures learnings, errors, and corrections… 17k downloads"；触发条件六类（失败、用户纠正、能力缺失、API 失败、知识过时、发现更优解）。https://www.openclawdirectory.dev/skills/agent-memory
[^19^]: stack-junkie.com（2026-03-13）："Corrections get written to Markdown files (MEMORY.md, AGENTS.md, SOUL.md)… promotion: Moving a learning from the temporary .learnings/ log to a permanent workspace file… The first complete loop typically takes one to two heartbeat cycles"。https://www.stack-junkie.com/blog/openclaw-learning-without-rl
[^20^]: RangeKing/self-evolving-agent（2026-03-18）："upgrades self-improving agents from reactive error logging to goal-driven capability evolution with curriculum, evaluation, transfer… Bootstrap .evolution/ and import the old .learnings/ directory"。https://github.com/RangeKing/self-evolving-agent
[^21^]: jimo.studio（2026-06-20）："达尔文.skill已于4月14日正式开源… npx skills add alchaincyf/darwin-skill… 设计100%受Karpathy开源的autoresearch项目启发"。https://jimo.studio/blog/darwin-skill-released-a-revolutionary-self-evolving-skill-system/
[^22^]: alchaincyf/darwin-skill README（2026-04-13 / v2.0 2026-05-28）："棘轮机制：分数只能上升… 新分>旧分→保留；否则→git revert… 启动2个独立子agent重新评分… CHECKPOINT暂停，展示diff+分数变化，等用户确认… v2.0吸收微软研究院SkillLens与SkillOpt"。https://github.com/alchaincyf/darwin-skill
[^23^]: skills.tenten.co（2026-05-31）："github.com/anthropics/skills/skills/skill-creator · 134k★… 访谈使用意图、写SKILL.md、执行with/without对照测试、量化token与时间差异…优化description提高触发召回率"。https://skills.tenten.co/original-html/skills-atlas-anthropics-skill-creator.html
[^24^]: anthropics/skills README（jarden-digital 镜像与官方一致）："Many skills in this repo are open source (Apache 2.0)… document creation & editing skills… are source-available, not open source"；安装 `/plugin marketplace add anthropics/skills`。https://github.com/anthropics/skills ；stars ~149k（2026-06-11，rywalker 引 GitHub API）[^2^]；~167k（LimeDock，日期不明 https://www.limedock.com/directories/anthropics-skills）
[^25^]: hboon.com（2026-03-03）："skill-creator… adds evaluation capabilities — test a skill against synthetic prompts, grade the outputs, and compare old vs new versions… optimize the skill's description so the agent triggers it more reliably"。https://hboon.com/using-the-skill-creator-skill-to-improve-your-existing-skills/
[^26^]: skillsmp skill-creator 页（2026-04-20）："Interview and Research… Write the SKILL.md… description is the primary triggering mechanism… make the skill descriptions a little bit pushy"。https://skillsmp.com/skills/anthropics-skills-skills-skill-creator-skill-md
[^27^]: brysonreece/better-skill-creator（2026-03-09）："7 clear phases from planning to distribution… 5 templates… Full validation gate before packaging"。https://github.com/brysonreece/better-skill-creator
[^28^]: yaniv-golan/skill-creator-plus（2026-04-01）："Create / Evaluate / Improve / Compare（blind A/B）/ Optimize Description"。https://github.com/yaniv-golan/skill-creator-plus
[^29^]: antongulin/opencode-skill-creator（2026-04-09）："OpenCode skill for creating, testing, and optimizing other OpenCode skills. Adapted from Anthropic's skill-creator"。https://github.com/antongulin/opencode-skill-creator
[^30^]: composio.dev（2026-05-11）："npx skills add https://github.com/anthropics/skills --skill skill-creator"。https://composio.dev/content/10-best-opencode-skills-that-are-actually-useful-in-2026
[^31^]: openclaw/skills self-optimization SKILL.md（2026-04-01）：给出 Claude Code/Codex hooks 配置（UserPromptSubmit→activator.sh、PostToolUse(Bash)→error-detector.sh）与 Copilot instructions 模板；"Promote stable rules into repo guidance… Extract reusable skills when the pattern is broad"。https://github.com/openclaw/skills/blob/main/skills/alethean-kaw/self-optimization/SKILL.md
[^32^]: Datawhale hello-agents Extra10「Agent 自进化」（含 Darwin Skill、JiuwenClaw、EvoSkill 详解）："EvoSkill… Base Agent/Proposer/Generator/Evaluator/Frontier… 以 program/* Git 分支形式版本化"；"JiuwenClaw… SignalDetector（基于规则、不调用LLM）… evolutions.json → solidify 合并回 SKILL.md"。https://github.com/datawhalechina/hello-agents/blob/main/Extra-Chapter/Extra10-Agent%E8%87%AA%E8%BF%9B%E5%8C%96.md
[^33^]: Adit-Jain-srm/skill-forge releases（2026-06-06）："SkillOpt Self-Improvement Loop — rollout/reflect/aggregate/select/update/evaluate… Multi-Harness — works in Cursor, Claude Code, Codex CLI, Gemini CLI, Copilot… 参考 microsoft/SkillOpt (4.6K stars): skill-as-trainable-state"。https://github.com/Adit-Jain-srm/skill-forge/releases
[^34^]: awesome-claude-code issue #959（2026-03-09）：ALBA——"9 built-in skills… 6 automated hooks… 3-tier git-tracked memory… Self-improvement: auto-records errors and learnings… MIT License"。https://github.com/hesreallyhim/awesome-claude-code/issues/959
[^35^]: awesome-claude-code issue #1089（2026-03-24）：Claudify——"1,727 skills… Self-improving knowledge base — agents nominate learnings, auditor validates, rules propagate… One-time purchase"。https://github.com/hesreallyhim/awesome-claude-code/issues/1089
[^36^]: clawbot.ai cognitive-memory（2026-02-28）："multi-store memory system with human-like encoding, consolidation, decay, and recall… sleep-time reflection… 6.3K downloads"。https://clawbot.ai/skills/cognitive-memory.html
[^37^]: playbooks.com ml-evolution-agent（2026-02-17）："Auto-evolving ML competition agent… HCC Multi-layer Memory — Episodic, Pattern, Knowledge, Strategic layers"。https://playbooks.com/skills/openclaw/skills/ml-evolution-agent
[^38^]: 智源社区/浙大-阿里 Open Skill（2026-07-03）："在SkillsBench（基于Claude 4.6）上，无Skill的baseline完成率为25%，Open Skill可以达到…43.6%… 在第三轮迭代时，自动进化的Skill就已经超越了人工编写的Skill… 应用于较小模型均获得35%到44%的性能提升"。https://hub.baai.ac.cn/view/56058
[^39^]: buildmvpfast（2026-04-23）："SkillsMP is the volume leader at 351,349 skills… Skills.sh… At 83,627 skills with 8M+ total installs… supports 18 different AI agents… ClawHub… roughly 3,200 skills with 1.5M+ downloads"。https://www.buildmvpfast.com/blog/agent-skills-npm-ai-package-manager-2026
[^40^]: mcpmarket skills.sh marketplace manager："npx/bunx skills add <owner/repo>… supports claude-code, opencode, codex, cursor, antigravity, github-copilot, roo"。https://mcpmarket.com/tools/skills/skills-sh-marketplace-manager
[^41^]: skillsllm skill-manager（2026-06-02）：SkillDock 支持 Claude Code、Codex、Cursor、Windsurf 等 30 种工具的技能/MCP 一键安装与同步。https://skillsllm.com/skill/wanghuan9-skill-manager
[^42^]: augmentclaude 市场对比（2026-07-03）：SkillsMP"2,000,000+"、Skills Directory"96,903 indexed skills"、CrossAITools"21,600+"、Smithery 18,734。https://augmentclaude.com/claude-skills-marketplaces
[^43^]: agentman 生态报告（2026-06-24）："SkillsMP alone lists about 1.9 million public skills… SkillsBench analyzed 47,150 public skills and found an average quality score of 6.2 out of 12, while curated skills raised agent pass rates by an average of 16.2 percentage points"。https://agentman.ai/blog/agent-skills-ecosystem-report-2026
[^44^]: Snyk ToxicSkills（2026-02-05）亦提及 ClawHub 规模与恶意包。https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub/
[^45^]: skillsdirectory.com/security："Snyk ToxicSkills… ClawHavoc Campaign January 2026… 341 malicious skills delivered Atomic macOS Stealer… Bitdefender found ~20% of all ClawHub packages were malicious… Cato CTRL MedusaLocker December 2025… the 'consent gap'"。https://www.skillsdirectory.com/security
[^46^]: mcpservers.org/agent-skills："this Claude Skills marketplace lists hundreds of official and community skills… download it as a ZIP or install it with one command in Claude Code, Cursor"。https://mcpservers.org/agent-skills
[^47^]: navosagent（2026-06-09）："LobeHub Skills 收录了超过 30 万个 Skill"。https://www.navosagent.ai/en/blog/best-agent-skills-marketplaces
[^48^]: npm @modelcontextprotocol/server-memory（2026-07-04 更新）：knowledge-graph resource、9 个变更工具、notifications/resources/updated。https://www.npmjs.com/package/@modelcontextprotocol/server-memory
[^49^]: explainx.ai（2026-04-13）："Knowledge Graph Memory is an official MCP server published by anthropic… ★80.5K GitHub stars（聚合数字，存疑）"。https://explainx.ai/mcp-servers/knowledge-graph-memory
[^50^]: fcwu/mykb（2026-05-09）："GitHub：55.2k stars、Apache 2.0… 整合：Library / Self-Hosted Server / Cloud SaaS / CLI / MCP / Agent Skills（Claude Code、Codex、Cursor、Windsurf 直接挂）… 仓库含 .claude-plugin/、.cursor-plugin/"。https://github.com/fcwu/mykb/blob/main/2026-05-09-article-mem0-vs-diy.md
[^51^]: theaiagentindex（2026-08-10 更新）：Mem0 "GitHub stars 62.9k"、Zep "29.7k"，二者均提供 MCP server。https://theaiagentindex.com/compare/zep-vs-mem0
[^52^]: mnemoverse Q3 2026 对比（2026-07-21）："only Zep/Graphiti answers point-in-time queries natively… self-hosting means owning the Neo4j operational burden"。https://mnemoverse.com/docs/library/ai-memory-solutions-2026-q3
[^53^]: dev.to 介绍（2026-03-19）：claude-mem "27.7k+ stars… License: AGPL-3.0；ragtime/ 目录 PolyForm Noncommercial 1.0.0… 5 lifecycle hooks… SQLite+Chroma… 渐进披露 ~10x token 节省"。https://dev.to/wonderlab/open-source-project-of-the-day-part-21-claude-mem-persistent-memory-compression-system-for-1db8
[^54^]: agentxagi/awesome-discoveries（2026-05-19）："claude-mem — 78.2K Stars（聚合数字，与 [^53^] 差异大，存疑）"。https://github.com/agentxagi/awesome-discoveries
[^55^]: clopca/open-mem README："Multi-platform… Cursor: bunx open-mem-cursor --project /path/to/project… Any MCP client… auto-generates a root AGENTS.md context file… Typical compression ratio: ~96%"。https://github.com/clopca/open-mem
[^56^]: syntax-syndicate/engram："Engram lets the agent decide what's worth remembering… Works with ANY agent via standard MCP"。https://github.com/syntax-syndicate/engram-agent-memory
[^57^]: agentxagi 列表："MemOS — Self-evolving memory OS for LLM and AI agents. Ultra-persistent memory, hybrid-retrieval (keyword + vector + graph)"。https://github.com/agentxagi/awesome-discoveries
[^58^]: dustinspace217/mcp-memory-server（2026-04-01）："derived from @modelcontextprotocol/server-memory… originally published under the MIT License… SQLite storage… Semantic vector search… Temporal versioning… Context layers L0/L1"。https://github.com/dustinspace217/mcp-memory-server
[^59^]: Cursor 官方文档 Agent Skills（2026-08-20 查阅）："Cursor announced Agent Skills support for the editor and CLI in Cursor 2.4… Skills are automatically loaded from: .agents/skills/, .cursor/skills/, ~/.agents/skills/, ~/.cursor/skills/… For compatibility, Cursor also loads skills from Claude and Codex directories: .claude/skills/, .codex/skills/…"；内置 /create-skill、/migrate-to-skills、/loop、/create-hook 等。https://cursor.com/docs/skills ；agentskillshub.dev/guides/cursor-skills-hub/（2026-05-23）
[^60^]: Cursor 官方文档 Rules："If alwaysApply is true, the rule will be applied to every chat session… Check your rules into git… When you see Agent make a mistake, update the rule"。https://cursor.com/docs/rules
[^61^]: codersera（2026-08-13）：".cursor/rules/<name>.mdc… four activation modes: Always / Auto-attach / Agent-decided / Manual… keep an AGENTS.md at the root and use .cursor/rules/ for scoped overrides"。https://codersera.com/blog/agents-md-vs-claude-md-vs-cursor-rules-comparison-2026/
[^62^]: vibecodingacademy（2026-01-21）："Cursor now reads AGENTS.md natively, both at the project root and in nested subdirectories"。https://www.vibecodingacademy.ai/blog/cursor-ai-best-practices-guide-2026
[^63^]: baeseokjae（2026-05-11）："Corrections made in chat context are not persisted to future agent sessions. To make a correction permanent, encode it as a rule in .cursor/rules/*.mdc with the imperative format: 'Do X, not Y, because Z.'"；".cursorrules is only read in Chat and Tab — not loaded during Agent mode"。https://baeseokjae.github.io/posts/cursor-agent-best-practices-2026/
[^64^]: Snyk ToxicSkills（2026-02-05）："13.4% of all skills, or 534 in total, all contain at least one critical-level security issue… 36.82% (1,467 skills) have at least one security flaw… 76 malicious payloads… 8 of these malicious skills remain publicly available on clawhub.ai as of publication"。https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub/
[^65^]: obielin/skillguard README（2026-04-16）："In January 2026, the ClawHavoc campaign dropped 341 malicious skills into the Claude skill marketplace in 3 days… Snyk's ToxicSkills audit found that 13.4% of 3,984 skills contain critical security issues… OWASP Agentic Skills Top 10 lists skill supply-chain attacks as the #1 risk"。https://github.com/obielin/skillguard
[^66^]: kjaylee/misskim-skills 趋势扫描（2026-02-12）："ClawHavoc: 341 malicious ClawHub skills… HIGH — ZERO blind installs confirmed"。https://github.com/kjaylee/misskim-skills/blob/main/sweep-2026-02-12-16h-summary.md
[^67^]: RationalEyes/claude-skills-security-guide（2026-03-18）："A SKILL.md placed in ~/.claude/skills/ receives the same authority as Anthropic's own system prompt — with zero security review… 80% attack success rate on frontier models (Skill-Inject benchmark, arXiv:2602.20156)"。https://github.com/RationalEyes/claude-skills-security-guide
[^68^]: arXiv:2606.07131 MalSkillBench（2026-04-04）：运行时验证的恶意 agent skill 基准；引用 Sentry skill-scanner、Snyk agent-scan、SkillsMP（740,000+ skills listed）。https://arxiv.org/html/2606.07131v3
[^69^]: 同 [^8^]（Trail of Bits 结论）。
[^70^]: cfitzgerald-pd/skillcop（2026-03-16）："LLM-based security scanner for Claude Code skill files, implemented as Claude Code hooks… SessionStart/PreToolUse 两个 hook 集成点… 基于 Snyk ToxicSkills 威胁分类"。https://github.com/cfitzgerald-pd/skillcop
[^71^]: ruvnet/ruflo issue #1574（2026-04-09）：skills.sh 已集成 Agent Trust Hub 与 Snyk 安全报告（示例：github-project-management skill 被标 CRITICAL——间接提示注入+恶意 URL）。https://github.com/ruvnet/ruflo/issues/1574

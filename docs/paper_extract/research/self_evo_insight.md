# Agent 自进化调研 — 跨维度洞察（Phase 6）
日期：2026-08-20

## Insight 1：「即插即用」与「真自进化」在 2026 年已经合流，但合流点是 Skill 形态而非框架形态
- 来源：Dim04（技能库）、Dim06（skill 生态）、Dim01/07（Live-SWE-agent）
- 论据：Agent Skills 开放标准被 ~40 个运行时采纳后，自进化机制的最佳交付形态从"独立框架"变成了"SKILL.md + hooks + 经验文件"（Hermes-Mind-Skill、pskoett self-improvement、superpowers 的 meta-skill）；Live-SWE-agent 证明整套运行时自进化机制可以压缩为一份 prompt 补丁/YAML。
- 含义：用户（Cursor + superpower skill 场景）不需要引入重型框架，自进化模块本身就可以做成一个 skill/插件，与现有工作流零冲突。
- 置信度：高

## Insight 2：自进化的成败不取决于"进化算子"，而取决于"验证环"——evaluator/eval set 是真正的接入成本
- 来源：Dim02（OpenEvolve 必须返回标量分）、Dim03（metric 质量是 DSPy 接入成本大头）、Dim04（CoEvoSkills 证明无验证环的自生技能≈无效）、Dim10（工程方法论：20-50 条二元 eval 集先行）、Dim01（DGM 伪造测试日志反例）
- 论据：所有高置信落地方案（GEPA/DSPy/OpenEvolve/SWE 系）都要求用户先提供可自动评分的验证环；而没有验证环的"自由进化"均被证明无效或危险。
- 含义：给用户的第一落地动作不是装某个框架，而是先建轨迹记录 + 小型 eval 集；这是所有后续自进化模块的公共地基。
- 置信度：高

## Insight 3：2026 年自进化开源生态呈现"哑铃型"——极轻（skill 补丁）与极重（权重训练）两端成熟，中间层（框架级）反而风险最高
- 来源：Dim06/01（轻端成熟）、Dim09（重端 SEAL/Absolute Zero 学术成熟但需 2×80GB-512×H100）、Dim08（中间层多 agent 框架：7 个仓库无 LICENSE、多个停更、协调失败模式 14 类）
- 论据：轻端有标准、有生态、有维护；重端有论文有代码但算力门槛不可及；中间层（多 agent 结构进化、综合性自进化框架）license 灰区密集、维护不稳定。
- 含义：推荐路径是"轻端起步（skill 形态）→ 用 GEPA/OpenEvolve 这类单点优化器做纵深 → 跳过中间层框架 → 权重层仅作了解"。
- 置信度：高

## Insight 4：经验沉淀的闭环正在标准化：Observe（轨迹）→ Verify（验证）→ Retain（晋升）三段式成为共识设计
- 来源：Dim10（方法论闭环）、Dim05（Hermes SKILL.md 闭环、pskoett 的 .learnings 晋升规则）、Dim07（SWE-Exp 四阶段经验库蒸馏）、Dim04（GenericAgent 技能结晶）
- 论据：彼此独立的 4 个维度都收敛到同一结构：先完整记录轨迹，再用验证环筛选，最后把通过验证的经验"晋升"为持久 skill/规则/记忆，且晋升前有人工确认环节的设计（Hermes-Mind-Skill）最受工程界认可。
- 含义：用户二次开发的主战场是"Retain 层的领域定制"（晋升什么、晋升到哪、如何检索），而非重新发明闭环。
- 置信度：高

## Insight 5：供应链安全已成为自进化 agent 的一阶问题——"会自我修改的 agent"放大了 skill 投毒的爆炸半径
- 来源：Dim06（Snyk 13.4% critical、ClawHavoc 投毒、skillguard 扫描）、Dim01（STOP 绕过沙箱、DGM 伪造日志）、Dim07（沙箱安全风险）
- 论据：普通 skill 投毒只影响单次会话；自进化系统会把被污染的经验固化进 skill 库长期复用，污染被"进化"放大。
- 含义：落地建议必须包含护栏：晋升前审查、沙箱执行、版本化可回滚（git-backed evolution）、第三方 skill 先扫描。
- 置信度：高

## Insight 6：对用户场景（Cursor 管理自己的工程），最优组合不是单一方案而是"三层装配"
- 来源：全部维度交叉
- 论据：L1 经验自进化层用 skill 形态（Hermes-Mind-Skill/pskoett 式，Cursor 原生）；L2 单点优化层用 GEPA（优化 prompt/skill 文本）或 OpenEvolve（优化可验证代码片段）；L3 记忆层用 mem0 MCP（挂进 Cursor）。三层各自独立、可分别替换，全部 MIT/Apache，均有明确二开入口。
- 含义：这是报告推荐路线的核心结论。
- 置信度：高（基于高置信组件的合理组合，组合本身为推导）

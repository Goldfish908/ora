# Agent 自进化开源方案调研 — 交叉验证报告（Phase 4-5）
日期：2026-08-20 | 输入：self_evo_dim01.md ~ dim10.md

## 一、置信度分级

### High Confidence（≥2 个独立来源一致）
1. **分层方法论**：自进化可在 5 个层面落地——prompt 层 / 记忆层 / 技能层 / 代码（脚手架）层 / 权重层，成本与风险递增。Dim01/03/05/09/10 一致，且与综述 arXiv:2507.21046（What/When/How/Where）及 yudesk 工程五层经验吻合。
2. **GEPA 是当前最有影响力的非权重优化器**：ICLR 2026 Oral，独立库（~6.2k★）+ 已并入 DSPy，可优化任意文本组件（prompt/skill/代码）。Dim02/03/05 三处独立提及。
3. **DSPy 是 prompt 程序化优化的事实标准**：MIT、活跃维护、MIPROv2+GEPA。Dim03 + 外部核实（多个 2026 年来源）。
4. **OpenEvolve 是进化式代码优化的首选开源引擎**：Apache-2.0，pip/CLI/库/Docker 四形态，evaluator 接口即插即用。Dim02 + 外部核实（2026-05 报道 6.2k★）。
5. **Live-SWE-agent 是"即插即用"程度最高的自进化编码 agent**：MIT，本质是 mini-SWE-agent 的 prompt 补丁（单 YAML），运行时自造工具+步级反思，SWE-bench Verified ~75-79%。Dim01/07 独立一致。
6. **Agent Skills 开放标准（agentskills.io）已被 Cursor/Claude Code/Codex/OpenCode 等数十个运行时采纳**；Cursor 2.4 原生支持 SKILL.md。Dim06 + 官方来源。
7. **权重级路线对个人工程用户可落地性低**：最低 2×80GB GPU，主流 8×A100。Dim09 多源一致。
8. **风险共识**：自生成技能/记忆若无验证环会污染（CoEvoSkills 实验证明无效）；skill 生态存在真实供应链投毒（ClawHavoc，Snyk 测 13.4% skill 含 critical 问题）。Dim04/06 一致。

### Medium Confidence（单一权威来源）
- GenericAgent 13.8k★（GitHub 页面直采 2026-05 + OSSInsight 13,762，可信；增长曲线 4→8→13.8k 连续）
- EvoAgentX 3.2k★ MIT，内置 TextGrad/AFlow/MIPRO/SEW/EvoPrompt/MAP-Elites 六优化器（Dim10 实采）
- mem0 63.6k★、Graphiti/Zep 30.1k★（Dim05 实测）
- DGM 2.2k★/Apache-2.0、SICA 386★/MIT、ADAS 1.6k★/Apache-2.0（Dim01 shields.io 核实）
- Hermes Agent 233k★/MIT（Dim05 多源交叉，但 4 个月 17k→233k 增长异常，存疑，引用时需带警示）
- SkillClaw 2.4k★ MIT 代理模式（Dim04 单源）
- MAS-Zero Apache-2.0 已开源（Dim08 单源）
- SE-Agent Verified 80%（Dim07 单源）
- SWE-Exp 44★ Apache-2.0 四阶段经验库（Dim07 单源）

### Low Confidence / 待核
- pskoett self-improvement 280★、darwin-skill、Hermes-Mind-Skill 等社区 skill 的精确 stars 与 license（GitHub API 限流，二手数据）
- 两个 awesome 列表当日精确 stars
- AFlow 官方优化总成本（仅有 $22.5/任务训练成本单源）

### Conflict Zone（已在报告中标注处理方式）
1. **DSPy stars 不一致**：Dim03 报 37.4k（2026-08-20 实抓）；外部来源报 28k（2026-04）、~34k（mid-2026）。→ 时间性差异，报告中采用"约 3.4-3.7 万（2026 年中至 8 月）"区间表述。
2. **superpowers stars**：Dim06 报"~25万"；外部核实 2026-04 为 147k、2026-06 底为 200k+。→ 采用"2026 年 6 月底超 20 万"的保守表述。
3. **OpenEvolve stars**：Dim02 报 7.2k（shields.io 2026-08-20）；2026-05 报道为 6.2k。→ 时间性增长，采用"约 7k（2026-08）"。
4. **Hermes Agent 增长曲线异常**：17k→233k/4个月，可能存在刷量或统计口径问题。→ 报告中保留数据但加显著警示。
5. **Alita 879★ 但官方未开源代码**（仅 README）→ 明确标注"不可用"。

## 二、许可证陷阱汇总（二开必读）
- **CC 非商用**：Meta HyperAgents（CC 非商用）、SWE-RL（CC BY-NC 4.0）、Synapse（非商用）
- **无 LICENSE（法律灰区）**：AutoSkill、R-Zero、LATM/CREATOR/CRAFT、AgentSquare/MaAS 等 7 个学术仓库、hermes-agent-self-evolution
- **安全许可（MIT/Apache-2.0）**：DSPy、GEPA、OpenEvolve、Live-SWE-agent、GenericAgent、EvoAgentX、mem0、DGM、SICA、ADAS、verl/TRL/OpenRLHF/slime

## 三、Phase 5 结论
冲突项均已通过时间性解释或保守表述解决，无需追加验证 agent。所有 Low Confidence 项在最终报告中明确标注。

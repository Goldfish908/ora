# 程序性 Memory 与 OR 建模近邻工作审查 v0.1

日期：2026-11-12 · 范围：围绕“迁移记忆内容，还是迁移记忆生产/验证程序”进行定向检索。不是完整系统综述；最终投稿前仍需精读全文和官方制品。

## 1. 最直接的 OR 近邻

| 工作 | 记忆表示与使用 | 验证和迁移 | 对本项目的约束 |
|---|---|---|---|
| [OptiSkill](https://arxiv.org/html/2609.22987v1) | 层级 SkillBank：Global Strategies 存适用场景与有序建模程序，Step Experiences 存局部触发与纠错指导；按问题类型和语义匹配检索 | solver 输出与参考答案核验；测试批内缓存候选，批级支持、修复和历史成功回归检查后晋升；8 个 OR benchmark | 已覆盖程序性技能、作用域、跨数据集复用、验证晋升和可靠性标签。不能把这些作为我们的新概念 |
| [OptSkills](https://arxiv.org/html/2605.29829v1) | 按优化 archetype 聚类，将同族成功轨迹蒸馏成 workflow-level skills；分布偏移时细化或扩库 | 明确区分 ID/OOD，覆盖大规模 MIPLIB-NL 与 NLCO | 已覆盖“结构而非题面措辞”的技能复用。我们的差异不能只说“按机制组织 memory” |
| [ArchOR](https://arxiv.org/html/2610.41909v1) | 在 OptSkills 库上加入结构表示学习、结构签名检索与基线保持仲裁 | 同库、同基座、同 benchmark 检验检索增益；案例显示同族但不同流动假设仍会误选 | 说明结构检索与误激活控制已有直接先例；我们的 trigger/embedding 不是独立贡献 |
| [AlphaOPT](https://arxiv.org/html/2510.18428v4) | 从有限监督和失败轨迹构建 solver-verified 经验库，经验含 taxonomy、condition、explanation、example | 通过求解输出验证和检索复用改善建模 | 已覆盖从失败提炼带适用条件的 OR 经验；需要区分独立业务语义证据与单纯 solver/reference correctness |
| [OptiLoop](https://arxiv.org/html/2605.27630v1) | 场景级 failure/fix lessons + 跨场景 meta-lessons；测试时冻结；同时支持 CodeFix 与 Reformulate | 用协调环中的行为证据验证；40/40 场景划分含新结构组合 | 已覆盖元经验、验证驱动修复与测试冻结。其主场景是 ADMM 协调，不等同于我们的通用解级业务检查 |

## 2. 通用 Agent 程序性记忆

- [AWM](https://arxiv.org/abs/2409.07429)：从成功轨迹归纳可复用 workflows，离线和在线均可，报告跨任务、网站和域迁移。
- [Memp](https://arxiv.org/html/2508.06433v3)：系统研究程序性记忆的 Build/Retrieve/Update，包含细粒度步骤与高层脚本抽象、验证过滤、修订和淘汰。
- [LEGOMem](https://arxiv.org/html/2510.04851v1)：将轨迹拆成模块化程序记忆，并研究 orchestrator 与执行 agent 的不同记忆位置。
- [ExpeL](https://arxiv.org/html/2308.10144v3)：从成功/失败轨迹提炼自然语言 insights，并检索成功轨迹；支持源域到目标域的正向迁移。
- [Learn to Memorize](https://arxiv.org/html/2508.16629v1)：把存储、检索、使用组成可优化的 memory cycle，直接研究“如何记忆”的参数化优化。
- [GovMem](https://arxiv.org/html/2607.02579v1)：将记忆写入视为证据治理，检查来源依赖、反证、作用域和 review；其外部人工复核表明表面 verification 仍可能不可靠。
- [BASM](https://arxiv.org/html/2608.22339v1)：直接研究“何时不应模仿技能”，为技能加入适用条件、风险线索、避免规则与恢复说明；表明成功轨迹技能也会提高错误工具调用的置信度。适用边界、拒绝模仿和修复提示因此也已有直接先例。

因此，以下主张均不足以构成独立创新：

- 把轨迹蒸馏成程序、技能或工作流；
- 用结构/archetype 替代表面文本检索；
- 为经验添加适用条件、来源、版本或可靠性；
- 用成功/失败轨迹更新记忆；
- 通过回归检查后再晋升记忆；
- 笼统地说“迁移记忆方法，而不是记忆内容”。

## 3. 仍可检验的窄差异

我们的研究问题必须进一步限定为：

> 在 OR 解级业务语义检查中，迁移一套诊断、数值重算、独立验证与 UNKNOWN 处理程序，是否比迁移旧域文本条款更可靠？这种收益能否在独立标签、自然错误和端到端修复中成立？

与近邻的潜在差异不在“程序性记忆”名称，而在以下组合：

1. **验证对象**：不是只比较 solver objective 与参考答案，而是对返回解执行业务不变量重算，并区分业务可行、目标值合格和模型语义等价。
2. **迁移对象**：通用诊断/验证程序与抽象机制模式可复用；字段绑定、具体业务条款和 witness 在本地重新验证，不要求直接跨域。
3. **失效语义**：`SATISFIED / VIOLATED / UNKNOWN / NOT_APPLICABLE` 分开；UNKNOWN 不计检出，也不能在最终报告中冒充安全。
4. **评价口径**：除准确率外，测可执行后的条件业务正确率、干净解误报、误激活、`harmed_win`、UNKNOWN 和全成本。
5. **因果协议**：共享初始候选与业务信息，比较文本经验、程序性指导及二者组合；固定制品检出与端到端修复分开报告。

这些差异是否成立必须由实验支持，不能再通过更换“SkillBank/RSI/DVSA”等名称获得。

## 4. 当前先导的定位

`docs/paper/procedural_memory_pilot_protocol_v0.1.md` 只做 NLP4LP dev 上零修复 authoring 四臂对照，辅以开发内 CEGIS 上界。它能回答：

- 通用程序是否改变检查器的检出、误报与 UNKNOWN；
- 声明式经验与程序是否互补；
- 是否值得继续做第二开发域和端到端修复。

它不能回答：

- 是否优于 OptiSkill/OptSkills 的完整系统；
- 是否实现跨域端到端自进化；
- 是否普遍提高 solver accuracy 或达到 SOTA；
- 是否证明“记忆方法”已迁移到 sealed 测试集。

若要形成 ICML 主贡献，后续必须加入同初始候选的自然修复、独立业务标签、第二模型或第二业务域，以及与强 skill 方法的同口径对照。

# Agent 技能层（code-carrying skill）自进化：机制全景与可复用设计

- **调研日期**：2026-08-29
- **调研对象**：代码技能库的生成-验证-沉淀、检索与组合、版本治理、技能作为可进化资产、组合优化/求解器代码生成
- **背景系统**：推理+验证 solver，冻结 Qwen 27B，CO-Bench/JSSP 评测；已有 prompt patch 跨代进化（(1+λ)+archive、阶梯评估、晋升协议、immutable generation snapshot）；实证发现"prompt 适合传判断、不适合传纪律"（时间治理纪律 patch 0.4464 惨败），假说"LLM 抄代码比守纪律可靠"；已建两条 code-carrying skill（solve() 时间预算 idiom；ast.parse+约束自检骨架），skill 形态 = patch body 携带可运行代码骨架，agent 生成 solve() 时参考/复用（runtime 冻结）。
- **检索规模**：8 轮 web 检索、29 条独立查询（中英文混合），覆盖 arXiv/GitHub/官方工程博客，另打开 4 篇论文全文核对。
- **证据强度标注**：⭐⭐⭐ = 同行评议/官方文档+定量实验；⭐⭐ = arXiv 预印本定量实验；⭐ = 工程博客/二手转述/定性。

---

## 0. 结论速览（TL;DR）

1. **"代码载体 > 文本纪律"有多条独立证据链**（§4）：SkillsBench 证明 LLM 自写 skill 平均 −1.3pp 而精选 skill +16.2pp[^12^]；EvolveTool-Bench 直接对照"代码级进化 vs 策略（文本）级进化"，代码级胜出且"未测试的代码比没有代码更糟"[^14^]；CodeAct 证明可执行代码动作比 JSON/Text 动作成功率高 20%[^16^]；s1 的 token-instruction 实验证明"prompt 里的时间/长度纪律几乎不被遵守，而 decoding 层强制（budget forcing）可达完美控制"[^17^]——这与背景系统"时间治理纪律 patch 惨败、改用 solve() 时间预算 idiom"的转向高度同构。
2. **生成-验证-沉淀的成熟范式**：验证环必须是执行级的（单测/沙箱运行/自验证），LATM 的"生成单测→运行→修 function call"三段式[^2^]与 Voyager 的"执行反馈+自验证后才入库"[^1^][^26^]是两条主干；背景系统的"阶梯评估+晋升协议"与 EvoSkill 的 held-out 验证集 + Pareto frontier 晋升[^7^]同构，可直接对齐。
3. **技能库膨胀已被实证为"静默失效模式"（library drift）**：无治理的积累导致检索退化与有害注入，治理配方 = 结果驱动退休 + 活跃技能上限 + 元技能先验[^13^]。背景系统的 archive 若只增不减，需在 v1 就内置退休机制。
4. **"代码骨架 + LLM 填充"正是 FunSearch/EoH/LLaMEA 的主流形态**：固定程序骨架、只进化关键函数（如 priority）、执行报错→适应度清零、岛模型保多样性[^18^][^19^][^21^]；CO-Bench 揭示当前 agent 的短板恰在"可行性约束处理不足"[^22^]——这直接支持背景系统第二条 skill（ast.parse+约束自检骨架）的选题。

---

## 1. 代码技能库的生成-验证-沉淀机制

### 1.1 Voyager — 执行反馈 + 自验证 + 嵌入式代码技能库（奠基范式）

- **来源**：Wang et al., "Voyager: An Open-Ended Embodied Agent with Large Language Models", arXiv:2305.16291 (2023-05-25, TMLR)，https://arxiv.org/abs/2305.16291 [^1^]
- **核心机制**：三件套 = 自动课程（提出渐进任务）+ 技能库（可执行 JS 代码）+ 迭代提示（环境反馈、执行错误、自验证）。技能"是 temporally extended, interpretable, and compositional"，入库即不再修改，靠新增而非覆盖来避免遗忘。验证环 = 代码在环境中真实执行 + GPT-4 自验证任务是否完成，通过后才写入技能库；检索按自然语言描述 embedding 相似度[^1^][^26^]。
- **证据强度**：⭐⭐⭐（3.3× 独特物品、15.3× 技术里程碑速度；新世界零样本泛化）。"It obtains 3.3× more unique items... unlocks key tech tree milestones up to 15.3× faster than prior SOTA"[^1^]
- **可复用性**：高。"只增不改、执行验证后才入库、description 索引"是几乎所有后续系统的默认模板。
- **对背景系统适用判断**：**直接适用**。背景系统的 immutable generation snapshot 与 Voyager 的"新技能不修改旧技能"哲学一致；但注意 Voyager 的自验证是 LLM 裁判，CO-Bench 场景有确定性验证器（makespan/gap），应优先用确定性验证而非 LLM 自评。

### 1.2 LATM — 工具制造三段式：proposing → verification（单测）→ wrapping

- **来源**：Cai et al., "Large Language Models as Tool Makers", arXiv:2305.17126 (2023-05)，https://arxiv.org/abs/2305.17126 [^2^]
- **核心机制**：贵模型当 tool maker、便宜模型当 tool user。制造分三步："(i) tool proposing... if the tool is not executable, report the error and generate a new one; (ii) tool verification: the tool maker runs unit tests on validation samples, if the tool does not pass the tests, report the error and generate new tests (in the function calls in unit tests); (iii) tool wrapping"[^2^]。关键设计：单测由 LLM 用验证样本自动生成，失败时**只修单测里的 function call 不改函数体**；单测同时充当"自然语言问题→函数调用"的示范，实现工具的一次制造、处处复用。dispatcher 识别缓存命中准确率 96%±3%。
- **证据强度**：⭐⭐（BIG-Bench 等任务上 cost-effective；GPT-3.5 在难任务上 0/5 造不出工具，说明制造端需要强模型）[^2^]
- **可复用性**：高。验证环的"生成测试→执行→分角色修错"结构清晰可抄。
- **对背景系统适用判断**：**验证环设计可直接借用**：为每条 code-carrying skill 生成小规模烟雾单测（如 solve() 在 toy JSSP 实例上运行且返回合法解、时间预算 idiom 在 deadline 内返回）；注意冻结 Qwen 27B 同时承担 maker/user，LATM 提示制造端能力门槛是真实存在的，27B 生成质量需实测。

### 1.3 CREATOR — 抽象推理（造工具）与具体执行（用工具）解耦

- **来源**：Qian et al., "CREATOR: Tool Creation for Disentangling Abstract and Concrete Reasoning of Large Language Models", arXiv:2305.14318 (2023-05-23, EMNLP Findings)，https://arxiv.org/abs/2305.14318 [^3^]
- **核心机制**：LLM 先写工具的 documentation（抽象设计）再做 code realization（具体实现），把"创造工具"与"用工具解题"拆成两个阶段，降低单次推理负荷。观察到工具创造的三个层级：改造现有工具、串联多工具、层级化创造（主工具调用子工具，"offloading more reasoning burdens"）[^3^]。
- **证据强度**：⭐⭐⭐（MATH/TabMWP 上超过 CoT/PoT/工具使用基线）
- **可复用性**：中-高。"先 doc 后 code"的两阶段生成适合长骨架 skill。
- **对背景系统适用判断**：**适用**。code-carrying skill 的 patch body 可采用"接口注释/文档块 + 代码骨架"结构，让 LLM 先读到纪律的语义再抄代码；层级化工具创造支持未来 skill 嵌套调用（骨架内调用已沉淀的子骨架）。

### 1.4 CRAFT — 离线建库：验证→抽象→去重，推理时检索复用

- **来源**：Yuan et al., "CRAFT: Customizing LLMs by Creating and Retrieving from Specialized Toolsets", arXiv:2309.17428 (2023-09-29, ICLR 2024)，https://arxiv.org/abs/2309.17428 [^4^]
- **核心机制**：离线阶段用 GPT-4 解训练样本收集代码方案，"Following a validation step ensuring the correctness, these solutions are abstracted into code snippets to enhance reusability, and deduplicated for higher quality"；推理时检索相关 snippet，直接执行或以其为条件生成[^4^]。
- **证据强度**：⭐⭐⭐（ICLR；且发现"scaling up the number of tools... consistent performance improvement"——在该设置下库规模增长未退化，因其检索+去重设计）[^4^]
- **可复用性**：高。"验证→抽象泛化→去重"三步是沉淀管线的最小完整形态；去重是防膨胀的第一道闸。
- **对背景系统适用判断**：**直接适用**。背景系统晋升协议中可加"抽象化+去重"环节：新 code skill 入库前与 archive 中现有 skill 做语义/AST 级查重，防止同义 idiom 多副本稀释检索。

### 1.5 SkillWeaver — 自主探索→练习→蒸馏为 API 的"磨炼"管线

- **来源**：Zheng et al., "SkillWeaver: Web Agents can Self-Improve by Discovering and Honing Skills", arXiv:2504.07079 (2025-04-09)，https://arxiv.org/abs/2504.07079 [^5^]
- **核心机制**：agent 在新网站上自主发现技能，"executes them for practice, and distills practice experiences into robust APIs"；迭代探索持续扩充"lightweight, plug-and-play APIs"库[^5^]。
- **证据强度**：⭐⭐（WebArena +31.8% 相对成功率、真实网站 +39.8%；强 agent 合成的 API 迁移给弱 agent +54.3%——**技能跨 agent 可迁移的直接证据**）[^5^]
- **可复用性**：中-高。"练习→蒸馏"强调了入库前要用真实执行把脆弱代码磨稳。
- **对背景系统适用判断**：**适用**。code skill 晋升前应在阶梯评估的多档实例上"练习"若干次再固化骨架形态；其跨模型迁移证据也支持"未来迁移其他数据集"时技能库可携带。

### 1.6 Anthropic Agent Skills — 生产级形态：SKILL.md + 渐进披露 + 捆绑脚本

- **来源**：Zhang, Lazuka, Murag, "Equipping Agents for the Real World with Agent Skills", Anthropic Engineering Blog (2025-10-16, 更新 2025-12-18；已开放为标准 agentskills.io)，https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills [^6^]
- **核心机制**：技能 = 含 SKILL.md（YAML frontmatter: name+description）的目录 + 可选 scripts/references/assets。三级渐进披露：L1 元数据常驻（~100 token/skill）、L2 SKILL.md body 触发时载入、L3 附属文件按需读取，"the amount of context that can be bundled into a skill is effectively unbounded"[^6^]。官方最佳实践："Provide code templates, not descriptions. Agents produce more reliable output when they can pattern-match against exact examples"（转述自规范文档，见 [^6^] 配套最佳实践）。安全警告：技能必须来自可信源，可携带恶意代码。
- **证据强度**：⭐⭐⭐（官方文档+生态事实标准；定量少）
- **可复用性**：高。这是"patch body 携带代码骨架"的工业形态参照：SKILL.md 文本负责触发与语义，scripts/ 负责确定性执行。
- **对背景系统适用判断**：**强烈参照**。背景系统的 skill patch 可直接采用 frontmatter（name/description/when-to-use/when-NOT-to-use）+ body（代码骨架 + 使用示例）结构；注意 Anthropic 安全模型假设 agent 有文件系统，而背景系统 runtime 冻结——代码骨架只能以 prompt 内嵌形式注入，须控制 token 预算（见 §2 渐进披露的替代实现）。

### 1.7 EvoSkill — 冻结模型下的技能级进化（与背景系统最同构）

- **来源**：Provenzano et al., "Automated Skill Discovery for Multi-Agent Systems / EvoSkill", arXiv:2603.02766 (2026-02-20)，https://arxiv.org/html/2603.02766v1 [^7^]
- **核心机制**：三 agent 协作：Executor 跑任务、Proposer 做失败归因并决定"create 新 skill 或 edit 旧 skill"、Skill-Builder 把提案物化为技能文件夹（SKILL.md + 触发元数据 + helper 脚本）。**晋升协议 = held-out 验证集打分 + 容量受限 Pareto frontier（K=3），候选须胜过 frontier 最弱者才准入**；反馈历史 H 记录所有提案的成败防止重复。**版本治理用 git**：每个 agent program 一个 branch，program.yaml 记录 parent 指针、generation 计数、分数，未入 frontier 的 child branch 直接删除，"any historical configuration can be restored via a single git checkout"[^7^]。
- **证据强度**：⭐⭐（OfficeQA +7.3pp、SealQA +12.1pp；技能零样本迁移 SealQA→BrowseComp +5.3pp——**技能级优化比 prompt 级优化更可迁移的直接证据**）[^7^]
- **可复用性**：高。其 git-branch lineage 与背景系统的 immutable generation snapshot 是同构实现，可直接互证。
- **对背景系统适用判断**：**最接近的参照系**。三点可抄：(a) Proposer 提示词中的反模式清单（"DON'T propose a new skill if an existing one covers similar ground → propose an EDIT"；"DON'T create narrow skills that only fix one specific failure"）[^7^]；(b) skill-merge 配置（合并多轮独立进化发现的互补技能）效果最佳（67.9%），支持背景系统的 archive 多样体并行进化后合并；(c) 15% 训练量反而弱于 10%，提示进化过拟合风险，与阶梯评估的档位设计呼应。

---

## 2. 技能检索与组合

### 2.1 描述索引与触发条件设计

- **Voyager 式**：技能以 GPT-4 生成的自然语言描述做 embedding 索引，按任务语义相似度检索 top-k[^1^][^26^]。
- **Agent Skills 式**：name+description 元数据常驻上下文，触发完全交给模型自身判断；官方最佳实践要求 description 写清"what it does AND when to use it"，并建议写"when not to use"（负向范围）[^6^]。EvoSkill 生成的技能 description 即含明确触发短语（"Use this skill when... Triggers on tasks requiring..."）[^7^]。
- **形式化**：SoK 将技能定义为 S=(C,π,T,R)，C 是 applicability condition（适用条件谓词），R 是 (name, params, returns) 可调用接口——触发条件被提升为技能的一等组件[^8^]。
- **对背景系统适用判断**：技能数量少（当前 2 条）时触发不是问题，但 patch 元数据应从第一天就带"when-to-use / when-not-to-use"字段，为库增长后的检索预留结构；冻结 runtime 下无 embedding 检索器，触发靠 patch 注入选择，本质是把 C 外置到进化循环里（由晋升协议决定注入哪条 skill）。

### 2.2 技能数量增长后的检索退化（实证与对策）

- **退化实证（工具域）**：RAG-MCP 报告工具数增加后准确率显著退化，检索式工具选择将准确率从 13.62% 提升到 43.13% 且 prompt token 减半；实践退化点在 ~10-20 个活跃工具即出现（OpenAI 硬上限 128）[^11^]。BoR 研究用 chance-corrected 指标量化"给 agent 看多少工具"：registry 20→3251 规模下，学到的按查询定深策略在 BFCL（370 工具）上平均只给 7 个工具即达到给 50 个的 90.3% vs 90.8% 覆盖率[^10^]。
- **退化实证（技能域）**：Library Drift 证明无治理的技能积累导致"retrieval degradation, false-positive injections, and performance stagnation"——即使每条技能单看都合理，库级失效是系统性的（"retrieval dilution and stale injection"）[^13^]。Agent Skills 综述将"skill selection at scale"列为开放挑战：选错技能会加载无关指令造成 distraction[^9^]。
- **对策清单**：(a) 渐进披露——只让元数据常驻（[^6^]；冻结 runtime 下的等价物 = patch 系统里只放 skill 的 id+一句话描述，骨架按需展开）；(b) 检索/路由分层（retrieve-and-rerank，SkillRouter 在 ~80K 技能 registry 上验证[^13^]转述）；(c) 活跃技能上限（bounded active-cap）[^13^]；(d) 去重与合并（CRAFT[^4^]、AutoSkill 的 add/merge/discard[^15^]）。
- **证据强度**：⭐⭐（工具域证据强于技能域；技能域的 Library Drift 是单一作者预印本，但含 8 组消融）[^13^]
- **对背景系统适用判断**：当前 2 条 skill 无检索问题，但跨代进化会让 archive 增长：**建议在 N≈10 前就启用"每代注入 top-k 条 skill 描述 + 仅展开被选骨架"的两级结构**，并把"注入但未使用/使用但未提分"记入 per-skill 贡献分（见 §3.2）。

### 2.3 技能组合/嵌套调用

- **代码天然可组合**：SoK 指出 code-as-skill "compose of function calls, imports, and control flow"，层级组合对应 RL options 框架的子例程结构[^8^]；CREATOR 观测到 LLM 自发创造层级工具（主工具调用 is_prime 子工具）[^3^]；Voyager 技能"compositional... compounds the agent's abilities rapidly"[^1^]。
- **混合 NL+代码形态**：Pattern-5 hybrid macro（SKILL.md 指令 + 脚本调用）是生产主流，风险是"boundary ambiguity: when instructions conflict with code, the agent must decide which to follow"[^8^]——**对背景系统的直接警示：patch 文本纪律与代码骨架若语义冲突，agent 行为将不稳定；应让文本只解释"何时用"，纪律全部写进代码**。
- **组合评测是开放问题**："testing how multiple skills interact and whether they conflict with each other remains an open research question"[^9^]。SkillsBench 发现"focused skills（2-3 模块）优于 comprehensive 文档"[^12^]。
- **对背景系统适用判断**：两条现有 skill（时间预算 idiom、约束自检骨架）应保持**正交且各自 focused**；组合方式初期用"同一 patch 内并列注入"而非嵌套调用，待实测后再引入骨架间 import 关系。

---

## 3. 技能版本治理

### 3.1 生命周期与 RETIRE：从"只增不减"到结果驱动退休

- **SoK 生命周期七阶段**：discovery → practice/refinement → distillation → storage → retrieval/composition → execution → **evaluation/update（"revising, replacing, or retiring skills as environments and requirements evolve"）**；并指出"code skills break when underlying APIs... change, necessitating maintenance and version management"[^8^]。
- **AutoSkill**：双环架构（执行环 + 进化环），每个交互后决定技能"add, merge, or discard"——merge 是冲突/冗余治理的具体算子[^15^]。
- **EvoSkill**：create/edit 二选一提案 + frontier 驱逐（容量 K=3，弱者被淘汰）+ 失败分支删除；edit 优先于 create 的反模式纪律[^7^]。
- **证据强度**：⭐⭐（AutoSkill/EvoSkill 均为预印本；SoK 为系统性综述）
- **对背景系统适用判断**：背景系统已有晋升协议，缺**退休协议**。建议：skill 设 N_min 次试用期 + 贡献分 ≤ −τ 即退休（参数可先借 Library Drift 的 N_min=100, τ=0.10 再按 CO-Bench 实例预算缩小）[^13^]；archive 中同义 skill 走 merge 而非并存。

### 3.2 技能库膨胀的实证研究：Library Drift（必引）

- **来源**：Zhang et al., "Library Drift: Diagnosing and Fixing a Silent Failure Mode in Self-Evolving LLM Skill Libraries", arXiv:2605.19576 (2026-05-19, ICML 2026 Workshop)，https://arxiv.org/abs/2605.19576 [^13^]
- **核心发现**：(1) 定义 library drift：累积产物把期望表现压到无技能基线之下，失效是静默的（无显式错误信号）；(2) 三种子模式——stagnation（技能到不了 solver）、bloat（无限增长毁掉检索）、erosion（治理过激毁掉有用技能；其 A4 消融"premature retirement"造成主动伤害 −0.019）；(3) 修复配方 "Ratchet" = 结果驱动退休（n(s)≥100 且 ĉ(s)≤−0.10 才退）+ 活跃上限 + 元技能先验，held-out pass@1 从 0.258 → 0.584（+0.328，MBPP+ hard-100，100 轮）；(4) 诊断工具 = append-only 证据日志：per-skill 贡献分、归因判决、路由参与度，"make the failure visible before it reaches end-task scores"[^13^]。
- **证据强度**：⭐⭐（单作者预印本+workshop，但含 8 组消融、机制分离清晰；与 SkillsBench 现象互证）
- **对背景系统适用判断**：**直接照搬三件套**：(a) 每条 skill 记贡献分（注入且被 solve() 复用后 fitness 差分归因）；(b) archive 设活跃上限，超出后按贡献分退休；(c) 进化日志 append-only，监控"路由/注入参与度"，在 end-task 指标下降前发现漂移。其名言"The bottleneck in self-evolving skill libraries is not the author—it is the librarian"[^13^]应作为治理设计原则。

### 3.3 工具库作为软件制品的质量治理：EvolveTool-Bench

- **来源**：Kaliyev, "EvolveTool-Bench: Evaluating the Quality of LLM-Generated Tool Libraries as Software Artifacts", arXiv:2604.00392 (2026-04-01)，https://arxiv.org/html/2604.00392v1 [^14^]
- **核心发现**（六条 finding 全部相关）：任务完成率（TC）掩盖质量差异（18% 质量缺口 TC 不可见）；**代码级进化（ARISE, ETS=0.603）优于策略（文本）级进化（EvoSkill, ETS=0.520），后者"creates zero executable tools and identical library health to no-evolution"**；"Untested code is worse than no code"（一次性生成未验证的工具库健康度 38.3% 低于不进化 41.4%）；奖励设计是瓶颈（启发式奖励产零工具，LLM-as-judge 才触发进化）；自生成测试漏缺陷，hidden tests 能抓到；便宜模型（Haiku）匹配贵模型质量[^14^]。
- **证据强度**：⭐⭐（预印本，99 任务，作者自承无统计显著性检验）
- **对背景系统适用判断**：(a) 给 code skill 的晋升指标不能只看 end-task fitness，要加"库健康度"维度（复用率、可测试性）；(b) 背景系统的阶梯评估正是"hidden tests"角色——保留晋升用高档实例不与进化训练实例重叠；(c) 未验证代码是负债：ast.parse 自检骨架这类"可被静态检查"的 skill 应优先于纯文本 skill 入库。

### 3.4 EDIT vs CREATE 的冲突纪律

- EvoSkill 的 Proposer 提示词是目前公开文献中最完整的技能提案纪律：已有技能本应防住失败却未防住 → EDIT；无技能覆盖 → CREATE；"DON'T propose capabilities that overlap with existing skills -> consolidate instead"[^7^]。技能间冲突的形式化评测仍"未查到"成熟工作（综述将其列为开放问题[^9^]）。
- **对背景系统适用判断**：把这段反模式清单直接翻译进背景系统的 patch 生成 prompt；晋升时若新 skill 与库内既有 skill 语义重叠 > 阈值，走 edit（原位替换并保留 git lineage）而非新增。

---

## 4. "技能作为可进化资产"的实证

### 4.1 技能库进化 vs 单技能/无技能的对照证据

- **SkillsBench（最重要的三条件对照）**：86 任务 × 11 域 × 7308 条轨迹，no-skill / curated-skill / self-generated-skill 三条件。"Curated Skills raise average pass rate by 16.2 percentage points... Self-generated Skills provide no benefit on average (−1.3pp)"；域差异巨大（医疗 +51.9pp vs 软件工程 +4.5pp、数学 +6.0pp）；16/84 任务为负增益；"Focused Skills with 2-3 modules outperform comprehensive documentation"；小模型+精选技能可匹配无技能大模型[^12^]。
- **Library Drift 的纵向对照**：同一冻结 LLM，无治理 +0.002 vs 有治理 +0.328——**治理本身比技能内容更决定收益**[^13^]。
- **技能集 vs 单技能**：EoH-S 把设计目标从"单一冠军启发式"改为"互补启发式集合"，用互补性感知种群管理应对实例分布偏移[^25^]；EvoSkill 的 skill-merge（合并多条独立进化线的技能）优于任何单线结果[^7^]。
- **对背景系统适用判断**：(1+λ)+archive 已是"种群级"结构，比单技能进化先进；但 SkillsBench 警告**自生成 skill 零增益**——背景系统的两条 code skill 必须经过阶梯评估的 curated 晋升（已是设计），且实测时务必保留"no-skill 基线"和"文本版同语义 skill"两个对照臂，才能干净验证"代码载体 > 文本纪律"假说。

### 4.2 code skill vs prompt skill 的直接对比证据

| 证据 | 内容 | 强度 |
|---|---|---|
| EvolveTool-Bench Finding 2 | 代码级进化 ETS=0.603 vs 策略（文本）级进化 ETS=0.520；文本级进化健康度与不进化相同[^14^] | ⭐⭐（同基准直接对照，单作者预印本） |
| CodeAct | 可执行 Python 动作 vs JSON/Text 动作：17 个 LLM 上成功率高至 +20pp（GPT-4: 74.4% vs 53.7%），轮次少 30%；"The Python interpreter acts as an automatic, zero-cost error signal"[^16^] | ⭐⭐⭐（ICML 2024） |
| s1 budget forcing | **时间治理域的最直接证据**：prompt 里的 token 数量纪律"after training the model hardly follows the token instruction... often overshoots the limit"，而 decoding 层强制执行"budget forcing leads to perfectly controlled"[^17^] | ⭐⭐⭐ |
| PoT/PAL 解耦 | 把计算卸载给 Python 解释器，数值推理较 CoT +10pp，消除"computation hallucination"[^27^] | ⭐⭐（转引） |
| SoK Pattern-2 | code-as-skill 的核心优势是 determinism："given the same inputs, a code skill produces the same outputs, enabling traditional software testing and verification"[^8^] | ⭐⭐（综述性论断） |
| SoK Pattern-5 风险 | NL 指令与代码冲突时行为不一致（boundary ambiguity）[^8^] | ⭐⭐ |
| Anthropic 最佳实践 | "Provide code templates, not descriptions. Agents produce more reliable output when they can pattern-match against exact examples"[^6^] | ⭐⭐⭐（官方指南） |

- **直接回答"有没有文献验证过代码载体 > 文本纪律"**：**没有完全同命题的论文，但有四条独立证据链收敛**：(i) 动作空间层（CodeAct：代码动作 > 文本动作）；(ii) 进化资产层（EvolveTool-Bench：代码进化 > 策略文本进化）；(iii) 纪律执行层（s1：prompt 长度/时间纪律不可守 vs 程序强制完美可控）；(iv) 资产质量层（SkillsBench/Library Drift：未 curated 的自写 skill 有害，code 可测试性使其可 curated）。**s1 的 token-instruction 失败与背景系统"时间治理纪律 patch 0.4464 惨败"几乎是同一现象的两次独立观测**，可作为背景假说最强的外部旁证。
- **对背景系统适用判断**：假说方向获文献支持，但注意三条边界：(a) CodeAct 的开源小模型收益大但绝对水平仍远低于强模型（Mistral-7B 12.2% vs GPT-4 74.4%）[^16^]——27B 冻结模型的"抄代码保真度"需实测；(b) 代码技能 brittle（API 变化即坏）[^8^]，solve() 骨架依赖的 driver 接口必须冻结在 immutable snapshot 里写明版本；(c) hybrid 冲突风险——patch 文本不要再写与骨架语义重叠的纪律。

---

## 5. 组合优化/求解器领域的代码生成经验（"代码骨架+LLM 填充"形态）

### 5.1 FunSearch — 骨架内只进化一个函数 + 执行评估 + 岛模型

- **来源**：Romera-Paredes et al., "Mathematical discoveries from program search with large language models", Nature (2023-12)，https://www.nature.com/articles/s41586-023-06924-6；机制细节转引自 [^18^]
- **核心机制**：用户提供的 specification = `evaluate` 函数 + 初始程序骨架（其中只有特定函数如 `priority` 待进化）；LLM 只对骨架中被标记的部分提修改；evaluator 在真实输入上打分；**岛模型 EA 维护多样性，采样偏好高分且短程序，best-shot prompting（喂 k=2 个好样例 v0/v1 回去）**；分布式异步并行[^18^]。
- **证据强度**：⭐⭐⭐（Nature；cap set n=8 从 496→512、online bin packing 超 first-fit/best-fit；消融确认岛模型与程序骨架均关键）
- **对背景系统适用判断**：**形态上完全同构**——背景系统的 solver = 固定 driver 骨架 + LLM 生成 solve()/priority 逻辑。三条直接经验：(a) 骨架是搜索空间的护栏，保住它（runtime 冻结反而天然满足）；(b) best-shot prompting：patch 注入时给 2 条历史最优 solve() 代码比给规则文本有效；(c) 偏好短程序的采样偏置可写进晋升协议 tie-breaker。FunSearch 的代价是百万级 LLM 查询[^19^]，背景系统阶梯评估正是预算控制手段。

### 5.2 EoH — thought 与 code 双载体协同进化

- **来源**：Liu et al., "Evolution of Heuristics: Towards Efficient Automatic Algorithm Design Using Large Language Model", arXiv:2401.02051 (2024-01-04, ICML 2024)，https://arxiv.org/abs/2401.02051 [^19^]
- **核心机制**：启发式 = 自然语言"thought"（高层思想）+ 可执行 code（实现），两者在进化框架中**同时进化**；2 探索 + 3 修改提示策略。TSP/oBPP/FSS 上超手工启发式与 FunSearch，且"around one million queries in FunSearch vs. 2000 queries EoH for oBPP"[^19^]（转引自对比研究，原始表述见 EoH 论文）。
- **证据强度**：⭐⭐⭐（ICML）
- **对背景系统适用判断**：**思想-代码双层结构正是"prompt 传判断 + 代码传纪律"的学术版**：thought（判断/策略）与 code（实现/纪律）配对进化。建议 code skill 的 patch 同时携带一段 thought（为什么这个时间预算分配有效）和骨架（怎么实现），变异时对两者分别操作——判断层变异空间大、代码层变异空间小，符合背景系统的实证哲学。

### 5.3 ReEvo — 反思进化与"语言梯度"，白盒/黑盒双视角

- **来源**：Ye et al., "ReEvo: Large Language Models as Hyper-Heuristics with Reflective Evolution", arXiv:2402.01145 (2024-02-02, NeurIPS 2024)，https://arxiv.org/abs/2402.01145 [^20^]
- **核心机制**：进化搜索探索启发式空间 + LLM 对两个启发式的相对表现做反思（short-term）并跨代积累洞见（long-term），形成"verbal gradient"；引入 fitness landscape analysis 与 black-box prompting；在 GLS 惩罚启发式、ACO 启发式度量、GA 遗传算子等 5 类算法 × 6 种 COP 上产 SOTA[^20^]。
- **证据强度**：⭐⭐⭐（NeurIPS）
- **对背景系统适用判断**：**反思对象的选择可直接借用**：不做绝对分数反思，而是给 LLM 看"父子两代 solve() 代码 + 相对 fitness 差"让其生成变异方向——比单点反思信号更密。白盒/黑盒区分对应背景系统：CO-Bench 有验证器可用白盒反思（看违反约束的具体位置），这正是约束自检骨架的养分来源。

### 5.4 LLaMEA — (1+1) 进化循环的工程细节（报错即零分、示例代码双刃剑）

- **来源**：van Stein & Bäck, "LLaMEA: A Large Language Model Evolutionary Algorithm for Automatically Generating Metaheuristics", arXiv:2405.20132 (2024-05-30, IEEE TEVC)，https://arxiv.org/abs/2405.20132 [^21^]
- **核心机制**：(1+1)/(1,1)-EA：每代 LLM 生成完整算法类，IOHexperimenter 自动评测 AOCC；**运行时错误直接记最低适应度（yt+1=0）**；反馈 prompt 携带历史算法名+均分+标准差列表防重复生成；"Either refine or redesign"把变异/重启选择权交给 LLM；**关键工程发现："including a small example code helps a lot in generating code without syntax and runtime errors. However, the example code could also bias the optimization search towards similar algorithms"**——故只用 random search 作种子[^21^]。
- **证据强度**：⭐⭐⭐（TEVC；BBOB 5D 上超 CMA-ES/DE）
- **对背景系统适用判断**：四条直接可抄：(a) 报错→适应度清零的硬规则与阶梯评估兼容（语法/接口错直接不晋升）；(b) 历史名字+分数列表防重复（对应 archive 摘要在变异 prompt 中常驻）；(c) **种子骨架的锚定偏置警告**——背景系统两条 code skill 会把所有后代 solve() 拉向同一形态，需保留"无 skill"或"最小骨架"的多样性种子；(d) (1+1) 与背景系统的 (1+λ) 同族，文献支持 (1+1)-elitist 在冻结预算下是强基线。

### 5.5 CO-Bench 基准本身揭示的 agent 短板（贴合背景评测集）

- **来源**：Sun et al., "CO-Bench: Benchmarking Language Model Agents in Algorithm Search for Combinatorial Optimization", arXiv:2504.04310 (2025-04-06, AAAI 2026)，https://arxiv.org/abs/2504.04310 [^22^]
- **核心发现**：36 个真实 CO 问题；30 分钟研究预算内 AI 生成算法在 25 题上超专家基线、3 题超 best-known；但**"current limitations, such as limited algorithmic novelty and insufficient handling of feasibility constraints"**、"they struggle to understand the problem constraints, and rely heavily on trial-and-error"[^22^]。
- **证据强度**：⭐⭐⭐（AAAI 2026）
- **对背景系统适用判断**：**直接论证了第二条 skill（ast.parse+约束自检骨架）的选题正确性**——可行性约束处理是全领域已知短板，把它做成代码级自检（而非文本提醒）恰是差异化资产；同时提示评测时 novelty 维度不必期待，技能层目标应锁定"约束合法性 + 时间治理"这类可靠性指标。

### 5.6 JSSP 专属：共享 solver 骨架 + 约束模板 + 反射记忆

- **来源**："An LLM-Driven Multi-Agent Evolution Framework for Solver Code Generation in Job Shop Scheduling", Mathematics 14(11):2010 (2026-06)，https://www.mdpi.com/2227-7390/14/11/2010 [^23^]；另 SeEvo（动态模糊 JSSP 调度规则进化），arXiv:2410.22657 [^24^]
- **核心机制**：三 agent 闭环：Agent 1"在结构化约束模板和**共享 solver 骨架**下构造可靠且行为多样的初始代码池"，Agent 2 做程序空间交叉 + best-so-far 变异，Agent 3 做带 trajectory-aware 反射记忆的代码级反思；消融显示初始化设计与反射修订均有实质贡献[^23^]。SeEvo 只允许 LLM 生成符合**固定函数名/输入/输出签名**的 HDR 代码片段，20 个案例自进化训练后即上线[^24^]。
- **证据强度**：⭐⭐（MDPI 期刊/预印本，JSSP 标准基准上超代表性元启发式）
- **对背景系统适用判断**：**形态完全一致**（共享骨架 + 接口签名约束 + 池级多样性 + 代码级反思）。背景系统的 solve() 接口约定 = 其"固定函数签名"；建议在 code skill 骨架中显式写出签名 docstring 与输入输出契约（SeEvo 证明这是 LLM 生成可用调度代码的充分约束）[^24^]。

---

## 6. 面向背景系统的可复用设计清单（综合）

按背景系统现有组件映射：

1. **patch 结构（code-carrying skill 形态）**：frontmatter（name / description 含 when-to-use 与 when-NOT-to-use）+ thought 段（判断，1-3 句）+ 代码骨架（纪律全在代码里，文本不重复纪律语义，避免 hybrid boundary ambiguity）[^6^][^8^][^19^]。骨架内显式写 solve() 签名契约[^24^]。
2. **验证环（入库前）**：三级——(a) 静态级：ast.parse + 接口签名 + 禁用 import 检查（现有骨架即此）；(b) 烟雾级：toy 实例真实执行，报错→零分不晋升[^21^]；(c) 阶梯级：多档实例 + held-out 晋升档（与进化训练档不重叠，防自生成测试漏缺陷）[^14^]。LATM 式"修错分角色"：语法错重生、语义错记录进反馈历史[^2^]。
3. **晋升协议对齐**：现有 (1+λ)+archive 可直接叠加 EvoSkill 的 frontier 容量约束与 round-robin 父代选择[^7^]；tie-breaker 偏好更短 solve()（FunSearch 偏置）[^18^]。
4. **退休协议（当前缺口）**：per-skill 贡献分（注入×复用×fitness 差分归因）+ N_min 试用期 + 负贡献退休 + archive 活跃上限；append-only 证据日志监控注入率/复用率，先于 end-task 指标发现漂移[^13^]。
5. **去重与合并**：入库前语义/AST 查重（CRAFT）[^4^]；重叠提案走 EDIT 并保留 git lineage（EvoSkill）[^7^]；多进化线产物定期 skill-merge[^7^]。
6. **检索退化预案**：N≈10 前启用"描述常驻 + 骨架按需展开"两级注入；变异 prompt 常驻"历史 skill 名+分数"列表防重复[^21^]。
7. **实测对照设计（验证"代码载体 > 文本纪律"）**：四臂——no-skill / 文本纪律版 / 代码骨架版 / 代码+thought 版；no-skill 臂必须保留（SkillsBench 证明自生成 skill 可负增益）[^12^]；保留最小骨架多样性种子防锚定[^21^]。
8. **迁移数据集预案**：技能 thought 层记"适用问题族"（EoH-S 互补性思想）[^25^]；SkillWeaver 跨 agent 迁移 +54.3% 与 EvoSkill 零样本迁移 +5.3pp 均支持技能库可携带，但 brittle 风险要求迁移后先跑静态级+烟雾级验证环[^5^][^7^][^8^]。

---

## 7. 检索覆盖与局限

- **独立检索**：8 轮 web_search 共 29 条查询（英文为主，中文 1 条无命中）+ 4 篇全文打开核对（EvoSkill、SoK、CRAFT、Library Drift 相关）。
- **"EDIT/RETIRE/deprecation"完整治理框架**：未查到单一系统提供完整三算子；最接近的是 AutoSkill（add/merge/discard）[^15^]、EvoSkill（create/edit+frontier 驱逐）[^7^]、Library Drift（结果驱动退休）[^13^]；技能间冲突的形式化检测"未查到"，综述明确列为开放问题[^9^]。
- **RAG-MCP 数字（13.62%→43.13%）**：来自二手科技媒体转述[^11^]，未直接核对原文，置信中等。
- **FunSearch 机制细节**：部分来自论文研读 wiki 转述[^18^]，主干结论有 Nature 原文背书。
- 多数技能进化系统（EvoSkill/AutoSkill/Library Drift/EvolveTool-Bench）为 2026 年预印本，未经同行评议，引用时已标注证据强度。

---

## 引用

[^1^]: Wang, G. et al. "Voyager: An Open-Ended Embodied Agent with Large Language Models." arXiv:2305.16291 (2023-05-25). https://arxiv.org/abs/2305.16291 — "an ever-growing skill library of executable code for storing and retrieving complex behaviors... iterative prompting mechanism that incorporates environment feedback, execution errors, and self-verification... 3.3× more unique items... 15.3× faster than prior SOTA."
[^2^]: Cai, T. et al. "Large Language Models as Tool Makers (LATM)." arXiv:2305.17126 (2023-05). https://arxiv.org/abs/2305.17126 — "tool proposing... if the tool is not executable, report the error and generate a new one; tool verification: the tool maker runs unit tests on validation samples... only correct the function calls in the unit test part and will not correct the function."
[^3^]: Qian, C. et al. "CREATOR: Tool Creation for Disentangling Abstract and Concrete Reasoning of Large Language Models." arXiv:2305.14318 (2023-05-23, EMNLP Findings 2023). https://arxiv.org/abs/2305.14318 — "disentangles abstract tool creation and concrete decision execution... creating tools with a clear hierarchy... offloading more reasoning burdens."
[^4^]: Yuan, L. et al. "CRAFT: Customizing LLMs by Creating and Retrieving from Specialized Toolsets." arXiv:2309.17428 (2023-09-29, ICLR 2024). https://arxiv.org/abs/2309.17428 — "Following a validation step ensuring the correctness, these solutions are abstracted into code snippets to enhance reusability, and deduplicated for higher quality."
[^5^]: Zheng, B. et al. "SkillWeaver: Web Agents can Self-Improve by Discovering and Honing Skills." arXiv:2504.07079 (2025-04-09). https://arxiv.org/abs/2504.07079 — "autonomously discovers skills, executes them for practice, and distills practice experiences into robust APIs... relative success rate improvements of 31.8% and 39.8%... transferable skills, yielding improvements of up to 54.3%."
[^6^]: Zhang, B., Lazuka, K., Murag, M. "Equipping Agents for the Real World with Agent Skills." Anthropic Engineering Blog (2025-10-16, updated 2025-12-18). https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills — "a skill is a directory that contains a SKILL.md file... Level 1 Metadata (always in context)... the amount of context that can be bundled into a skill is effectively unbounded."
[^7^]: Provenzano, N. et al. "EvoSkill: Automated Skill Discovery for Multi-Agent Systems." arXiv:2603.02766 (2026-02-20). https://arxiv.org/html/2603.02766v1 — "A Pareto frontier of agent programs governs selection, retaining only skills that improve held-out validation performance while the underlying model remains frozen... OfficeQA +7.3% (60.6%→67.9%); SealQA +12.1%; zero-shot transfer to BrowseComp +5.3%... 'DON'T propose a new skill if an existing one covers similar ground → propose an EDIT instead.'"
[^8^]: Jiang, Y. et al. "SoK: Agentic Skills — Beyond Tool Use in LLM Agents." arXiv:2602.20867 (2026-02-21). https://arxiv.org/html/2602.20867v1 — "S=(C,π,T,R)... The key advantage of code skills is determinism... 'revising, replacing, or retiring skills as environments and requirements evolve'... 'when instructions conflict with code, the agent must decide which to follow, creating potential for inconsistent behavior.'"
[^9^]: Xu, R., Yan, Y. "Agent Skills for Large Language Models: Architecture, Acquisition, Security, and the Path Forward." arXiv:2602.12430 (2026-02-17). https://arxiv.org/abs/2602.12430 — "skill selection at scale... If the selection mechanism is inaccurate, the agent may load irrelevant instructions, leading to 'distraction'... testing how multiple skills interact and whether they conflict with each other remains an open research question."
[^10^]: "How Many Tools Should an LLM Agent See? A Chance-Corrected Answer." arXiv:2605.24660 (2026-05-23). https://arxiv.org/html/2605.24660v1 — "On BFCL (370 tools), the learned policy nearly matches the coverage of showing 50 tools (90.3% vs 90.8%) while presenting only 7 on average."
[^11^]: TechGig (2026-07-07) 转述 RAG-MCP (2025-05). https://techgig.com/news/ai/ai-agent-tool-selection-six-techniques-to-boost-accuracy-efficiency/132230296 — "agent accuracy can measurably degrade once tool counts exceed 10 to 15... retrieval-based tool selection significantly improved accuracy from 13.62% to 43.13% while reducing prompt tokens by over 50%."（二手来源，置信中等）
[^12^]: Li, X. et al. "SkillsBench: Benchmarking How Well Agent Skills Work Across Diverse Tasks." arXiv:2602.12670 (2026-02). https://arxiv.org/pdf/2602.12670v1 — "Curated Skills raise average pass rate by 16.2 percentage points... Self-generated Skills provide no benefit on average... Focused Skills with 2-3 modules outperform comprehensive documentation, and smaller models with Skills can match larger models without them."
[^13^]: Zhang, X. et al. "Library Drift: Diagnosing and Fixing a Silent Failure Mode in Self-Evolving LLM Skill Libraries." arXiv:2605.19576 (2026-05-19, ICML 2026 Workshop). https://arxiv.org/abs/2605.19576 — "unbounded skill accumulation without outcome-driven lifecycle management causes retrieval degradation, false-positive injections, and performance stagnation... (outcome-driven retirement + bounded active-cap + meta-skill authoring prior) lifts held-out pass@1 from a 0.258 baseline to a late-window mean of 0.584... 'The bottleneck in self-evolving skill libraries is not the author—it is the librarian.'"
[^14^]: Kaliyev, A.T. "EvolveTool-Bench: Evaluating the Quality of LLM-Generated Tool Libraries as Software Artifacts." arXiv:2604.00392 (2026-04-01). https://arxiv.org/html/2604.00392v1 — "Code evolution outperforms strategy evolution. ARISE (ETS=0.603) outperforms EvoSkill (ETS=0.520)... Untested code is worse than no code. One-Shot library health (38.3%) is below no-evolution (41.4%)... 70.4% reuse and 51.7% health."
[^15^]: Yang, Y. et al. "AutoSkill: Experience-Driven Lifelong Learning via Skill Self-Evolution." arXiv:2603.01145 (2026-03-01). https://arxiv.org/abs/2603.01145 — "dual-loop architecture runs task execution and skill evolution in parallel... extracts new skills from interactions and decides whether to add, merge, or discard them."（dual-loop 描述转引自实现文档 https://github.com/d-wwei/skill-se-kit-python）
[^16^]: Wang, X. et al. "Executable Code Actions Elicit Better LLM Agents (CodeAct)." arXiv:2402.01030 (2024-02-01, ICML 2024). https://arxiv.org/abs/2402.01030 — "CodeAct achieves up to a 20% absolute improvement over baselines on the success rate... while requiring up to 30% fewer actions"（GPT-4: 74.4% vs JSON/Text 53.7%，见 html 版 §2.3）。
[^17^]: Muennighoff, N. et al. "s1: Simple test-time scaling." arXiv:2501.19393 (2025-01). https://arxiv.org/pdf/2501.19393 — "after training the model hardly follows the token instruction... it does sometimes generate more tokens when given a higher limit but often overshoots the limit... To prevent exceeding the limit, we test budget forcing... This leads to perfectly control."
[^18^]: Romera-Paredes, B. et al. "Mathematical discoveries from program search with large language models (FunSearch)." Nature (2023-12). https://www.nature.com/articles/s41586-023-06924-6；机制细节转引 https://github-wiki-see.page/m/Paper-Reading-Study/2025/wiki/ — "a user-provided 'specification': an evaluate function and an initial program 'skeleton'... an 'island-based' evolutionary algorithm... 'best-shot prompting' (feeding k=2 good examples, v0 and v1, back to the LLM)."
[^19^]: Liu, F. et al. "Evolution of Heuristics: Towards Efficient Automatic Algorithm Design Using Large Language Model (EoH)." arXiv:2401.02051 (2024-01-04, ICML 2024). https://arxiv.org/abs/2401.02051 — "co-evolve thoughts and codes... outperforms commonly used handcrafted heuristics and other recent AHD methods including FunSearch"；查询量对比转引 https://arxiv.org/html/2503.03350v1 — "around one million queries in FunSearch vs. 2000 queries EoH for oBPP."
[^20^]: Ye, H. et al. "ReEvo: Large Language Models as Hyper-Heuristics with Reflective Evolution." arXiv:2402.01145 (2024-02-02, NeurIPS 2024). https://arxiv.org/abs/2402.01145 — "couples evolutionary search... with humanoid reflections... providing 'verbal gradient' within search spaces... across five heterogeneous algorithmic types, six different COPs, and both white-box and black-box views."
[^21^]: van Stein, N., Bäck, T. "LLaMEA: A Large Language Model Evolutionary Algorithm for Automatically Generating Metaheuristics." arXiv:2405.20132 (2024-05-30, IEEE TEVC). https://arxiv.org/html/2405.20132v3 — "setting yt+1 explicitly to zero (worst possible quality) if runtime errors occurred... including a small example code helps a lot in generating code without syntax and runtime errors. However, the example code could also bias the optimization search towards similar algorithms."
[^22^]: Sun, W. et al. "CO-Bench: Benchmarking Language Model Agents in Algorithm Search for Combinatorial Optimization." arXiv:2504.04310 (2025-04-06, AAAI 2026). https://arxiv.org/abs/2504.04310 — "on 25 problems, AI-generated algorithms outperformed expert baselines within a 30-minute research budget, and on 3 problems, they surpassed the best-known solutions. However... limited algorithmic novelty and insufficient handling of feasibility constraints."
[^23^]: "An LLM-Driven Multi-Agent Evolution Framework for Solver Code Generation in Job Shop Scheduling." Mathematics 14(11):2010 (2026-06). https://www.mdpi.com/2227-7390/14/11/2010 — "Agent 1 constructs a reliable and behaviorally diverse initial code pool under a structured constraint template and a shared solver skeleton, Agent 2 iteratively evolves the pool through program-space crossover and best-so-far mutation, and Agent 3 generates structured revision guidance through code-level reflection with trajectory-aware reflective memory."
[^24^]: "Automatic programming via large language models with population self-evolution for dynamic fuzzy job shop scheduling problem (SeEvo)." arXiv:2410.22657 (2024-10). https://arxiv.org/html/2410.22657v2 — "individuals are code fragments rather than fixed-length representations... The only requirement is that the LLM-generated code must adhere to specific function names, input parameters, and output parameters."
[^25^]: Liu, F. et al. "EoH-S: Evolution of Heuristic Set using LLMs for Automated Heuristic Design." arXiv:2508.03082 (2025-08-05, AAAI 2026). https://arxiv.org/html/2508.03082v1 — "design a small set of complementary heuristics and let each instance use its strongest member."（描述转引 https://github.com/CIAM-Group/awesome-llm4aad）
[^26^]: "Adaptation of Agentic AI: A Survey of Post-Training, Memory, and Skills." arXiv:2512.16301 (2025-12). https://arxiv.org/html/2512.16301v3 — "a frozen GPT-4 agent generates executable code for each new task, and successful programs are stored in a growing skill library indexed by natural-language descriptions. When the agent encounters a related task, it retrieves and composes previously verified skills instead of reasoning from scratch."
[^27^]: "CodeMem: Architecting Reproducible Agents via Dynamic MCP and Procedural Memory." arXiv:2512.15813 (2025-12-17). https://arxiv.org/html/2512.15813 — "Program of Thoughts (PoT), showing that offloading logic to a Python interpreter improves numerical reasoning accuracy by over 10% compared to Chain of Thought (CoT)... code-driven agents achieved a 20% higher success rate... 30% fewer turns."

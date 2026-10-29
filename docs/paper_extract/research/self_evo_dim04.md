# 维度 04：技能库（Skill Library）自进化开源方案深度调研

> 调研日期：2026-08-20。所有 stars 为当日从 GitHub 仓库页面抓取的实时数据（GitHub API 因限流不可用，改用页面 `aria-label` 抓取）。
> 调研方法：20 次独立中英文搜索（Google 类检索 + GitHub/arXiv/官方文档直采），覆盖 GitHub 仓库、arXiv 论文、官方 README/文档、第三方评测。

---

## 0. 总览对比表（stars 查询日期均为 2026-08-20）

| 方案 | 仓库 | Stars | License | 语言 | 一句话定位 | 即插即用度 |
|---|---|---|---|---|---|---|
| Voyager | MineDojo/Voyager | 7,152 | MIT | Python+JS | 技能库范式鼻祖（Minecraft） | 低（绑定 Minecraft/Mineflayer） |
| GenericAgent | lsdefine/GenericAgent | 13,810 | MIT | Python | 3.3K 行种子代码自进化长出技能树 | 高（pip install + API key） |
| Alita（官方） | CharlesQ9/Alita | 879 | 未声明 | —（仅 README，未放代码） | 按需自造 MCP 的 generalist agent | 不可用（官方未开源代码） |
| OpenAlita（复现） | ryantzr1/OpenAlita | 100 | MIT | Python | Alita 社区复现 | 中 |
| AutoSkill | ECNU-ICALK/AutoSkill | 559 | 未声明（无 LICENSE 文件） | Python | 对话经验沉淀为 SKILL.md 并版本化进化 | 高（SDK/Web UI/OpenAI 兼容代理） |
| SkillClaw | AMAP-ML/SkillClaw | 2,462 | MIT | Python | 跨会话/设备/用户的集体技能进化 | 高（本地代理即接入） |
| Hermes Agent | NousResearch/hermes-agent | 233,264 | MIT | Python | 自我改进 agent，skill_manage 闭环 | 高 |
| hermes-agent-self-evolution | NousResearch/hermes-agent-self-evolution | 5,090 | MIT | Python | DSPy+GEPA 离线进化 SKILL.md | 高（独立工具，输出 PR） |
| CoEvoSkills (EvoSkills) | Zhang-Henry/CoEvoSkills | 60 | Apache-2.0 | Python | 生成器-验证器共进化多文件技能包 | 中（benchmark 向框架） |
| SkillFoundry | ma-compbio-lab/SkillFoundry | 36 | Apache-2.0 | Python | 从科研资源挖掘并验证技能的闭环 | 中（面向科学领域） |
| LATM | ctlllll/LLM-ToolMaker | 1,063 | 未声明 | Python | LLM 自造可复用 Python 工具 | 低（研究代码） |
| CREATOR | qiancheng0/CREATOR | 31 | 未声明 | Python | 解耦"造工具"与"用工具" | 低（研究代码） |
| CRAFT | lifan-yuan/CRAFT | 62 | 未声明 | Python | 离线造工具集 + 推理时检索 | 低（研究代码） |
| XSKILL | XSkill-Agent/XSkill | 253 | MIT | Python | 技能库+经验库双流协同进化 | 中 |
| Skill Self-Play | Qwen-Applications/skill-self-play | 127 | Apache-2.0 | Python | 自博弈训练中的技能库协同进化 | 低（训练框架） |
| SciAgent-Skills（静态库参照） | jaechang-hits/SciAgent-Skills | 339 | 未查到 | Markdown/Python | 199 个生物信息 SKILL.md 领域库 | 高（静态库，非自进化） |

---

## 1. Voyager（NVIDIA / MineDojo）——技能库范式鼻祖

- **仓库**：https://github.com/MineDojo/Voyager ；论文 arXiv:2305.15350
- **Stars**：7,152（2026-08-20，页面抓取）；**License**：MIT（页面显示 "MIT license"）[^2^]
- **语言**：Python（agent 逻辑）+ JavaScript（技能代码，基于 Mineflayer API）
- **核心机制**（生成/验证/检索/组合）[^1^][^3^][^4^]：
  - **生成**：Automatic Curriculum 提出下一任务 → GPT-4 编写 JS 技能代码（"Code as Action"）；
  - **验证**：三重反馈循环——环境状态、JS 解释器执行错误、GPT-4 Critic 自验证（self-verification）。消融实验显示去掉自验证后新物品发现率下降 73%[^3^]；
  - **存储/检索**：技能库存为 `skill/code/*.js` + `skill/description/*.txt` + `skills.json` + `vectordb`（描述文本做 embedding，按任务描述向量检索 top-k 技能拼入 prompt）[^4^]；
  - **组合**：技能即带描述的函数，新技能可调用旧技能，自然形成组合层次；
  - **迁移**：技能库目录可整体拷贝复用（`skill_library_dir` 参数加载，社区已共享 trial1/2/3 及多个 checkpoint 仓库）[^4^]；论文还证明 Voyager 技能库可插到 AutoGPT 上提升性能（即插即用证据）[^5^]。
- **即插即用程度**：低。强绑定 Minecraft Java 版 + Fabric mods + Mineflayer + Node.js ≥16.13 + Python ≥3.9[^3^]；2024-04 后基本停更[^2^]。
- **二次开发入口**：`voyager/agents/`（action/curriculum/critic/skill 四个 agent 模块）、`voyager/control_primitives/`；技能库格式简单（js + txt + json），易被移植。
- **领域定制**：换环境=重写 action 原语与验证反馈源；"Code as Action" 范式本身可迁移到任何有结构化 API 的沙盒[^1^]。
- **后续复现/泛化**：官方仓库支持加载社区技能库 checkpoint（daswer123/Voyager_checkpoint 等）[^4^]；范式被 GenericAgent / Alita / AutoSkill 等 2025-2026 项目泛化到通用计算机操作与 SKILL.md 生态（见下文）。局限：未找到官方"泛化版 Voyager"。
- **局限性**：GPT-4 调用成本高；代码幻觉（如合成不存在的物品）需靠环境反馈纠正[^1^]；强绑定单一游戏环境；技能库无去重/淘汰机制，长期运行有错误技能累积风险。

## 2. GenericAgent（lsdefine）——3.3K 行种子自进化技能树 ★与本任务最贴合

- **仓库**：https://github.com/lsdefine/GenericAgent ；官网 https://gaagent.ai ；技术报告 JinyiHan99/GA-Technical-Report
- **Stars**：13,810（2026-08-20 页面抓取；第三方 2026-05-28 记录为 12,229，增长一致）[^6^][^7^]；**License**：MIT[^6^]；**语言**：Python
- **核心机制**[^6^]：
  - **骨架**：9 个原子工具（`code_run`、`file_read/write/patch`、`web_scan`、`web_execute_js`、`ask_user`、两个记忆工具）+ ~100 行 `agent_loop.py`；
  - **生成/沉淀**：每解决一个新任务，执行路径自动"结晶"为 Skill 写入分层记忆（L0 Meta Rules → L1 Insight Index → L2 Global Facts → **L3 Task Skills/SOPs** → L4 Session Archive）；
  - **验证**：执行期自我调试（install deps → write scripts → debug → verify）；
  - **检索**：L1 索引层做路由召回，上下文 <30K（对比同类 200K–1M），号称 token 消耗低 6 倍[^6^][^7^]；
  - **组合/扩展**：`code_run` 可运行时动态装包、写脚本、封装成永久工具；2026-03 发布百万级 Skill Library（中文社区）、Sophub Skill Hub[^8^]。
  - **自举实证**：整个仓库（388+ commits）由 agent 自己提交完成[^6^][^7^]。
- **即插即用程度**：高。`git clone && uv pip install -e ".[ui]"` + 填 API key；也有 Windows/Linux 一键脚本；专门提供"给 LLM Agent 读"的 installation.md（`curl` 抓取即可让 Cursor/Claude 自动安装）[^6^]。
- **二次开发入口**：核心仅 ~3K 行，`agent_loop.py` ~100 行；无 LangChain/Playwright 重依赖；社区已有 ga-manager、galley 等二次开发 GUI。
- **领域定制（编码/运维）**：出厂仅"几个核心文件 + 少量初始 Skills"，技能几乎全部从使用中生长——天然领域自适应：在编码/运维场景反复使用即长出该领域技能树；也可预置/导入 starter skills 与 Sophub 技能。
- **嵌入用户现有工程的方式**：可作为独立本地 agent 与 Cursor 并存（它本身支持 Claude/Gemini/Kimi/MiniMax 等模型），或参考其"技能结晶 + 分层记忆"机制在 superpower skill 体系上复刻（3K 行量级，二次开发成本低）。
- **局限性**：技能质量取决于 backbone 模型自我总结能力，无强制 eval gate（错误路径可能被固化）；评估以自建 benchmark 为主[^6^]；对个人使用场景优化，多用户/团队共享技能库不是原生设计（需配 SkillClaw 类方案）。

## 3. Alita——minimal predefinition + maximal self-evolution

- **官方仓库**：https://github.com/CharlesQ9/Alita （**879 stars，但截至 2026-08-20 仅有 README + Figures，未释放代码，无 LICENSE**）；论文 arXiv:2505.20286[^9^]
- **复现**：ianlucas1/Alita（2025-06，stars 未查到/抓取失败）[^10^]；ryantzr1/OpenAlita（**100 stars，MIT**，2026-08-20）[^11^]
- **核心机制**[^9^]：
  - **Minimal Predefinition**：只内置一个核心能力（web agent）+ 少量通用模块（Manager Agent + CodeReAct loop）；
  - **生成**：收到任务 → MCP Brainstorming（头脑风暴需要什么工具）→ Web Agent 搜开源库/资源 → 自动生成脚本 + 配置虚拟环境 → 执行，出错则反馈自纠；
  - **沉淀/复用**：有用工具封装为 **MCP server** 存入 "MCP Box"，后续任务直接复用，形成自增强循环（"generate increasingly powerful MCPs"）；
  - **验证**：执行反馈自纠 + MCP Box 使 pass@1 逼近 pass@N（GAIA 75.15% pass@1 / 87.27% pass@3）[^9^][^10^]。
- **即插即用程度**：官方代码未开源——**不可直接使用**；OpenAlita 复现可用（集成 browser-use，Python）。
- **二次开发/领域定制**：思想贡献大于代码贡献：MCP 是标准协议，生成的 MCP 可"蒸馏"给更弱的 agent（agent distillation），天然支持领域 MCP Box 积累[^10^]。
- **局限性（作者自述）**：自动生成的 MCP 抽象度过低会过拟合 benchmark（GAIA），过高则 MCP Overload（重叠过载）[^10^]；工具/环境生成质量依赖搜索到的开源资源质量。

## 4. AutoSkill（ECNU-ICALK × 上海AI Lab）——经验驱动的 SKILL.md 自进化

- **仓库**：https://github.com/ECNU-ICALK/AutoSkill （559 stars，2026-08-20）；论文 arXiv:2603.01145[^12^][^13^]
- **License**：**未声明**（仓库根目录无 LICENSE 文件，2026-08-20 核查）——二次开发需注意；**语言**：Python
- **核心机制**[^13^][^14^]：
  - **技能表示**：标准化 `SKILL.md`，形式化为元组 s=(名称, 描述, 可执行指令 prompt, 触发集, 标签集, 示例集, 版本号)，人可读/可编辑/可合并/可版本化；
  - **生成**：双通路——在线服务路径（query 改写 → 稠密向量 + BM25 混合检索 → 技能注入 prompt）+ 后台学习路径（仅从**用户输入**提取可复用行为模式，避免把模型输出当证据）；
  - **维护**：管理裁判对每个候选技能做 **add / merge / discard** 三选一；merge 触发版本递增（v0.1.0 → v0.1.1），保证"精炼而非重复堆积"；一次性通用请求不产技能（防噪）[^13^]；
  - **检索**：embedding + BM25 混合，超阈值才注入；
  - **衍生组件**：AutoSkill4Doc（从文档/论文抽技能）、AutoSkill4OpenClaw（从 agent 轨迹抽技能）、**SkillEvo**（replay→evaluate→mutate→promote 的迭代进化）、`skills/autoskill` 本地技能管理器（discard/improve/merge/create 决策）[^12^]。
- **即插即用程度**：高。三种接口：Python SDK、Web UI、**OpenAI 兼容反向代理**（前台做技能检索注入、后台异步提取进化）——可直接架在现有 LLM 调用链上，model-agnostic[^14^]。
- **二次开发入口**：`autoskill/`（核心 SDK/runtime）、`SkillEvo/`、`examples/`、`tests/`；技能就是文件系统里的 SKILL.md，易与 Cursor/superpower 的 skills 目录互通。
- **领域定制**：技能按用户 SkillBank 隔离，天然沉淀个人/领域偏好（写作风格、SOP、工具流程）；离线导入历史会话/轨迹即可冷启动领域技能。
- **局限性**：主要面向"偏好/流程"类软技能，不生成可执行代码技能（相对 Voyager/CREATOR）；无 LICENSE；技能注入增加 prompt 长度；提取质量依赖裁判模型。

## 5. 工具制造三杰（LATM / CREATOR / CRAFT，2023，研究代码）

### 5.1 LATM（LLMs as Tool Makers）
- **仓库**：https://github.com/ctlllll/LLM-ToolMaker （1,063 stars，2026-08-20）；arXiv:2305.17126；ICLR 2024[^15^][^16^]
- **License**：**未声明**；**语言**：Python
- **机制**：两阶段闭环——强模型（GPT-4）做 tool maker 造 Python 工具函数，弱模型（GPT-3.5）做 tool user 调用；工具缓存形成功能性缓存（functional cache），一次制造成本分摊到多次使用[^15^][^16^]。
- **即插即用**：低（Big-Bench 实验代码，OpenAI 老 API）；**领域定制**：换任务即换 maker prompt。**局限**：无工具验证/去重/版本管理，是"最小范式证明"而非框架。

### 5.2 CREATOR
- **仓库**：https://github.com/qiancheng0/CREATOR （31 stars，2026-08-20）；arXiv:2305.14318[^17^][^18^]
- **License**：**未声明**；**语言**：Python
- **机制**：四阶段——抽象工具创建（ToolSpec：签名+docstring+伪码）→ 代码实现（ToolCode）→ 决策程序生成 → **Rectification 纠错**（沙箱执行报错后重 prompting 修复）；强调"造工具"与"用工具"解耦、可复用性；MATH/TabMWP 上比 CoT/PoT/API 工具最高 +13 点[^17^][^18^]。
- **即插即用**：低（研究复现脚本，需 OpenAI + WolframAlpha key）；**局限**：工具库无持久化注册表设计，重单任务正确性、轻长期库治理。

### 5.3 CRAFT
- **仓库**：https://github.com/lifan-yuan/CRAFT （62 stars，2026-08-20）；arXiv:2309.17428；ICLR 2024[^19^][^20^]
- **License**：**未声明**；**语言**：Python
- **机制**：**离线造工具集 + 推理时检索**——相似度迭代采样任务保多样性 → GPT-4 生成代码解 → 抽象为可复用工具 → 在原题上验证正确性（错则丢弃）→ 去重；推理时 multi-view matching（问题×函数名×docstring）检索工具拼入 prompt；训练-free、即插即用适配未见领域[^19^][^20^]。
- **即插即用**：低-中（vqa / tab_and_math 两个实验目录，构造与推理脚本分离，流程清晰可迁移）；**领域定制**：换领域=换训练题集重新造工具集，无需微调——是三杰里最贴近"领域专用技能库"的。
- **局限**：依赖 GPT-4 批量造库成本；检索为启发式匹配，工具集大后检索精度未充分验证。

## 6. 2025–2026 新一代技能进化项目

### 6.1 SkillClaw（高德 AMAP-ML）——集体技能进化 ★即插即用
- **仓库**：https://github.com/AMAP-ML/SkillClaw （2,462 stars，2026-08-20；2026-05-20 报道时 1.3k）；论文 arXiv:2604.08377[^21^][^22^]
- **License**：MIT；**语言**：Python
- **机制**：本地 **Client Proxy**（拦截 `/v1/chat/completions`、`/v1/messages`，记录任务输入/工具调用/反馈/结果，维护本地技能库）+ 可选 **Evolve Server**（从共享存储读多会话数据，做技能去重、合并、低质技能改写）；进化引擎两种：`workflow`（Summarize→Aggregate→Execute 三阶段 LLM 流水线）或 `agent`（基于 OpenClaw 工作区直接编辑技能）；统一 SKILL.md 格式；共享存储支持本地目录/OSS/S3[^22^][^23^]。
- **即插即用**：高——代理模式对宿主透明，兼容 Hermes、Codex、Claude Code、OpenClaw、QwenPaw 及任意 OpenAI 兼容 API[^21^][^23^]。
- **领域定制**：指向团队共享存储即形成领域技能中台；多设备/多成员经验汇总去重后分发。
- **局限**：技能治理质量依赖 Evolve Server 的裁判 prompt；多用户共享带来隐私/权限问题（需自行设计审计）[^23^]。

### 6.2 Hermes Agent（Nous Research）+ hermes-agent-self-evolution
- **仓库**：https://github.com/NousResearch/hermes-agent （233,264 stars，2026-08-20，2026 年现象级项目；2026-04 报道为 60,977→90k+，增长轨迹一致）[^24^][^25^]；MIT；Python
- **机制**：执行后反思阶段提取可复用推理模式，以 `SKILL.md` 持久化（YAML frontmatter + 正文）；agent 通过 `skill_manage` 工具自创建/打补丁/删除技能（`create/patch/edit/delete/write_file`）；`skills.write_approval` 门控可把技能写入改为"暂存→人工 approve"（防错误技能入库）；`/learn` 把大部头资料蒸馏为知识库技能（SKILL.md + references/ 按需加载）；Skills Hub 支持从 skills.sh、ClawHub、GitHub taps 安装[^26^][^27^]。
- **配套进化工具**：**hermes-agent-self-evolution**（5,090 stars，MIT）——独立仓库，用 **DSPy + GEPA**（ICLR 2026 Oral）离线进化 SKILL.md/工具描述/系统提示：读执行轨迹→反思失败→定向变异→约束门（测试全过、≤15KB、缓存兼容、语义保持）→**全部走 PR 人工合并**，单次优化约 $2–10[^28^]。
- **即插即用**：高（pip 安装 + 快照/恢复脚本保证技能跨重建存活[^26^]）；**领域定制**：技能按目录分类 + 用户建模（USER.md）+ 自进化工具可对任意指定 skill 跑 GEPA。
- **局限**：默认技能自由写入，小模型可能"误判学到的东西"（官方因此提供审批门与危险模式扫描器）[^27^]；GEPA 进化需要 eval 数据集（合成/会话挖掘/金标），冷启动成本。

### 6.3 CoEvoSkills / EvoSkills（COLM 2026）
- **仓库**：https://github.com/Zhang-Henry/CoEvoSkills （60 stars，2026-08-20）；论文 arXiv:2604.01687[^29^][^30^]
- **License**：Apache-2.0；**语言**：Python（uv 管理）
- **机制**：**生成器-验证器共进化**——Skill Generator 迭代生成/修复多文件技能包（SKILL.md+脚本+引用）；Surrogate Verifier 在**信息隔离**的独立会话中合成确定性测试断言并给出结构化失败诊断（规避自验证确认偏误）；通过代理测试后才调 ground-truth oracle，且 oracle 只回不透明 pass/fail；oracle 失败时验证器"测试升级"（test escalation），技能与测试互相抬升[^29^][^30^]。
- **关键证据**：SkillsBench（87 任务/11+领域）pass rate 71.1%，比人工精选技能 +17.6pp、比无技能 +40.5pp；一次性自生技能（32.0%）与无技能基线（30.6%）无统计差异——**证明"无验证环的自生技能几乎无效"**；进化出的技能跨 6 个模型迁移 +35~44pp[^30^][^31^]。
- **即插即用**：中——面向 SkillsBench 的研究框架，但提供自定义任务接入（task.toml + background doc）与 agent adapter 注册（LiteLLM 模型字符串 / Harbor agent 类），可直接对 Claude Code/Codex 进化技能[^32^]。
- **局限**：需要任务有确定性 oracle 或能合成代理测试；每任务最多 5 轮进化，token 成本高。

### 6.4 SkillFoundry（CMU Ma Lab）——从外部资源挖矿式建库
- **仓库**：https://github.com/ma-compbio-lab/SkillFoundry （36 stars，2026-08-20）；论文 arXiv:2604.03964[^33^][^34^]
- **License**：Apache-2.0；**语言**：Python 3.10+
- **机制**：领域知识树作为搜索先验与进化结构——建树（域/子域/技能叶）→ 资源挖掘（repos/APIs/论文/notebooks）→ 技能编译（操作契约+依赖+测试）→ **多级验证**（执行测试/SLURM 系统测试/合成数据测试，失败进修复环）→ 树扩张 → 失败/冗余技能修订、合并、剪枝，闭环循环；267+ 技能覆盖 28 域，71.1% 相对现有库（SkillHub/SkillSMP）为新；MoSciBench 6 数据集中 5 个提升[^33^][^34^]。
- **即插即用**：中（`pip install -e .` + CLI `cycle/campaign/design-skill`）；**领域定制**：天然领域化——给 `--focus-term genomics` 即定向挖某领域，是"领域专用技能库自动化建设"的最佳参考。
- **局限（作者自述）**：覆盖面仍有限；多数技能仅经内部测试验证、缺广泛下游验证；高可靠场景需谨慎[^34^]。

### 6.5 XSKILL（HKUST×浙大×华科）
- **仓库**：https://github.com/XSkill-Agent/XSkill （253 stars，2026-08-20）；论文 arXiv:2603.12056[^35^]
- **License**：MIT；**语言**：Python
- **机制**：**双流知识系统**——Skill Library（结构化程序，像驾驶手册）+ Experience Bank（情境化行动提示，像驾驶直觉），技能与经验协同进化；cross-rollout critique 比较多次执行提取因果教训[^35^]。
- **即插即用**：中（多模态 agent 研究方向）；**领域定制**：技能库与经验库分离，可按域替换。

### 6.6 Skill Self-Play（阿里 Qwen 应用团队）
- **仓库**：https://github.com/Qwen-Applications/skill-self-play （127 stars，2026-08-20，2026-07 发布）[^36^]
- **License**：Apache-2.0；**语言**：Python
- **机制**：训练侧自博弈——技能路由的任务生成 + 有效性校验 + 前沿课程 + 反馈驱动的技能精炼/剪枝/归纳；技能只在训练时使用，推理时 solver 为纯 prompt[^36^]。面向"训练 agent 模型"而非"即插即用技能库"，列为延伸参考。

### 6.7 SkillNet（浙大×复旦×阿里等 19 家机构）
- 论文 2026-04-10 发布；三层架构（技能分类体系 + 技能关系图 + 技能包库）+ 五维评估（含安全性/完整性）；ALFWorld/WebShop/ScienceWorld 上平均 reward +40%、执行步数 -30%；与 OpenClaw、华为九问 Claw 集成[^37^]。**GitHub 仓库地址未查到**（疑似尚未完全开源或以平台形式发布），列为观察对象。

### 6.8 其他相关（一句话）
- **jaechang-hits/SciAgent-Skills**（339 stars）：199 个生信领域 SKILL.md 静态库，Claude Code 装上 BixBench 65%→92%——"领域静态技能库"价值与格式的参照[^38^]。
- **SKILL0**（arXiv:2604.02268）：把技能内化进模型参数的 in-context RL，指出检索式技能的三大痛点（检索噪声/语义污染、token 爆炸、"照本宣科"非内化）[^39^]。
- **MetaClaw**（arXiv:2603.17187）、**HyperAgents**（facebookresearch/HyperAgents）、**CORAL**（arXiv:2604.01658）：更激进的策略/代码级自进化，风险更高[^40^]。

---

## 7. 局限性横向总结（技能库自进化的共性风险）

1. **一次性自生技能≈无效**：CoEvoSkills 在 SkillsBench 上证明单 pass 自生技能（32.0%）与无技能基线（30.6%）无统计差异；必须有验证/进化闭环[^30^][^31^]。
2. **技能污染与错误技能累积**：无 eval gate 的自动入库会把错误路径固化（SkillClaw 针对的"相似技能反复生成、旧新技能打架、低质半成品堆积"[^21^]；GenericAgent 依赖 backbone 自我总结，无强制验证[^6^]）。对策：Hermes 的 `write_approval` 人工门[^27^]、SkillFoundry 多级验证+剪枝[^33^]、AutoSkill 的 add/merge/discard 裁判[^13^]。
3. **检索失败/语义污染**：检索器易召回无关技能污染决策上下文，跨领域时更严重；技能变大后 token 开销爆炸[^39^]。对策：分层索引（GenericAgent L1[^6^]）、混合检索+阈值（AutoSkill[^14^]）、multi-view matching（CRAFT[^19^]）。
4. **过拟合 benchmark / 过拟合生成环境**：Alita 作者自述 MCP 抽象过低则过拟合 GAIA、过高则 MCP Overload[^10^]；SkillFoundry 承认内部验证≠下游效用[^34^]。
5. **人机认知错位**：人工编写技能在某些领域反而降低 agent 表现（SkillsBench 自然科学域），自进化技能更贴合模型实际推理方式[^31^]。
6. **自验证确认偏误**：生成器自己验证自己不可靠——CoEvoSkills 用信息隔离的独立验证器会话解决[^29^]。
7. **供应链安全**：技能含脚本/网络访问即软件供应链一环；社区建议候选技能须过静态检查+沙箱+回归评测+人工审核后才进版本化 registry，生产只加载已发布版本[^41^]。
8. **成本**：Voyager 式循环 GPT-4 调用成本高[^1^]；CoEvoSkills 每任务多轮进化成本高[^30^]；GEPA 优化每次 $2–10[^28^]。

## 8. 针对"Cursor + GPT + superpower skill"场景的落地建议（推断，非事实）

- **首选直接可用**：**SkillClaw**（MIT，代理模式对现有 LLM 调用链透明，SKILL.md 格式与 Cursor/superpower 技能生态一致）+ **AutoSkill**（OpenAI 兼容代理/SDK，但注意无 LICENSE）。
- **机制最简可复刻**：**GenericAgent**（3K 行，技能结晶+分层记忆，MIT，二开成本极低，且自带"给 LLM 读的安装文档"，与 Cursor 工作流天然契合）。
- **离线技能质量提升**：**hermes-agent-self-evolution** 的 DSPy+GEPA 流程（对任意 SKILL.md 跑进化、PR 人审）可独立于 Hermes 思路复用到 superpower 技能库。
- **编码/运维领域限定**：用 SkillFoundry 的"领域知识树+定向挖掘+多级验证"思路建领域库；或用 CRAFT 的"离线造库+推理检索"模式对运维 runbook 造工具集。
- **研究前沿参考**：CoEvoSkills（生成-验证共进化）、Alita（按需自造 MCP）。

---

## 引用

[^1^]: Skywork, "Voyager AI Skill Library: The Future of Embodied Agents", 2026-06-23, https://skywork.ai/slide/en/voyager-ai-embodied-agents-2069436686966333440 —— "Voyager relies heavily on GPT-4 API calls… hallucinations mitigated via Self-Verification… 'Code as Action' paradigm is transferable to any sandbox with a structured API"；官方代码 github.com/MineDojo/Voyager，论文 arxiv.org/abs/2305.15350。
[^2^]: Enterprise DNA Open-Source Directory, "Voyager", 2026-06-01, https://enterprisedna.co/directories/open-source/voyager/ —— "6,944 stars on GitHub. Last updated 2024-04-03. Licensed MIT."（stars 已于 2026-08-20 由本调研重新抓取为 7,152）。
[^3^]: Skywork, "Voyager AI Minecraft Skill Library", 2026-06-23, https://skywork.ai/slide/en/voyager-ai-minecraft-skills-2069435054276669440 —— 三重反馈（Environmental/Execution/Verification）；去掉自验证 "reducing unique item discovery by 73%"；Node ≥16.13、Python ≥3.9、Fabric mods。
[^4^]: MineDojo/Voyager skill_library/README.md, https://github.com/MineDojo/Voyager/blob/main/skill_library/README.md —— 技能库目录结构 `skill/code/*.js`、`skill/description/*.txt`、`skills.json`、`vectordb`；社区 checkpoint：daswer123/Voyager_checkpoint 等；`skill_library_dir` 加载复用。（访问日期 2026-08-20）
[^5^]: CSDN 博客（HERODING23） Voyager 论文精读, 2023-11-15, https://blog.csdn.net/HERODING23/article/details/134426646 —— "终身学习的技能库不仅增强了 VOYAGER 的性能，还增强了 AutoGPT 的性能，说明技能库可以作为一种即插即用的工具"；tech tree wooden level 快 15.3 倍，唯一解锁 diamond level。
[^6^]: GitHub lsdefine/GenericAgent README, https://github.com/lsdefine/GenericAgent （访问 2026-08-20；stars 13,810 当日抓取）—— "~3K lines of seed code · 9 atomic tools · ~100-line Agent Loop"；"don't preload skills, evolve them"；五层记忆 L0–L4（L3 Task Skills/SOPs）；`<30K context window`；"Distributed under the MIT License"；安装 `uv pip install -e ".[ui]"` + `docs/installation.md`（For LLM Agents）。
[^7^]: AgentStaffer profile, 2026-05-28, https://agentstaffer.com/agents/github-lsdefine-genericagent —— "12,229 stars, 1,411 forks, last activity 2026-05-28"；sotaaz.com, 2026-04-19, https://sotaaz.com/post/self-evolving-agents-en —— "388 commits, none manually typed… 6x token savings"。
[^8^]: GitHub lsdefine/GenericAgent 路线图摘录（搜索结果快照, 2026-05-23）—— "2026-03-10 — Released million-scale Skill Library (Chinese)"；Sophub Skill Hub badge。
[^9^]: arXiv:2505.20286 "Alita: Generalist Agent Enabling Scalable Agentic Reasoning with Minimal Predefinition and Maximal Self-Evolution", https://arxiv.org/pdf/2505.20286 —— "dynamically generate, adapt, and reuse MCPs… new tools can be encapsulated as MCP servers for future reuse… self-reinforcing cycle"；GAIA "75.15% pass@1 and 87.27% pass@3"。
[^10^]: GitHub ianlucas1/Alita（CharlesQ9/Alita 复现与作者评论整理）, 2025-06-09, https://github.com/ianlucas1/Alita —— Comment 18/19："MCPs may only work on GAIA validation… overfit"；"abstraction too high → MCP Overload；too low → overfit the dataset"；MCP Box 可做 agent distillation，"pass@1 approach pass@N"。
[^11^]: GitHub ryantzr1/OpenAlita, 2025-06-04, https://github.com/ryantzr1/OpenAlita —— "Open Source Implementation of Alita… leverages MCP to dynamically create, adapt, and reuse capabilities"；stars 100、MIT（2026-08-20 抓取）。
[^12^]: GitHub ECNU-ICALK/AutoSkill README, https://github.com/ECNU-ICALK/AutoSkill （访问 2026-08-20；stars 559）—— News：SkillEvo 1.0（replay/evaluation/mutation/promotion）、AutoSkill4Doc、AutoSkill4OpenClaw、`skills/autoskill` 本地技能管理器（discard/improve/merge/create）；目录结构 autoskill/、SkillBank/、SkillEvo/ 等；citation 注明 arXiv 2603.01145。根目录无 LICENSE 文件（当日核查）。
[^13^]: arXiv:2603.01145v2 "AutoSkill: Experience-Driven Lifelong Learning via Skill Self-Evolution", 2026-03-05, https://arxiv.org/html/2603.01145v2 —— 技能元组 s=(n,d,p,τ,γ,ξ,v)；"add / merge / discard" 决策与版本 Bump；"generic one-off requests should typically produce no skill"。
[^14^]: alphaxiv overview 2603.01145, https://www.alphaxiv.org/overview/2603.01145 —— 混合检索 Rel=λ·dense+(1−λ)·BM25；"only user-generated content serves as evidence for skill induction"；SDK/Web UI/OpenAI 兼容反向代理三接口。
[^15^]: GitHub ctlllll/LLM-ToolMaker README, https://github.com/ctlllll/LLM-ToolMaker （stars 1,063，2026-08-20）—— "two key phases: 1) tool making… Python utility function. 2) tool using…"；GPT-4 maker + GPT-3.5 user 成本大幅降低。
[^16^]: arXiv:2305.17126 "Large Language Models as Tool Makers", https://arxiv.org/abs/2305.17126 —— "functional cache through the caching and reuse of tools"；ICLR 2024 poster https://iclr.cc/virtual/2024/poster/17729。
[^17^]: GitHub qiancheng0/CREATOR, https://github.com/qiancheng0/CREATOR （stars 31，2026-08-20）—— MATH/TabMWP/Creation Challenge 实验；`generate_CREATOR.py` 配置 prompt_creation/decision/rectification。
[^18^]: arXiv:2305.14318v3, https://arxiv.org/html/2305.14318v3 —— 四阶段 Creation/Decision/Execution/Rectification；对比表 CREATOR 唯一同时 CreateTools+UtilizeTools+ApplyCodes+Reusability；emergentmind 综述（2026-02-12, https://www.emergentmind.com/topics/creator-algorithm）："up to a 13-point accuracy improvement over CoT and API tool-use baselines"。
[^19^]: GitHub lifan-yuan/CRAFT, https://github.com/lifan-yuan/CRAFT （stars 62，2026-08-20）—— "iterative problem-sampling… abstract… evaluate… discard incorrect… deduplicate"；"multi-view matching… target problem, function name, and docstring"。
[^20^]: arXiv:2309.17428v2, https://arxiv.org/html/2309.17428v2 —— "training-free and plug-and-play approach to adapt off-the-shelf LLMs to unseen domains… without any finetuning"；ICLR 2024。
[^21^]: 智猩猩（腾讯新闻）, "1.3k Stars！阿里高德开源Agent Skills自进化框架", 2026-05-20, https://news.qq.com/rain/a/20260520A035M700 —— 项目链接 github.com/AMAP-ML/SkillClaw，论文 arxiv.org/pdf/2604.08377；"相似技能反复生成、旧技能和新技能互相打架、低质量半成品堆积如山"；支持 Hermes/Codex/Claude Code/OpenClaw/QwenPaw 及任意 OpenAI 接口。
[^22^]: 同上 —— "Client Proxy 代理模型请求…记录任务输入、工具调用、执行反馈和最终结果"；"Evolve Server…Summarize → Aggregate → Execute 三阶段 LLM 流水线；另一种是基于 OpenClaw 的 agent engine"；共享存储 OSS/S3/本地；统一 SKILL.md。stars 2,462、MIT（2026-08-20 抓取）。
[^23^]: datawhalechina/hello-agents Extra10-Agent自进化, https://github.com/datawhalechina/hello-agents/blob/main/Extra-Chapter/Extra10-Agent%E8%87%AA%E8%BF%9B%E5%8C%96.md —— "Client Proxy 拦截 /v1/chat/completions 与 /v1/messages…单独启用即可完成接入"；"跨会话、跨设备、跨用户…把隐私、权限和审计提前设计进去"。
[^24^]: dev.to, "One Open Source Project a Day (No.40): Hermes Agent", 2026-04-16, https://dev.to/wonderlab/one-open-source-project-a-day-no40-hermes-agent-nous-researchs-self-improving-ai-agent-4ale —— "90k+ Stars, 12k+ Forks… closed-loop skill learning… three-layer memory architecture"。
[^25^]: openx.im, "NousResearch Hermes Agent", https://www.openx.im/718.html —— "over 60,977 total stars and 8,141 forks… topped the trending charts on April 12, 2026, accumulating over 6,400 stars in a single day"。（2026-08-20 抓取为 233,264 stars）
[^26^]: NVIDIA Developer Blog, "Deploy Self-Evolving Agents… with a Hermes Agent and NVIDIA NemoClaw", 2026-06-02, https://developer.nvidia.com/blog/deploy-self-evolving-agents-for-faster-more-secure-research-with-a-hermes-agent-and-nvidia-nemoclaw/ —— "Hermes writes a SKILL.md to the filesystem… short YAML frontmatter (name and description)"；snapshot/tear-down/restore 保证技能跨重建存活。
[^27^]: Hermes Agent 官方文档 Skills System, https://hermes-agent.nousresearch.com/docs/user-guide/features/skills —— `skill_manage` 动作表（create/patch/edit/delete/write_file/remove_file）；"skills.write_approval: false = write freely (default) | true = require approval"，暂存于 `~/.hermes/pending/skills/`；`/learn` 蒸馏知识库技能；Skills Hub 多源安装。
[^28^]: GitHub NousResearch/hermes-agent-self-evolution, https://github.com/NousResearch/hermes-agent-self-evolution （stars 5,090，MIT，2026-08-20）—— "DSPy + GEPA… No GPU training required… ~$2-10 per optimization run"；Guardrails："Full test suite… Size limits… Semantic preservation… PR review, never direct commit"；GEPA "ICLR 2026 Oral"。PLAN.md：Tier1 SKILL.md 最高价值最低风险。
[^29^]: arXiv:2604.01687v1 "EvoSkills: Self-Evolving Agent Skills via Co-Evolutionary Verification", 2026-04-02, https://arxiv.org/html/2604.01687v1 —— "Surrogate Verifier, a separate LLM session without inheriting the generator's biases… synthesizes test cases and scripts… information isolation"；消融：去 surrogate verifier 71.1%→41.1%。
[^30^]: emergentmind paper digest, https://www.emergentmind.com/papers/2604.01687 —— "71.1% pass rate on SkillsBench, outperforming human-curated skills by +17.6pp"；evoskills.net 官方页：No-skill 30.6% / Self-Generated 32.0% / Human-curated 53.5% / EvoSkills 71.1%（+40.5pp）。
[^31^]: alphaxiv, "CoEvoSkills", 2026-08-10, https://www.alphaxiv.org/abs/2604.01687 —— Test Escalation 机制；Natural Science 域人工技能反而降性能（"human-machine cognitive misalignment"）；跨 6 模型迁移 +35~44pp。
[^32^]: GitHub Zhang-Henry/CoEvoSkills README, https://github.com/Zhang-Henry/CoEvoSkills （stars 60，Apache-2.0，2026-08-20）—— 自定义任务接入（task.toml + answer-free background doc）；agent adapter 注册 `--agent-import-path`；COLM 2026。
[^33^]: GitHub ma-compbio-lab/SkillFoundry README, https://github.com/ma-compbio-lab/SkillFoundry （stars 36，Apache-2.0，2026-08-20）—— 六步闭环（Tree Construction→Resource Mining→Skill Compilation→Multi-Level Validation→Tree Expansion→Refinement & Loop）；"267+ skills across 28 scientific domains；71.1% novelty vs SkillHub/SkillSMP；5/6 MoSciBench datasets improved"；`pip install -e .`、`cycle/campaign/design-skill` CLI。
[^34^]: arXiv:2604.03964v1, 2026-04-05, https://arxiv.org/html/2604.03964v1 —— 技能包含 "task scope, inputs and outputs, execution steps, environment assumptions, provenance, and tests"；Limitations："coverage still relatively limited… validated primarily through internal testing pipeline rather than broad downstream evaluation… use with appropriate caution in high reliability settings"。
[^35^]: GitHub d-wwei/skill-se-kit-python（综述性引用）, 2026-03-21, https://github.com/d-wwei/skill-se-kit-python —— XSKILL：arXiv:2603.12056，代码 XSkill-Agent/XSkill，"dual-stream knowledge system — a Skill Library… and an Experience Bank… cross-rollout critique"。stars 253、MIT（2026-08-20 抓取 XSkill-Agent/XSkill 页面）。
[^36^]: GitHub Qwen-Applications/skill-self-play, 2026-07-15, https://github.com/Qwen-Applications/skill-self-play （stars 127，Apache-2.0，2026-08-20）—— "Evolving skill library… Verified task generation… Frontier-based co-evolution… Targeted skill evolution: refinement, pruning, and induction"。
[^37^]: 百度百科（英文） SkillNet 词条, 2026-05-09, https://baike.baidu.com/en/item/SkillNet/1670523 —— 浙大/复旦/阿里等近 20 家机构，2026-04-10 论文；"three-layer architecture… Five-dimensional Evaluation Mechanism covering safety and completeness"；"average reward increase of 40% and a 30% reduction in execution steps"；集成 OpenClaw 与 Huawei JiuwenClaw。开源仓库地址未查到。
[^38^]: skillsllm.com SciAgent-Skills 条目, 2026-04-15, https://skillsllm.com/skill/sciagent-skills —— "199 ready-to-use scientific skills… BixBench 65.3%→92.0%"；仓库 jaechang-hits/SciAgent-Skills（339 stars，2026-08-20 抓取）。
[^39^]: CSDN, "将 Agent skill内化于模型参数的上下文：SKILL0", 2026-04-04, https://blog.csdn.net/kakaZhui/article/details/159830115 —— 检索式技能三痛点："检索噪声与语义污染…Token 开销与上下文爆炸…'照本宣科'而非'内化吸收'"。
[^40^]: zdoc.app ai-boost/awesome-prompts（Self-Improving Agents 表）, 2026-07-24, https://zdoc.app/zh/ai-boost/awesome-prompts —— HyperAgents（facebookresearch/HyperAgents, arXiv:2603.19461）、OpenClaw-RL（2603.10165）、MetaClaw（2603.17187，"21.4%→40.6%"）、CORAL（2604.01658）、SKILL0（2604.02268）。
[^41^]: CSDN, "Agent Skills 的自演化：从SKILL.md 到会生长的技能库", 2026-07-23, https://blog.csdn.net/xx_nm98/article/details/163142977 —— "候选 skill 经过静态检查、沙箱运行、回归评测、人工或策略审核后，才进入版本化 skill registry；生产 Agent 只加载已发布版本"；"没有 eval gate 的 skill evolution，本质只是自动改提示词"。

# 维度03：Prompt/程序自动优化框架（Self-Evolution 调研）

> 调研日期：2026-08-20。所有 stars 均为当日通过 GitHub 页面抓取（API 因限流不可用，改用 HTML `users starred this repository` 字段与 commits atom feed 交叉验证）。
> 主题：把 prompt、指令、few-shot、agentic workflow 当作可优化对象的开源框架。面向"Cursor + GPT + skill 管理工程中加入 Agent 自进化模块"的选型需求。

## 0. 结论速览（TL;DR）

| 方案 | Stars(2026-08-20) | License | 活跃度 | 优化对象 | 即插即用 | 推荐场景 |
|---|---|---|---|---|---|---|
| **DSPy (MIPROv2 + GEPA)** | 37,443 | MIT | 极高（最近提交 2026-08-18） | 指令+few-shot+权重 | 高（pip，三行 compile） | 首选基座；生产级 |
| **GEPA (独立库)** | 6,170 | MIT | 极高（2026-08-19） | 任意文本参数（prompt/代码/策略） | 高 | 无 DSPy 依赖的反思式优化 |
| **TextGrad** | 3,702 | MIT | 停滞（最后提交 2025-07-25） | 任意文本变量（prompt/代码/分子） | 中 | 多节点系统的"文本反向传播" |
| **OPRO** | 770 | Apache-2.0 | 停滞（2024-12-04） | 指令 | 低（研究代码） | 算法参考，不建议直接用 |
| **AFlow (MetaGPT 内)** | 69,904（整个 MetaGPT） | MIT | 中（2026-01-21） | 工作流拓扑+节点 prompt | 中（需配 benchmark 类） | 多智能体工作流结构进化 |
| **SAMMO** | 775 | MIT | 停滞（2025-06-23） | 结构化 prompt 程序 | 中 | prompt 压缩、RAG pipeline 调优 |
| **PromptAgent** | 355 | Apache-2.0 | 停滞（2025-07-17） | 专家级任务指令 | 中 | 领域知识密集型单 prompt |
| **Trace/OPTO** | 753 | MIT | 低（2025-08-14） | prompt+代码+超参（异构） | 中 | 研究；OPTO 抽象 |
| **EvoAgentX**（集成者） | 3,242 | MIT | 高（2026-08-14） | 工作流+prompt+工具配置 | 高 | 想一次集成 TextGrad/AFlow/MIPRO |

**给用户的直接建议**：自进化模块以 **DSPy 3.x + GEPA** 为主干（生态、文档、维护最好，metric/evaluator 完全自定义），需要优化**工作流结构**而不仅是 prompt 时叠加 **AFlow**（或直接用 EvoAgentX 整合层）；OPRO/SAMMO/PromptAgent 作为算法思想参考即可。

---

## 1. DSPy（stanfordnlp/dspy）—— 重点

- **仓库**：https://github.com/stanfordnlp/dspy ；**Stars 37,443**（2026-08-20 抓取）[^1^]
- **License**：MIT（`LICENSE` 头： "MIT License, Copyright (c) 2023 Stanford Future Data Systems"）[^2^]
- **语言**：Python（pip 包名 `dspy`）；**最新版本 3.3.0**（2025-11 发布；含实验性"把程序作为代码优化"的 Flex、ReActV2、GEPA 0.1.1 支持）[^3^]
- **维护状态**：极高，main 分支最近提交 2026-08-18[^1^]

### 核心机制
DSPy 把 LLM 调用抽象为 **Signature（输入/输出声明）+ Module（Predict/ChainOfThought/ReAct 等）**，优化器（teleprompter）把"编译"程序 = 自动搜索最优 prompt 配置[^4^]。

**MIPROv2**（arXiv:2406.11695）三阶段：
1. Bootstrap 生成 few-shot 候选集（labeled + bootstrapped demos）；
2. LLM 生成 grounded instruction 候选（输入数据集描述、程序代码、task demos、6 类 tips：creative/simple/description/high_stakes/persona 等）；
3. 用 Optuna 贝叶斯优化搜索 instruction × demos 最优组合[^5^][^6^]。
原文摘录："MIPROv2同时优化prompt中的两个部分：instruction 和 few-shot 部分…Step 3 借助 Optuna 开源框架实现"[^5^]。

**GEPA（DSPy 内置）**：`dspy.GEPA`，依赖 `gepa[dspy]` 独立包；"用户除标量分数外还可提供文本反馈（text feedback）指导优化……使 GEPA 能在极少 rollouts 内提出高性能 prompt"[^7^]。3.2.0 起 `BetterTogether` 可用策略字符串串联优化器，如 `strategy="p -> w -> p"`（prompt 优化→微调→再 prompt 优化）[^3^]。

### 与主流框架关系
与 LangChain **互补而非竞争**："DSPy 优化 LLM 产出的 prompt 质量；LangChain 编排 pipeline。生产系统可用 DSPy 优化 LangChain RAG 内部的生成 prompt"[^8^]。DSPy 底层正与 LiteLLM 解耦（3.2/3.3 的 BaseLM 改造）[^3^]；与 MLflow 3.0 原生集成做追踪[^9^]。

### 即插即用程度 & 二次开发入口
- **接入现有 prompt 程序**：需把逻辑改写为 `dspy.Module`（signature + forward），再用 `optimizer.compile(program, trainset=..., valset=...)`；优化产物可 `program.save("x.json")` 序列化后脱离 DSPy 部署[^4^][^6^]。
- **自定义 metric**：任意 `metric(example, prediction, trace=None) -> bool/float` 函数[^8^]；GEPA 可用返回 `ScoreWithFeedback` 的反馈 metric。
- **自定义优化算子**：GEPA 支持 `custom instruction_proposer`（含多模态）、自定义 component selection 逻辑、`gepa_kwargs` 透传[^3^]；MIPROv2 可调 `num_candidates / max_bootstrapped_demos / max_labeled_demos / num_trials`。
- **领域定制**：换 trainset + metric 即可；instruction proposer 可注入领域先验；社区已有临床 QA 等垂直落地（ArchEHR-QA 2026 用 MIPROv2 全 subtask 自动寻优，获全场第二 mean rank）[^10^]。

### 典型成本
- `auto` 预设：light（num_trials≈7，val≤100）/ medium（≈25 trials，val≤300）/ heavy（≈50 trials，val≤1000）[^6^]；另一社区 skill 文档记 light~10 / medium~40 / heavy 100+ trials[^11^]（两来源口径不同，以实际 `dspy` 版本源码为准）。
- 费用量级："MIPRO with 200 examples can cost $5–10 in API calls"[^8^]；heavy 档耗时以小时计[^11^]。
- GEPA 官方 FAQ 对比：HotPotQA 上 GEPA 用 100–500 rollouts、约 **$20**、3 小时，达到 GRPO（5,000+ rollouts、$300、24h）以上 20% 的效果[^12^]。

### 局限与争议
- 每次 compile 都是真金白银的 API 消耗；"并非所有任务都能提升，接近模型能力上限的任务收益递减"[^8^]。
- 编译产物 prompt 是自动生成的，可解释性/调试需要翻 compile trace[^8^]。
- **版本敏感性**：2.x→3.0 有 breaking changes（移除 `dspy.Program` 别名、移除社区检索器、停支持 Python 3.9）[^9^]，升级需 pin 版本[^8^]。
- 第三方比较研究指出，2025 年后的新方法（CAPO 等）声称可在部分基准超过 MIPROv2 甚至 GEPA[^13^]——提示"DSPy 默认优化器 ≠ 永远 SOTA"。

---

## 2. GEPA 独立库（gepa-ai/gepa）

- **仓库**：https://github.com/gepa-ai/gepa ；**Stars 6,170**（2026-08-20）[^1^]
- **License**：MIT（"Copyright © 2025 Lakshya A Agrawal, Permission is hereby granted, free of charge…"）[^2^]；**语言**：Python；最近提交 2026-08-19，极活跃[^1^]
- **论文**：arXiv:2507.19457，**ICLR 2026 Oral**[^14^]

### 核心机制
Genetic-Pareto：对复合 AI 系统中每个 prompt 做**反思式突变**——采样 rollout 轨迹（推理链、工具调用、编译器报错等），用反思 LLM 诊断失败并提出新 prompt；维护**逐实例 Pareto 前沿**避免贪心局部最优；Merge 变体可交叉不同谱系的互补策略[^14^][^15^]。
关键结果："在 Qwen3 8B 上以少 35× 的 rollouts 超过 GRPO（24,000 rollouts+LoRA）达 19%；全面超过 MIPROv2，聚合增益 +14% vs MIPROv2 的 +7%"[^14^]。

### 与主流框架关系
既可作 `dspy.GEPA` 内置优化器，也可 `pip install gepa` 独立用；通过 **`GEPAAdapter` 接口**可优化"任意文本工件：prompt、代码、agent 架构、调度策略、矢量图"（2026-02 官方博客 "optimize anything" API）[^16^][^15^]。

### 二次开发入口 / 领域定制
实现 `GEPAAdapter`（evaluate + 可选 feedback 函数），提供 trainset、metric、feedback function `μf`、rollout 预算 B[^15^]；3 个样本即可起效，建议 30–300 样本[^12^]。

### 典型成本
样本效率是主打："HotPotQA 上 100–500 rollouts ≈ $20、3 小时，8× 快于 GRPO、15× 便宜"[^12^]。

### 局限
- 反思质量依赖强 reflection LM（通常需 GPT-4 级）[^17^]；
- 单轨迹方法（TextGrad 类）的批评同样部分适用：minibatch 评估有方差，官方建议 80/20 或 50/50 划分 train/val[^12^]。

---

## 3. TextGrad（zou-group/textgrad）

- **仓库**：https://github.com/zou-group/textgrad ；**Stars 3,702**（2026-08-20）[^1^]
- **License**：MIT（"Copyright (c) 2024 Zou Group"）[^2^]；**语言**：Python；论文 arXiv:2406.07496（2024-06）[^18^]
- **维护状态**：**最后提交 2025-07-25，一年未更新**[^1^]——采用时注意

### 核心机制
把复合 AI 系统建成**计算图**，节点是文本 Variable；"梯度"是 LLM 生成的自然语言批评（`∇LLM` 算子），沿图反向传播（拓扑排序），再用 **TGD（Textual Gradient Descent）** 让 LLM 吸收批评改写变量；支持 minibatch、自然语言约束、momentum（`momentum_window`）[^18^][^19^]。API 刻意仿 PyTorch（`loss.backward()` / `optimizer.step()`）[^20^]。

### 与主流框架关系
引擎抽象（OpenAI/Anthropic/本地模型均可作 backward engine）；与 LangChain 无官方深度集成（未查到），但因变量即字符串，可包裹任意框架的 prompt。EvoAgentX 把它作为内置进化算法之一[^21^]。

### 二次开发入口
- 自定义 loss：`tg.TextLoss("评估指令…")` 或任意可调用 evaluator；
- 自定义 optimizer 提示词、约束、momentum；
- 两类优化：**instance optimization**（优化单个解答/代码/分子）与 **prompt optimization**（优化可泛化的系统 prompt）[^18^]。

### 典型成本
每次优化迭代 = 前向 + 评估 + 梯度 + 更新多次 LLM 调用；论文代码优化实验"每次迭代调用 gpt-4o 三次：评估 test-time loss、收集梯度、更新代码"[^19^]。prompt 优化案例：GPT-3.5 QA 准确率 78%→92%，仅需少量迭代[^20^]。

### 局限与争议
- 单轨迹贪心下降，易陷局部最优——GEPA 侧比较称"TextGrad 像沿单条轨迹做梯度下降，GEPA 的种群+Pareto 能避开单候选方法的局部最优"[^16^]；
- 2026 年的对比论文把 TextGrad 每步 backward+TGD 两次 LLM 调用作为 baseline 评估，暗示其已是"经典基线"而非前沿[^22^]；
- 仓库停更（2025-07 后无提交），issue 积压风险未查到量化数据。

---

## 4. OPRO（google-deepmind/opro）

- **仓库**：https://github.com/google-deepmind/opro ；**Stars 770**（2026-08-20；第三方审计 2026-07-10 记 ~762，吻合）[^1^][^23^]
- **License**：Apache-2.0[^23^]；**语言**：Python/Jupyter；**最后提交 2024-12-04，基本停更**[^1^]
- **论文**：arXiv:2309.03409（Google DeepMind, ICLR 2024）

### 核心机制
LLM 即优化器：meta-prompt 携带"历史 (instruction, score) 对"，优化器 LLM 每步生成 ≤8 条新指令 → scorer LLM 在训练集上打分 → 追加进历史，迭代至收敛。结果：GSM8K 上比人工 prompt 高至多 8%，BBH 上高至多 50%[^24^]。

### 二次开发入口
`opro/optimization/optimize_instructions.py`（入口）、`opt_utils.py`（`run_evolution`、`gen_meta_prompt`）、`eval_utils.py/metrics.py`（打分）[^23^]——结构清晰，适合**借鉴 meta-prompt 模板自行实现**，而非当库用。

### 典型成本
第三方测算："20+ 步、每步扩展 8 条、每条 100 次 scorer 调用 → 约 **16,000 次 LLM 调用**"，并被批评"更新只基于历史表现而非全量数据，结果不可预测、低效"[^25^]。

### 局限
代码针对 PaLM 2/text-bison 时代 API，直接跑通需改造；停更；算法思想已被 GEPA/EvoPrompt 系全面超越[^13^]。

---

## 5. AFlow（内置于 geekan/MetaGPT，ICLR 2025）

- **仓库**：https://github.com/geekan/MetaGPT （组织已迁移至 FoundationAgents/MetaGPT）；MetaGPT 整库 **Stars 69,904**（2026-08-20）[^1^]；AFlow 代码位于 `metagpt/ext/aflow/` + `examples/aflow/`[^26^]
- **License**：MIT[^2^]；**语言**：Python；仓库最后提交 2026-01-21[^1^]
- **论文**：arXiv:2410.10762，ICLR 2025；DeepWisdom/HKUST(GZ) 等[^27^]

### 核心机制
把工作流优化形式化为**代码表示的工作流空间上的搜索**：节点=LLM 调用，边=逻辑依赖；用 **MCTS 变体**（软混合概率选择 → LLM 作为 optimizer 扩展改代码/prompt → 执行评估 → 经验沿树回传）迭代；预定义 **Operator**（Generate/Format/Review/Revise/Ensemble/Test/Programmer）作为构建块[^26^][^27^]。
结果："超过人工设计方法平均 5.7%，超过同期自动工作流优化工作 19.5%；让小模型以 GPT-4o **4.55% 的推理成本**在特定任务上超过 GPT-4o"[^27^]。

### 接入与二次开发
- 运行：`python -m examples.aflow.optimize --dataset MATH --max_rounds 20 --validation_rounds 5`；支持 `--check_convergence` 早停[^26^]。
- **领域定制**：继承 `BaseBenchmark` 实现 `evaluate_problem / calculate_score / get_result_columns`，注册到 evaluator 与 optimizer；可自定义 Operator[^26^]。
- 评估器直接执行工作流，每个候选在验证集上跑 5 次取均值/方差（"提高单次迭代成本，但反馈更准、减少总轮次"）[^27^]。

### 典型成本
每轮 = 1 次 optimizer LLM 生成 + 5×验证集规模的工作流执行；默认 20 轮。论文强调推理成本节省（4.55%），**优化阶段总 token 成本未查到官方数字**；社区反馈一轮 MATH 优化需数小时（推断，基于执行次数，标注为推断）。

### 局限与社区争议（证据充分）
- GitHub issue 可见多处可用性问题：numpy 序列化报错致 round 失败（#1706）、自定义 OpenAI 兼容端点 `object list can't be used in 'await'`（#1597）、非白名单模型报 `No module named ...round_8`（#1673）[^28^]——**对新模型/自定义 LLM 的适配坑较多，需要改源码**。
- MetaGPT 主库方向已转向（FoundationAgents），AFlow 子模块演进放缓（推断，依据主库提交频率与 ext 目录更新情况）。

---

## 6. SAMMO（microsoft/sammo）

- **仓库**：https://github.com/microsoft/sammo ；**Stars 775**（2026-08-20）[^1^]
- **License**：MIT[^2^]；**语言**：Python；**最后提交 2025-06-23，停滞**[^1^]
- **论文**：arXiv:2404.02319（"Prompts As Programs"，Microsoft Research）[^29^]

### 核心机制
把 prompt 表示为**结构化对象/函数图**（meta-prompt program），定义结构感知变异算子（节点重排/替换/删除、指令文本改写、增删子节点），用**遗传算法或 beam search** 在编译期搜索更优程序；黑盒设定（仅需 API 采样）。三个场景收益：instruction tuning +10–100%、RAG 调优 +26–133%、prompt 压缩 >40%；并发现"复杂 prompt 需对每个 LLM 分别优化，弱模型收益更大"[^29^][^30^]。

### 二次开发入口
自定义变异算子、自定义 search runner（beam/genetic）、自定义后端 LLM；适合 RAG pipeline 与长 prompt 压缩场景[^30^]。

### 局限
停更一年+；社区热度低（775 stars）；微软后续重心转向 Trace[^31^]。典型成本未查到官方数字（取决于搜索预算 × 评估集大小）。

---

## 7. PromptAgent（XinyuanWangCS/PromptAgent）

- **仓库**：https://github.com/XinyuanWangCS/PromptAgent ；**Stars 355**（2026-08-20）[^1^]
- **License**：Apache-2.0[^2^]；**语言**：Python；**最后提交 2025-07-17**[^1^]
- **论文**：arXiv:2310.16427，ICLR 2024（UCSD/CMU/MBZUAI/MSR）[^32^]

### 核心机制
把 prompt 优化建成**战略规划问题**：MCTS 中 state=prompt、action=基于 base LLM 错误样本生成的 error feedback；optimizer LLM（如 GPT-4）反思错误并把领域洞察合并进 prompt；模拟+回传 Q 值选择高奖励路径。产出"专家级"长 prompt（含术语澄清、异常处理、格式约束等），BBH 平均超 CoT 9.5%、超 APE 11.2%；生物医学领域任务超 APE +7.3%[^32^][^33^]。

### 领域定制
天生面向领域知识密集任务（论文主打 biomedical NER 等）；换 base task dataset + 初始 prompt 即可；优化产物可跨模型迁移（GPT-3.5 上优化 → GPT-4/PaLM2 仍有效，"每任务只需优化一次"）[^33^]。

### 典型成本
精确的 LLM 调用数**未查到**官方数字；论文仅称比蒙特卡洛采样类方法"探索效率更高、用更少 explored prompts 达到更高准确率"[^33^]。

### 局限
停更；只优化单条任务指令，不处理 few-shot/多模块系统；产出 prompt 很长，弱模型可能 hold 不住（论文自述小模型"可能无法领会专家级 prompt，导致性能显著下降"）[^33^]。

---

## 8. Trace / OPTO（microsoft/Trace）

- **仓库**：https://github.com/microsoft/Trace ；**Stars 753**（2026-08-20）[^1^]
- **License**：MIT[^2^]；**语言**：Python；**最后提交 2025-08-14，低活跃**[^1^]；社区 fork AgentOpt/OpenTrace 仍在演进[^34^]
- **论文**：arXiv:2406.16218（"Trace is the New AutoDiff"，Stanford+MSR，ICML 2024 相关系列）

### 核心机制
提出 **OPTO（Optimization with Trace Oracle）**：优化器接收执行 trace + 对输出的丰富反馈，迭代更新**异构参数（prompt、超参、代码）**；Trace 用 PyTorch 式接口（`@trace.model`、`trace.node(trainable=True)`、`@trace.bundle`）把任意计算工作流转为 OPTO 实例；自带通用优化器 **OptoPrime**（LLM-based），可做数值优化、prompt 优化、超参调优、机器人控制器设计、代码调试[^35^][^34^]。

### 与主流框架关系
早期示例基于 AutoGen config；抽象层级与 LangChain 正交（可包裹任何 Python 工作流）[^34^]。

### 局限
维护放缓；`opti` 包生态小；文档/教程少于 DSPy。典型成本：每 epoch = 前向 + 反馈 + backward + step（每可训练节点若干 LLM 调用），无官方汇总数字（未查到）。

---

## 9. 集成层与其他值得关注的 2025–2026 工作

- **EvoAgentX**（https://github.com/EvoAgentX/EvoAgentX，**3,242 stars**，MIT，最近提交 2026-08-14，活跃）：EMNLP 2025 Demo；五层架构，**evolving 层直接集成 TextGrad、AFlow、MIPRO 三种算法**迭代优化 agent prompt、工具配置与工作流拓扑；HotPotQA F1 +7.44%、MBPP pass@1 +10%、MATH +10%、GAIA 最高 +20%；支持 LiteLLM 多模型、HITL、长期记忆[^21^][^36^]。——想"开箱即用地组合多种进化算法"时最省事。
- **promptolution**（https://github.com/gepromptet/promptolution，EACL 2026）：统一模块化 prompt 优化框架，内置多种优化器实现（含 **CAPO** 成本感知进化优化）、统一 LLM 后端（API/本地/vLLM）、缓存与 token 统计；2025 年比较有研究称 CAPO 可超过 GEPA[^37^][^13^]。
- **AutoPrompt**（Eladlev/AutoPrompt）：Intent-based Prompt Calibration，"GPT-4 Turbo 下几分钟、<$1 完成一次优化"，与 LangChain/Wandb/Argilla 集成[^38^]。
- **Promptomatix**（Salesforce）：基于 DSPy 的零配置封装（自动生成合成数据、选模块和 metric），适合不想手写 DSPy 程序的场景[^39^]。
- 学术前沿（2026）：A²Flow（AAAI'26）、FlowBot（ICML'26，bilevel+文本梯度）、JudgeFlow、AgentEvo 等见 Awesome-Self-Evolving-Coding-Agents 清单[^40^]。

---

## 10. 横向对比：接入用户"Cursor + GPT + superpower skill"工程的建议

1. **优化对象只是 prompt/few-shot** → DSPy `dspy.GEPA`（默认）或 `dspy.MIPROv2`（数据量 ≥200 时）；metric 直接复用工程里的测试/评审脚本。
2. **不想引入 DSPy 编程模型** → `pip install gepa` + 实现 `GEPAAdapter`，把现有 prompt 文件当作可变文本参数。
3. **要进化多步 agent 工作流结构（增删节点、改拓扑）** → AFlow（接受改源码适配自有模型）或 EvoAgentX（更省心）。
4. **成本预算**：轻量验证 < $1（AutoPrompt 级）；常规单任务 GEPA ≈ $20；MIPROv2 medium ≈ $5–10；AFlow/OPRO 级全量搜索可达数千到上万次调用。
5. **共性风险**：优化集会过拟合（务必留 hold-out test set）；优化结果对底座模型版本敏感（换模型需重优化，SAMMO 论文有实证[^29^]）；所有框架都要求**可靠的自动 metric**——这是接入成本的大头，而非框架本身。

---

## 参考来源

[^1^]: GitHub 仓库页面抓取（`users starred this repository` 字段 + commits atom feed `<updated>`），2026-08-20。各仓库 stars：stanfordnlp/dspy 37,443（last commit 2026-08-18）；gepa-ai/gepa 6,170（2026-08-19）；zou-group/textgrad 3,702（2025-07-25）；google-deepmind/opro 770（2024-12-04）；microsoft/sammo 775（2025-06-23）；XinyuanWangCS/PromptAgent 355（2025-07-17）；microsoft/Trace 753（2025-08-14）；geekan/MetaGPT 69,904（2026-01-21）；EvoAgentX/EvoAgentX 3,242（2026-08-14）。
[^2^]: 各仓库 `LICENSE` 文件头抓取，2026-08-20：dspy="MIT License, Copyright (c) 2023 Stanford Future Data Systems"；gepa="Copyright © 2025 Lakshya A Agrawal, Permission is hereby granted, free of charge…"（MIT 条款）；textgrad="MIT License, Copyright (c) 2024 Zou Group"；sammo="MIT License, Copyright (c) Microsoft Corporation"；PromptAgent="Apache License Version 2.0"；Trace="MIT License, Copyright (c) Microsoft Corporation"；MetaGPT="The MIT License, Copyright (c) 2024 Chenglin Wu"；OPRO Apache-2.0 见 [^23^]。
[^3^]: DSPy Releases, https://github.com/stanfordnlp/dspy/releases （2025-11-18 检索）。摘录："DSPy 3.3.0 is a feature release with a new experimental way to optimize programs as code…"；"BetterTogether now accepts arbitrary optimizers… strategy='p -> w -> p'"；"DSPy now supports gepa[dspy]==0.1.1"；"Add custom instruction_proposer support to GEPA"；"Add custom component selection logic support"。
[^4^]: myengineeringpath.dev "DSPy Framework — Programmatic Prompt Optimization (2026)", https://myengineeringpath.dev/tools/dspy-guide/ （2026-03-20）。摘录："Optimizers take your program, training data, and metric — then systematically search for the best prompt configuration"。
[^5^]: 张铁蕾《浅谈DSPy和自动化提示词工程（中）》https://zhangtielei.com/posts/blog-dspy-internals-2.html （2024-11-30）。摘录："MIPROv2同时优化prompt中的两个部分：instruction 和 few-shot 部分…Step 3 借助一个叫做 Optuna 的开源框架来实现"。
[^6^]: 知乎《自动写提示词：DSPy.MIPROv2的介绍与实践》https://zhuanlan.zhihu.com/p/18156572393 （2025-01-14）。摘录："auto：light=7，medium=25，heavy=50（num_trials）；val_size：light=100，medium=300，heavy=1000"；"Step1 Bootstrap…Step2 生成N条候选instruction…tips 有6类，如creative/simple/description/high_stakes/persona…Step3 Bayesian Search"。
[^7^]: DSPy 官方文档 dspy.GEPA Overview, https://dspy.ai/api/optimizers/GEPA/overview/ 。摘录："users can also provide GEPA with a text feedback to guide the optimization process… allows GEPA to propose high performing prompts in very few rollouts"。
[^8^]: 同 [^4^]。摘录："DSPy vs LangChain: They are complementary, not competing… MIPRO with 200 examples can cost $5-10 in API calls… Not all tasks improve… DSPy's API has changed between major versions. Pin your dspy-ai version"。
[^9^]: 知乎《DSPy 3.0.0 发布》https://zhuanlan.zhihu.com/p/1939274286901761918 （2025-08-14）。摘录："与 MLflow 3.0 原生集成…移除社区检索器…停止支持 Python 3.9…移除别名 dspy.Program…GEPA：构建提示词的帕累托树，初步结果显示在多个任务上优于 MIPROv2"。
[^10^]: arXiv:2605.10877 "Neural at ArchEHR-QA 2026", https://arxiv.org/html/2605.10877v1 （2026-05-11）。摘录："leveraging DSPy's MIPROv2 optimizer to autonomously discover high-performing prompts for each stage… mean rank of 4.00, the second best among teams"。
[^11^]: agentscli marketplace "dspy-miprov2-optimizer" skill, https://marketplace.agentscli.com/items/omidzamani-dspy-skills-dspy-miprov2-optimizer （2026-08-07）。摘录："light ~10 / medium ~40 / heavy 100+ trials… Limitations: High computational cost (many LLM calls); Optimization time: hours for 'heavy' preset"。
[^12^]: GEPA 官方 FAQ, https://gepa-ai.github.io/gepa/guides/faq/ 。摘录："GEPA can show improvements with as few as 3 examples… Aim for 30-300 examples… Concrete comparison on HotPotQA: GEPA achieves 20% better performance than GRPO in 35x fewer rollouts (100–500 vs. 5,000+), 8x faster wall-clock time (3 hours vs. 24 hours), at 15x lower cost ($20 vs. $300)"。
[^13^]: arXiv:2605.18869（综述章节）。摘录："A recent comparison [Zehle et al. 2025a] shows that CAPO can outperform SOTA optimizers like GEPA… GEPA instead uses reflective prompt evolution… outperforming MIPROv2. Both are included in DSPy"。
[^14^]: arXiv:2507.19457 "GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning", https://arxiv.org/abs/2507.19457 （v1 2025-07-25, v2 2026-02-14）。摘录："GEPA outperforms GRPO by 6% on average and by up to 20%, while using up to 35x fewer rollouts. GEPA also outperforms the leading prompt optimizer, MIPROv2, by over 10% (e.g., +12% accuracy on AIME-2025)"。ICLR 2026 Oral 及软件地址见引用 [^161^]（arXiv:2604.04347 参考文献："GEPA… ICLR 2026 (Oral). Software: https://github.com/gepa-ai/gepa"）。
[^15^]: arXiv:2507.19457 HTML, https://arxiv.org/html/2507.19457v1 。摘录："GEPA (Genetic-Pareto), a reflective prompt optimizer for compound AI systems that merges textual reflection with multi-objective evolutionary search… maintains a Pareto front… GEPA receives: system Φ, training dataset D_train, metric μ, feedback function μ_f and total rollout budget B"。
[^16^]: Morph "GEPA Prompt Optimization", https://www.morphllm.com/gepa-prompt-optimization （2026-03-14）。摘录："GEPA ships as a standalone library (pip install gepa). Through its GEPAAdapter interface it can optimize any text artifact: prompts, code, agent architectures, scheduling policies… TextGrad iteratively refines a single prompt using textual feedback… GEPA's population-based approach avoids local optima that single-candidate methods like TextGrad can converge to"。另见 gepa-ai 官方博客 "optimize anything: A universal API for optimizing any text parameter"（2026-02-18，经 [^161^] 引用）。
[^17^]: 微信文章《GEPA：反思式Prompt进化，效果超过RL》http://mp.weixin.qq.com/s?__biz=MzkxNTU5NDM4Mg==&mid=2247485948 （2025-08-22）。摘录：GEPA 元提示需"喂给一个高级的LLM（如GPT-4）…反思现有指令的不足之处"。
[^18^]: arXiv:2406.07496 "TextGrad: Automatic 'Differentiation' via Text", https://arxiv.org/html/2406.07496v1 （2024-06-11）。摘录："we open-source our framework at https://github.com/zou-group/textgrad… Instance vs Prompt Optimization… Batch Optimization / Constrained Optimization / Momentum"。
[^19^]: 同 [^18^]（中文镜像摘录 https://arxiv.org/pdf/2406.07496v1 ）："在每次优化迭代中，TEXTGRAD 会调用 gpt-4o 三次：一次用于评估测试时损失，一次用于收集梯度，一次用于更新代码片段"。
[^20^]: 百度千帆社区《浅析优化文本提示技术——TextGrad》https://qianfan.cloud.baidu.com/qianfandev/topic/362147 （2024-09-11）；腾讯云开发者社区 https://developer.cloud.tencent.com/article/2485613 （2025-01-08）。摘录："TextGrad 关键组件：变量、函数、梯度、文本梯度下降（TGD）…API 设计模仿了 PyTorch"；"将GPT-3.5-turbo的QA准确率从78%提升到了92%，而且只需进行少量几次的优化迭代"。
[^21^]: ACL Anthology 2025.emnlp-demos.47 "EvoAgentX", https://aclanthology.org/2025.emnlp-demos.47/ 。摘录："within the evolving layer, EvoAgentX integrates three MAS optimization algorithms, TextGrad, AFlow, and MIPRO… 7.44% increase in HotPotQA F1, 10.00% improvement in MBPP pass@1, 10.00% gain in MATH… up to 20.00% on GAIA. Source code: https://github.com/EvoAgentX/EvoAgentX"。
[^22^]: arXiv:2603.18620。摘录："TextGrad (Yuksekgonul et al., 2024) decomposes each prompt update into two LLM calls: a backward call that critiques the current instruction… followed by a Textual Gradient Descent (TGD) call… treat each backward-TGD step as one evolution round"（作为 baseline）。
[^23^]: faresrafat3/opro-full-extraction（对官方仓库的审计提取）, https://github.com/faresrafat3/opro-full-extraction （2026-07-10）。摘录："Code: https://github.com/google-deepmind/opro, Audited commit a76bdce… GitHub stars: ~762 (verified 2026-07-10) · License: Apache-2.0… Instruction optimization entry: opro/optimization/optimize_instructions.py; Evolution + meta-prompt: opt_utils.py (run_evolution, gen_meta_prompt)"。
[^24^]: arXiv:2309.03409 "Large Language Models as Optimizers"。摘录："the best prompts optimized by OPRO outperform human-designed prompts by up to 8% on GSM8K, and by up to 50% on Big-Bench Hard tasks"。
[^25^]: MDPI Applied Sciences 15(9):5198（2025-05-07）, https://www.mdpi.com/2076-3417/15/9/5198 。摘录（Table 1）："Iterative-APE: 100,000 LLM calls; OPRO: 8 prompts/step × 100 × 20 steps = 16,000; APO: 28,800"；正文："OPRO adopts an implicit reflection-based strategy… updates are made based only on past performance rather than the full dataset, optimization results can be unpredictable and inefficient"。
[^26^]: MetaGPT examples/aflow README, https://github.com/geekan/MetaGPT/tree/main/examples/aflow （亦见 FoundationAgents/MetaGPT 同路径）。摘录："Operator: Predefined combinations of Nodes… Generate, Format, Review, Revise, Ensemble, Test, and Programmer… You can customize your own Operator"；"For custom tasks… Inherit the BaseBenchmark class and implement evaluate_problem, calculate_score, and get_result_columns"；"python -m examples.aflow.optimize --dataset MATH --max_rounds 20 --validation_rounds 5"。
[^27^]: arXiv:2410.10762 "AFlow: Automating Agentic Workflow Generation"。摘录："outperform all manually designed methods by an average of 5.7% and surpass contemporary automatic workflow optimization work by 19.5%… enables smaller models to outperform GPT-4o on specific tasks at 4.55% of its inference cost… We test each generated workflow 5 times on the validation set… early stopping… The code is available at https://github.com/geekan/MetaGPT"。开源公告（EINPresswire, 2025-04-21）："ICLR 2025 framework uses MCTS to generate optimal workflows, attaining GPT-4 results at lower costs" https://www.techdogs.com/tech-news/ein-presswire/metagpt-open-sources-aflow-for-automated-agent-workflow-optimization 。
[^28^]: MetaGPT issues：#1706 "Aflow 运行报错… Unable to serialize unknown type: numpy.int64"（2025-02-20）https://github.com/geekan/MetaGPT/issues/1706 ；#1597 "object list can't be used in 'await' expression"（2024-12-29）https://github.com/geekan/MetaGPT/issues/1597 ；#1673 "No module named 'metagpt.ext.aflow.scripts.optimized.MATH.workflows.round_8'"（2025-01-20）https://github.com/geekan/MetaGPT/issues/1673 。
[^29^]: arXiv:2404.02319 "Prompts As Programs (SAMMO)", https://arxiv.org/html/2404.02319v1 （2024-04-02）。摘录："Sammo carries out a genetic search over a set of mutation operators… gains of 10-100% in instruction tuning, 26-133% in RAG tuning, and over 40% in prompt compression… complex prompts need to be optimized separately for each LLM… Code at https://github.com/microsoft/sammo under an MIT license"。
[^30^]: 53AI/微信《微软最新的结构化Prompt优化方法SAMMO》https://mp.weixin.qq.com/s/ibgpbqKXVdR-0h11fnYVrA （2024-04-17）。摘录："SAMMO定义了一系列结构感知的变异算子：节点级别的变换如重排、替换、删除节点；节点参数的变换如修改指令文本；图结构层面的变换…采用遗传算法或者beam search"。
[^31^]: 推断：SAMMO 与 Trace 均为 Microsoft 同方向项目，SAMMO 2025-06 停更而 Trace 2025-08 停更；微软官方未发声明，标注为推断。
[^32^]: arXiv:2310.16427 "PromptAgent", https://arxiv.org/abs/2310.16427 （2023-10-25）。摘录："views prompt optimization as a strategic planning problem and employs a principled planning algorithm, rooted in Monte Carlo tree search… Code and demo: https://github.com/XinyuanWangCS/PromptAgent"。
[^33^]: alphaXiv PromptAgent 摘要 https://www.alphaxiv.org/abs/2310.16427 （2023-12-07）及 ar5iv 原文 https://ar5iv.labs.arxiv.org/html/2310.16427 。摘录："BBH: 0.802 vs CoT 0.707 and APE 0.690… Domain-specific: +7.3% over APE"；"we only need to optimize each task once"；"less advanced and smaller LLMs… may not adeptly grasp the subtleties of these expert-level prompts, potentially causing significant performance drop"。
[^34^]: AgentOpt/OpenTrace README（同 microsoft/Trace QuickStart）, https://github.com/AgentOpt/OpenTrace （2025-05-01）与 https://github.com/microsoft/Trace 。摘录："from opto.optimizers import OptoPrime… optimizer.zero_feedback(); optimizer.backward(correctness, feedback); optimizer.step()… @trace.model / trace.node(trainable=True) / @trace.bundle(trainable=True)"。
[^35^]: arXiv:2406.16218 "Trace is the New AutoDiff", https://arxiv.org/html/2406.16218v1 （2024-06-23）。摘录："Optimization of computational workflows often involves rich feedback… heterogeneous parameters (e.g. prompts, hyper-parameters, codes)… We frame a new mathematical setup… Optimization with Trace Oracle (OPTO)… OptoPrime is capable of first-order numerical optimization, prompt optimization, hyper-parameter tuning, robot controller design, code debugging"。
[^36^]: EvoAgentX 仓库 README, https://github.com/EvoAgentX/EvoAgentX （2026-06-07 快照）。摘录："Self-Evolution Engine… Agents don't just work—they learn… Plug-and-Play Compatibility… LiteLLM… [July 2025] 1,000 Stars Reached"；License MIT 见 SourceForge 镜像 v0.1.0 release notes。
[^37^]: promptolution 仓库 README, https://github.com/gepromptet/promptolution 。摘录："a unified, modular framework for prompt optimization… Implementation of many current prompt optimizers out of the box… Unified LLM backend supporting API-based models, Local LLMs, and vLLM clusters… CAPO: Cost-Aware Prompt Optimization (AutoML 2025)"。
[^38^]: Eladlev/AutoPrompt README, https://github.com/Eladlev/AutoPrompt 。摘录："Using GPT-4 Turbo, this optimization typically completes in just a few minutes at a cost of under $1… integrates seamlessly with LangChain, Wandb, and Argilla"。
[^39^]: SalesforceAIResearch/promptomatix README, https://github.com/salesforceairesearch/promptomatix （2025-07-08）。摘录："The framework leverages the power of DSPy and advanced optimization techniques… Zero-Configuration Intelligence… Automated Dataset Generation… CLI and API Interfaces"。
[^40^]: zhouhao1024/Awesome-Self-Evolving-Coding-Agents, https://github.com/zhouhao1024/Awesome-Self-Evolving-Coding-Agents （2026-08-04）。System Optimization 一节列举：AFlow (ICLR'25)、GEPA (ICLR'26)、A²Flow (AAAI'26)、FlowBot (ICML'26)、JudgeFlow、AgentEvo、MaAS (ICML'25)、EvoAgentX (EMNLP'25 Demos) 等。

---

### 检索记录
共执行 27 次独立检索（中英混合），覆盖：DSPy GEPA/MIPROv2 官方文档与 release、TextGrad/OPRO/AFlow/SAMMO/PromptAgent/Trace 论文与仓库、GEPA 独立库与 FAQ、中文社区解读（知乎/CSDN/微信/百度千帆/腾讯云）、MetaGPT aflow 使用 issue、prompt 优化成本对比研究、EvoAgentX/promptolution/AutoPrompt/Promptomatix 等补充方案。GitHub API 受限流，stars 与提交时间改用 HTML/atom feed 抓取（2026-08-20）。
**未查到项**：AFlow 优化阶段官方总成本数字、PromptAgent 精确 LLM 调用数、SAMMO 官方成本基准、TextGrad 与 LangChain 的官方集成、DSPy 社区系统性负面评测（reddit/博客争议检索返回 0 结果，局限性以文档与第三方研究佐证）。

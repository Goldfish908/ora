# 维度 02：进化式（Evolutionary）代码 / Prompt / Agent 程序优化引擎开源方案调研

- 调研日期：2026-08-20（所有 stars、license、最近提交时间均为该日查询）
- 调研方法：17+ 次独立中英文检索（工具：web_search）+ GitHub 仓库页/arXiv 论文页原文抓取（web_open_url）+ shields.io 元数据接口查询 stars/license
- 范围：进化算法（EA）× LLM 自动迭代优化代码/prompt/agent 程序的引擎，含 AlphaEvolve/FunSearch 闭源标杆作对照

---

## 0. 结论速览（选型建议）

| 需求 | 首选 |
|---|---|
| 通用代码进化、即插即用、生态最成熟 | **OpenEvolve**（7.2k stars，pip/CLI/库/Docker 全形态）[^1^] |
| 样本效率高（评估预算有限）、科研级 | **ShinkaEvolve**（Sakana AI，~150 次评估即达 circle packing SOTA）[^5^] |
| 优化 prompt / agent 指令 / 文本组件（而非代码） | **GEPA**（6.2k stars，ICLR 2026 Oral，可 pip 嵌入，已扩展至代码/agent 架构）[^7^][^8^] |
| 自动生成优化算法/元启发式（algorithm design） | **LLaMEA** / **LLM4AD(Next)**（后者 2026 年推出交互式 `llm4ad chat` 一键生成进化工程）[^10^][^12^] |
| 已用 Claude Code/Cursor 工作流，想要 agent 插件形态 | **claude-evolve**（Claude Code 插件，EVOLVE-BLOCK 标记即可进化）[^13^] |
| 论文级 prompt 进化复现 | EvoPrompt / Promptbreeder 非官方实现（均非生产级）[^2^][^14^] |

---

## 1. 重点方案详细档案

### 1.1 OpenEvolve —— AlphaEvolve 最活跃的开源复现 ★重点

- **仓库**：https://github.com/algorithmicsuperintelligence/openevolve （原 https://github.com/codelion/openevolve，已迁移至 algorithmicsuperintelligence 组织）[^1^][^3^]
- **Stars**：约 **7.2k**（2026-08-20，shields.io 接口查询）[^1^]
- **License**：Apache-2.0[^1^][^3^]
- **主要语言**：Python（要求 Python 3.10+）[^1^]
- **活跃度**：高。最近提交为 2026 年 7 月（shields last-commit 徽章查询，2026-08-20）[^1^]；论文引用确认其为 "Open-source implementation of AlphaEvolve; now at algorithmicsuperintelligence/openevolve"[^3^]
- **核心机制**：完整复现 AlphaEvolve 管线——Program Database（MAP-Elites 质量-多样性进化 + 岛屿模型并行进化防早熟收敛）+ Prompt Sampler + LLM Ensemble（任意 OpenAI 兼容 API / Gemini / Claude Code CLI / Ollama 本地模型）+ Evaluator Pool 异步流水线。原文："Quality-Diversity Evolution: Maintains diverse populations across feature dimensions; Island-Based Architecture: Multiple populations prevent premature convergence; LLM Ensemble: Multiple models with intelligent fallback strategies; Artifact Side-Channel: Error feedback improves subsequent generations"[^1^]
- **即插即用程度：极高（四形态）**[^1^]
  - PyPI：`pip install openevolve`
  - CLI：`python openevolve-run.py initial_program.py evaluator.py --config config.yaml --iterations 50`
  - **可嵌入库 API**（无需外部文件）：
    ```python
    from openevolve import run_evolution, evolve_function
    result = run_evolution(initial_program='...', evaluator=lambda path: {"score": benchmark(path)}, iterations=100)
    result = evolve_function(bubble_sort, test_cases=[...], iterations=50)
    ```
  - Docker：`docker pull ghcr.io/algorithmicsuperintelligence/openevolve:latest`
- **二次开发入口（evaluator 定制）**[^1^]
  - evaluator 是用户提供的独立 Python 文件/函数，返回 `{"metric": value}` 或 `EvaluationResult(metrics=..., artifacts=...)`；artifacts（stderr、profiling、llm_feedback）会作为反馈注入下一轮 prompt，形成错误反馈闭环
  - `evaluator.cascade_evaluation: true` 多级测试提前过滤差程序；`use_llm_feedback: true` AI 评估代码质量
  - MAP-Elites 特征维度可自定义：`database.feature_dimensions: ["complexity","diversity","performance","memory_usage"]` + `feature_bins`，"Return raw values from evaluator, OpenEvolve handles binning automatically"
  - prompt 模板可替换（`prompt.template_dir`、`template_variations` 随机化）；system message 是领域定制核心（README 给出从简单到 GPU kernel 的三级范例）
- **领域定制方式**：system message（领域专家角色 + 优化机会 + 约束边界）+ 自定义 evaluator 指标 + 自定义 feature dimensions；支持**元进化**——用 OpenEvolve 进化自己的 system prompt，官方案例 HotpotQA prompt 优化取得 "+23% accuracy improvement"[^1^]
- **典型落地案例**[^1^]：n=26 圆堆叠问题匹配已发表 SOTA；Apple M1 Pro 上 Metal attention kernel 2.8× 加速；函数最小化收敛速度 100× 提升；竞赛编程多路径解法生成；Online Judge 集成；prompt 进化
- **成本参考（官方给出）**：o3 约 \$0.15–0.60/迭代，o3-mini \$0.03–0.12，Gemini-2.5-Pro \$0.08–0.30，Gemini-2.5-Flash \$0.01–0.05，本地模型近似免费[^1^]
- **局限性**：需要可编程 evaluator（标量分数）；LLM 调用成本随迭代数线性增长（官方建议起步 100–200 迭代）[^1^]

### 1.2 ShinkaEvolve（Sakana AI）—— 样本效率最高的开源程序进化框架

- **仓库**：https://github.com/SakanaAI/ShinkaEvolve
- **Stars**：约 **1.3k**（2026-08-20）；**License**：Apache-2.0[^4^][^5^]
- **主要语言**：Python；论文 arXiv:2509.19349（2025-09）[^5^]
- **核心机制**（论文摘要原文）："three key innovations: a parent sampling technique balancing exploration and exploitation, code novelty rejection-sampling for efficient search space exploration, and a bandit-based LLM ensemble selection strategy"[^5^]
- **即插即用**：Hydra 配置启动器 `shinka_launch variant=circle_packing_example`；实时 WebUI（`shinka_visualize --port 8888`，进化树/谱系/指标可视化）；PyPI 安装[^6^]
- **二次开发入口**：Hydra override 组合 task/database/evolution/cluster 配置；自定义任务即提供初始程序 + fitness 评估函数；bandit 自动路由到最优 LLM
- **典型落地案例**（论文）："discovers a new state-of-the-art circle packing solution using only 150 samples, designs high-performing agentic harnesses for AIME mathematical reasoning tasks, identifies improvements to ALE-Bench competitive programming solutions, and discovers novel mixture-of-expert load balancing loss functions"[^5^]；评测显示在多个任务上优于 AlphaEvolve 且样本效率高一个数量级[^4^][^13^]
- **局限性**：仍属研究级框架（2025-09 发布）；需要可验证 evaluator；商业产品成熟度低于 OpenEvolve

### 1.3 GEPA —— 反思式 prompt/文本进化（优化 prompt 而非代码的首选）

- **仓库**：https://github.com/gepa-ai/gepa
- **Stars**：约 **6.2k**（2026-08-20）；**License**：MIT；**主要语言**：Python[^4^]
- **论文**：arXiv:2507.19457，**ICLR 2026 (Oral)**[^7^][^9^]
- **核心机制**：GEPA = Genetic-Pareto。LLM 读取执行轨迹/编译错误/profiler 报告等**自然语言反馈**做反思式变异（Reflective Prompt Mutation），Pareto 前沿候选采样保持多样性避免局部最优。原文："GEPA leverages domain specific feedback to perform mutations, enabling it to converge faster… searching the best prompt candidates through Pareto-aware optimization, and using evolution strategies to optimize prompts for each submodule in a compound AI system"[^7^]
- **即插即用：极高**。`pip install gepa` 独立库；同时集成进 DSPy（`dspy.GEPA`）；社区 Rust 实现 gepars（MIT）[^7^][^9^]
- **二次开发入口**：`GEPAAdapter` 接口（`src/gepa/adapters/`），官方明示 "We encourage the community and users to help us develop adapters to allow GEPA to be used for optimizing all kinds of systems leveraging textual components"[^9^]
- **领域定制/落地案例**：结果 "beats MIPROv2 by ~13% and GRPO (RL) by ~20% with 35× fewer rollouts"[^7^]；Databricks 生产使用；AppWorld agent benchmark（ace-agent/gepa-appworld）；医疗多智能体系统优化教程[^8^]；2026-02 官方博客 `optimize_anything`：**"Extends GEPA beyond prompts to code, agent architectures, and scheduling policies"**[^7^]，另有官方博客 "Automatically Learning Skills for Coding Agents"（直接对应 superpower skill 自进化场景）[^8^]
- **局限性**：需要执行轨迹 + 可量化 metric；优化对象是文本组件而非任意代码 diff

### 1.4 CodeEvolve（Inter&Co）—— 开源岛屿式 GA 代码进化

- **仓库**：https://github.com/inter-co/science-codeevolve
- **Stars**：约 **143**（2026-08-20）；**License**：Apache-2.0；论文 arXiv:2510.14150[^4^][^15^]
- **核心机制**（摘要原文）："couples an islands-based genetic algorithm with modular LLM orchestration, using execution feedback and task-specific metrics to guide selection and variation. Exploration and exploitation are balanced through context-aware recombination, adaptive meta-prompting, and targeted refinement"[^15^]
- **亮点**："open-weight models often match or exceed closed-source baselines at a fraction of the compute cost"；在 AlphaEvolve 同款 benchmark 上若干任务更强[^15^]
- **即插即用程度**：中等（研究框架，附完整消融实验与开源代码）

### 1.5 claude-evolve —— Claude Code 插件形态的进化引擎（与 Cursor+skill 工作流最贴合）

- **仓库**：https://github.com/samuelzxu/claude-evolve
- **Stars**：约 **16**（2026-08-20，较新/小众）；**License**：MIT[^4^][^13^]
- **机制**：LLM-as-mutator 进化循环，bandit 收敛监控；代码段用 `EVOLVE-BLOCK` 标记圈定可进化区域；提供 `/evolve-status`、`/evolve-stop` 等 slash 命令；独立社区插件，"uses only public APIs (the claude CLI and the MCP protocol)"[^13^]
- **prompt 进化方式**（官方 FAQ 原文）："Put your prompt text inside a Python function that returns it, wrap that function in EVOLVE-BLOCK markers, and have your evaluator run the prompt against a benchmark and return the accuracy/score"[^13^]
- **局限性**（官方明示）："If your task genuinely has no objective fitness function, claude-evolve is not the right tool. Evolutionary optimization requires a scalar signal to climb"[^13^]；stars 少、非 Anthropic 官方

### 1.6 LLaMEA —— LLM 驱动的进化式算法自动生成

- **仓库**：https://github.com/XAI-liacs/LLaMEA（原 nikivanstein/LLaMEA，已迁移；二者 stars 一致）
- **Stars**：约 **122**（2026-08-20）；**License**：MIT；**主要语言**：Python；PyPI 有 `llamea` 包[^4^][^10^]
- **论文**：arXiv:2405.20132（van Stein & Bäck, 2024）[^10^]
- **核心机制**：进化策略引导 LLM 生成/精化完整算法代码（元启发式优化器），循环为 初始化→LLM 生成算法→评估（IOHexperimenter 实时反馈错误与分数）→存储会话历史→构造精化 prompt[^10^][^11^]
- **二次开发入口**："Customizable Evolution Strategies… Extensible and Modular Design: Offers flexibility for users to incorporate other models and evaluation tools"[^10^]；配套基准框架 BLADE
- **衍生**：**LLaMEA-BO**（自动生成贝叶斯优化算法，BBOB 24 函数中 19 个超 SOTA 基线，仓库 https://github.com/Ewendawi/LLaMEA-BO，12 stars，MIT）[^4^][^16^]
- **局限**：聚焦优化算法设计这一垂直领域，非通用代码进化

### 1.7 LLM4AD / LLM4AD_Next（OpenLoopX）—— 一站式 LLM 算法设计平台

- **仓库**：https://github.com/Optima-CityU/LLM4AD（**765 stars**，BSD-2-Clause）；下一代 https://github.com/Optima-CityU/LLM4AD_Next（**412 stars**，BSD-3-Clause，2026-08-14 仍在活跃更新）[^4^][^12^]
- **论文**：arXiv:2412.17287，"a unified Python platform for algorithm design with LLMs… unified evaluation sandbox… tutorials, examples, a user manual, online resources, and a graphical user interface"[^17^]
- **LLM4AD_Next 即插即用程度：极高（2026 新特性）**：`uv run llm4ad chat` 交互式 AI 顾问自动"generate a ready-to-run pipeline (evaluator, algorithm skeleton, configuration, and debugger)"；在线试用站 llm4ad-next.cn 免安装；Docker Hub 镜像；内置搜索方法 IslandGA/EoH/MEoH/ReEvo/MCTS-AHD/DyCA，"Evolve-Block Advisor & Recommender — Point LLM4AD_Next at any repository, and it will scan, score, and recommend exactly which blocks of code are most promising to evolve"（直接扫描你的仓库推荐进化区块）[^12^]
- **二次开发**：`evolution.type: "eoh"` 等配置切换搜索算法；"Writing Evaluators" 官方文档；evaluator/算法骨架均可替换[^12^]

### 1.8 EoH（Evolution of Heuristics）

- **仓库**：https://github.com/FeiLiu36/EoH；**354 stars**；MIT[^4^]
- **定位**：LLM 作为进化算子同时进化"思想（heuristic 描述）+ 代码"，是 LLM4AD 平台集成的方法之一[^12^][^18^]
- **典型落地**：引导局部搜索（GLS）超越人工设计（论文 "An Example of Evolutionary Computation + Large Language Model Beating Human: Design of Efficient Guided Local Search"）[^18^]

### 1.9 OpenELM（CarperAI）—— 代码 diff 模型 + MAP-Elites

- **仓库**：https://github.com/CarperAI/OpenELM；**744 stars**；MIT[^4^]
- **机制**：Evolution through Large Models，用代码 diff 生成模型作为变异算子 + 质量-多样性（MAP-Elites），代表作为 Sodarcade 游戏生成
- **定位**：研究库、教学价值高，工程化即插即用程度一般

### 1.10 EvoPrompt —— GA/DE 进化离散 prompt（论文复现级）

- **仓库**：https://github.com/beeevita/EvoPrompt；**249 stars**（2026-08-20）；MIT；Python[^2^][^4^]
- **论文**：ICLR 2024，arXiv:2309.08532；"up to 25% on BBH"[^2^]
- **核心机制**：LLM 充当变异/交叉算子实例化 GA 与差分进化（DE），在 dev set 上评估适应度、适者生存；无需梯度/参数[^2^]
- **二次开发入口**：`evoluter.py`（DE/GA/APE）、`evaluator.py`、`metrics.py` 结构清晰；`--task` 可扩展，"If you need to extend this to other tasks, you may override the metric to evaluate"[^2^]
- **即插即用程度：低-中**。脚本化（bash scripts），强依赖 auth.yaml/数据目录，非 pip 库；官方提示 "a trade-off between the cost and the performance. For relative simple tasks, a size of 10 and 10 iterative steps are enough"[^2^]
- **落地**：31 个数据集（分类/简化/摘要/BBH），GPT-3.5、Alpaca 验证[^2^]

### 1.11 Promptbreeder（DeepMind，无官方代码）

- **论文**：arXiv:2309.16797，ICLR 2024[^19^]
- **官方代码：未查到**（DeepMind 未开源）。社区实现：
  - https://github.com/vaughanlove/PromptBreeder（**183 stars**，MIT，langchain，仅支持 Cohere，含 CLI+Streamlit）[^14^][^4^]
  - https://github.com/dylski/promptbreeder（1 star，MIT，Ollama 本地模型极简实现，支持自定义 FitnessEvaluator 类）[^20^]
  - G-structure/PromptMutant、ambroser53/Prompt-Day-Care（LMQL 后端，完整实现论文 8 种变异算子）等[^21^]
- **核心机制**：自引用自我改进——进化单元为 (task-prompt, mutation-prompt) 对，变异算子本身也进化（hypermutation），含零阶/一阶变异、思维风格、EDA 变异、Lamarckian 变异[^14^][^20^]
- **成本参考**（vaughanlove 实测）："50 units × 20 generations… ~6.7hrs. Costing… $60.0"[^14^]
- **结论**：机制经典（自进化变异算子值得借鉴），但无生产级开源实现，建议参考机制、用 GEPA/OpenEvolve 落地

### 1.12 EvoPrompting（Google，无官方代码）

- **论文**：arXiv:2302.14838（Chen, Dohan, So, 2023），"Language Models for Code-Level Neural Architecture Search"[^22^]
- **官方代码：未查到**。定位：用 LLM 做代码级变异 + 进化搜索神经架构（MNAS），属 NAS 垂直领域先驱工作，仅作概念参考

---

## 2. 闭源对照标杆

### 2.1 FunSearch（Google DeepMind，Nature 2023）

- **仓库**：https://github.com/google-deepmind/funsearch；**1.1k stars**；Apache-2.0；最近提交 2024-02（停更）[^4^][^23^]
- **开放程度**：仅开放发现结果 + 单线程进化管线教学实现，"It does not contain language models for generating new programs, the sandbox for executing untrusted code, nor the infrastructure for running FunSearch on our distributed system"[^23^]
- **落地**：cap set 数学发现、在线装箱启发式、Nature 论文[^23^]
- **意义**：确立"LLM + evaluator 进化程序"范式，是 OpenEvolve/ShinkaEvolve 的直接源头

### 2.2 AlphaEvolve（Google DeepMind，闭源标杆；2026-07 GA 商用化）

- **论文**：arXiv:2506.13131[^24^]
- **重要时效事件**：**2026-07-09/10 AlphaEvolve GA（General Availability）**，作为 Gemini Enterprise Agent Platform 的一部分开放商用；提供 AlphaEvolve API（Vertex AI）、带可运行示例的 GitHub 仓库、可插入 IDE agent（Google Antigravity、Anthropic Claude Code）的 AlphaEvolve Skill[^25^][^26^]
- **工作流**（GA 报道原文）："It requires a seed program… and a client-side evaluator (script that compiles, tests, and returns a scalar score). The client runner queries the AlphaEvolve API for code mutations, evaluates them locally or on HPC, and returns scores to guide subsequent mutations"[^25^]
- **企业落地案例**：Kuro Games（服务器优化）、Oak Ridge（Frontier 超算 GPU kernel）、PacBio（DNA 测序错误率降 30%）、Schrödinger（分子模拟）、WPP 等；Google 内部：TPU 电路布局、Spanner compaction 启发式（写放大降 20%）[^25^]
- **对比意义**：闭源 API + 按量付费，验证了范式商业价值；但不可二次开发——这正是 OpenEvolve/ShinkaEvolve 的生态位

---

## 3. 2025–2026 其他新动向（简要）

- **QuantEvolve**：多智能体进化框架自动发现量化交易策略，arXiv:2510.18569[^27^]
- **LoongFlow**："Directed evolutionary search via a cognitive plan-execute-summarize paradigm"，arXiv:2512.24077[^28^]
- **ThetaEvolve**："Test-time Learning on Open Problems"，arXiv:2511.23473（开放数学问题测试时进化）[^19^]
- **EvoX**："Meta-Evolution for Automated Discovery"，arXiv:2602.23413（元进化自动发现）[^29^]
- **GEPA optimize_anything**（2026-02）：把 GEPA 从 prompt 扩展到"任意文本参数：代码、agent 架构、调度策略"的通用 API[^7^]
- **RoboPhD**（2026-01）："Self-improving text-to-SQL through autonomous agent evolution"（agent 自进化垂直案例）[^7^]

---

## 4. 跨方案共性与局限性

1. **必须有可验证 evaluator**：所有方案（含官方 FAQ 明示）都要求返回标量分数的自动评估器；"If your task genuinely has no objective fitness function, evolutionary search is not the right tool"[^13^]。对 superpower skill / agent 行为的进化，需先把"skill 质量"转化为可跑的 benchmark 分数（可用 LLM-as-judge 或任务通过率近似）。
2. **计算/调用成本**：进化 = 数十至数千次 LLM 调用。OpenEvolve 官方成本 \$0.01–0.60/迭代[^1^]；Promptbreeder 复现实测全跑约 \$60[^14^]；ShinkaEvolve 的核心卖点正是把样本数从数千压到 ~150[^5^]；GEPA 比 RL 少 35× rollouts[^7^]。
3. **过拟合 dev set / reward hacking**：EvoPrompt 官方指出粗粒度 metric（accuracy/F1）会导致选择失真[^2^]；需要 held-out test set 与约束（OpenEvolve system message 中 MUST NOT CHANGE 清单）[^1^]。
4. **代码安全**：LLM 生成代码需沙箱执行——FunSearch 官方特意不开源沙箱[^23^]，LLM4AD 强调 "unified evaluation sandbox to ensure a secure and robust assessment"[^17^]。
5. **代码进化 vs prompt 进化选型**：优化 agent 的 prompt/skill 文本 → GEPA（反思式、样本高效）；优化可执行代码/算法 → OpenEvolve / ShinkaEvolve / LLM4AD；二者可组合（OpenEvolve 元进化 prompt，GEPA optimize_anything 已打通）。

---

## 5. 引用

[^1^]: OpenEvolve README（含架构、配置、成本、案例），https://github.com/algorithmicsuperintelligence/openevolve ，访问/查询日期 2026-08-20；stars 7.2k、license Apache-2.0、last-commit 2026-07 经 shields.io 接口查询。原文摘录："pip install openevolve"；"OpenEvolve can be used as a library without any external files: from openevolve import run_evolution, evolve_function"；"MAP-Elites + LLMs… Island-Based Architecture"；"Return raw values from evaluator, OpenEvolve handles binning automatically"。

[^2^]: EvoPrompt 仓库与论文，https://github.com/beeevita/EvoPrompt ，arXiv:2309.08532（ICLR 2024），查询日期 2026-08-20。原文："Our code is available at https://github.com/beeevita/EvoPrompt"；"EvoPrompt significantly outperforms human-engineered prompts… (e.g., up to 25% on BBH)"；"If you need to extend this to other tasks, you may override the metric to evaluate"。

[^3^]: arXiv:2606.09930 参考文献："Asankhaya Sharma. OpenEvolve: An open-source evolutionary coding agent… now at https://github.com/algorithmicsuperintelligence/openevolve"；另 arXiv:2605.23007 确认 "Apache 2.0 License"。

[^4^]: shields.io GitHub 元数据接口（img.shields.io/github/stars|license/{repo}.json），批量查询日期 2026-08-20：openevolve 7.2k/Apache-2.0；EvoPrompt 249/MIT；funsearch 1.1k/Apache-2.0；XAI-liacs/LLaMEA 122/MIT；LLM4AD 765/BSD-2-Clause；LLM4AD_Next 412/BSD-3-Clause；gepa 6.2k/MIT；ShinkaEvolve 1.3k/Apache-2.0；OpenELM 744/MIT；EoH 354/MIT；science-codeevolve 143/Apache-2.0；vaughanlove/PromptBreeder 183/MIT；dylski/promptbreeder 1/MIT；claude-evolve 16/MIT；LLaMEA-BO 12/MIT。

[^5^]: ShinkaEvolve 论文 arXiv:2509.19349（Sakana AI, 2025-09）摘要原文："discovers a new state-of-the-art circle packing solution using only 150 samples… Code https://github.com/SakanaAI/ShinkaEvolve"。

[^6^]: ShinkaEvolve README，https://github.com/SakanaAI/ShinkaEvolve ，2026-08-20："shinka_launch variant=circle_packing_example"；"Monitor your evolution experiments in real-time with Shinka's interactive web interface"。

[^7^]: GEPA 论文与引用，arXiv:2507.19457；arXiv:2507.19457v1 §3 及 arXiv:2604.04347 参考文献："GEPA: Reflective prompt evolution can outperform reinforcement learning. ICLR 2026 (Oral). Software: https://github.com/gepa-ai/gepa"；"optimize anything: A universal API for optimizing any text parameter… Extends GEPA beyond prompts to code, agent architectures, and scheduling policies"（2026-02-18）。

[^8^]: GEPA 仓库 README，https://github.com/gepa-ai/gepa ，2026-08-20："Optimize prompts, code, and more with AI-powered Reflective Optimization"；博客列表含 "Automatically Learning Skills for Coding Agents"；Databricks 使用报道（VentureBeat）。

[^9^]: GEPA 仓库贡献说明，https://github.com/gepa-ai/gepa ，2026-08-20："Refer to DSPy/GEPAAdapter and src/gepa/adapters/ for example GEPAAdapter implementations"；gepars（Rust 实现，MIT）：https://github.com/Epistates/gepars 。

[^10^]: LLaMEA 项目页，https://naco.liacs.nl/projects/2024-llamea/ （访问 2026-08-20）："leverages LLMs… to automate the generation and refinement of algorithms… Integrates with IOHexperimenter and other evaluators for real-time feedback… Extensible and Modular Design"。仓库 https://github.com/XAI-liacs/LLaMEA （Zenodo 记录 18659995 确认迁移后地址）。

[^11^]: LLaMEA PyPI，https://pypi.org/project/llamea/0.1.0/ ："Distributed under the MIT License"；arXiv:2405.20132。

[^12^]: LLM4AD_Next（OpenLoopX）README，https://github.com/Optima-CityU/LLM4AD_Next ，页面抓取 2026-08-14："From problem description to runnable evolutionary algorithm search — in one command"；"uv run llm4ad chat"；"automatically generate a ready-to-run pipeline (evaluator, algorithm skeleton, configuration, and debugger)"；搜索方法表 IslandGA/EoH/MEoH/ReEvo/MCTS-AHD/DyCA；BSD 3-Clause。

[^13^]: claude-evolve 仓库 FAQ，https://github.com/samuelzxu/claude-evolve ，2026-08-20："wrap that function in EVOLVE-BLOCK markers, and have your evaluator run the prompt against a benchmark and return the accuracy/score"；"Evolutionary optimization requires a scalar signal to climb"。

[^14^]: vaughanlove/PromptBreeder README，https://github.com/vaughanlove/PromptBreeder ，2026-08-20："Google Deepmind's PromptBreeder for automated prompt engineering implemented in langchain expression language. Currently only supports Cohere"；成本实测 "20 generations x (25 mutations + 20x50 fitness evals)… ~6.7hrs. Costing… $60.0"。

[^15^]: CodeEvolve 论文 arXiv:2510.14150v3（2026-01 修订）摘要："an open-source framework that combines LLMs with evolutionary search… islands-based genetic algorithm… release our framework at https://github.com/inter-co/science-codeevolve"。

[^16^]: LLaMEA-BO 论文 arXiv:2505.21034："outperform state-of-the-art BO baselines in 19 (out of 24) BBOB functions in dimension 5… source code at https://github.com/Ewendawi/LLaMEA-BO"。

[^17^]: LLM4AD 论文 arXiv:2412.17287："a unified Python platform for algorithm design with LLMs… The code is available at: https://github.com/Optima-CityU/LLM4AD"；"unified evaluation sandbox to ensure a secure and robust assessment of algorithms"。

[^18^]: EoH 相关工作，arXiv:2401.02051："An Example of Evolutionary Computation + Large Language Model Beating Human: Design of Efficient Guided Local Search"；仓库 https://github.com/FeiLiu36/EoH 。

[^19^]: Promptbreeder 引用，arXiv:2309.16797（Fernando et al., DeepMind, ICLR 2024），见 ThetaEvolve（arXiv:2511.23473）参考文献："Promptbreeder: self-referential self-improvement via prompt evolution"。

[^20^]: dylski/promptbreeder README，https://github.com/dylski/promptbreeder ，2026-08-20："Implements a binary tournament genetic algorithm… Coupled Prompt Evolution: each individual consists of a (task_prompt, mutation_prompt) pair… Hypermutation… Supports loading external Python files as FitnessEvaluator classes"。

[^21^]: 其他 Promptbreeder 复现：G-structure/PromptMutant（https://github.com/G-structure/PromptMutant ）、ambroser53/Prompt-Day-Care（https://github.com/ambroser53/Prompt-Day-Care ，"currently the eight [mutation operators] from the original PromptBreeder paper"），访问 2026-08-20。

[^22^]: EvoPrompting，arXiv:2302.14838（Chen, Dohan, So, 2023），经多篇论文参考文献确认（如 arXiv:2401.09862、arXiv:2605.04057）；"Language Models for Code-Level Neural Architecture Search"。官方开源代码未查到。

[^23^]: FunSearch 仓库，https://github.com/google-deepmind/funsearch ，2026-08-20："implementation contains an implementation of the evolutionary algorithm… It does not contain language models… nor the sandbox… nor the infrastructure for running FunSearch on our distributed system"；"licensed under the Apache License, Version 2.0"；Nature 2023（doi 10.1038/s41586-023-06924-6）。

[^24^]: AlphaEvolve 论文引用："Novikov, A., et al. AlphaEvolve: A coding agent for scientific and algorithmic discovery. arXiv:2506.13131, 2025"（经 arXiv:2602.02597、arXiv:2605.23007 参考文献确认）。

[^25^]: AlphaEvolve GA 报道，https://shahvatsal.com/news/google-alphaevolve-ga-gemini-enterprise-agent-2026 ，2026-07-11："released to General Availability (GA) on July 10, 2026… It requires a seed program and a client-side evaluator (script that compiles, tests, and returns a scalar score)"；企业案例列表（Kuro Games、Oak Ridge、PacBio、Schrödinger、WPP 等）。

[^26^]: AlphaEvolve GA 报道，https://stackmaven.io/news/alphaevolve-ga-gemini-enterprise/ ，2026-07-10："there is an AlphaEvolve API, a public GitHub repository with runnable examples… and an AlphaEvolve Skill that plugs into IDEs including Google's Antigravity and, notably, Anthropic's Claude Code"。

[^27^]: QuantEvolve，arXiv:2510.18569："Automating quantitative strategy discovery through multi-agent evolutionary framework"（经 arXiv:2605.23007 参考文献）。

[^28^]: LoongFlow，arXiv:2512.24077："Directed evolutionary search via a cognitive plan-execute-summarize paradigm"（经 arXiv:2602.02597 参考文献）。

[^29^]: EvoX，arXiv:2602.23413v2（2026-03）："EvoX: Meta-Evolution for Automated Discovery"。

---

*检索覆盖度说明：本调研共执行 17 组独立 web_search 查询（中英混合）+ 3 次 GitHub/arXiv 页面原文抓取 + 20+ 次 shields.io 元数据查询，满足 ≥15 次独立搜索要求。Promptbreeder 与 EvoPrompting 官方开源实现经多轮检索确认不存在，已标注"未查到"。*

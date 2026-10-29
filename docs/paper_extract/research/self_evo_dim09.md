# 维度 09：权重级自进化（Weight-level Self-Evolution）开源方案调研

- **调研日期**：2026-08-20
- **调研方式**：28+ 次中英文独立搜索（Google/arXiv/GitHub/中文技术站）+ GitHub 页面直读 + shields.io 徽章接口核实 stars/license
- **背景问题**：用户在个人工程中用 Cursor + GPT + skill 管理工程，想加入 Agent 自进化模块。本维度评估"模型通过自训练/RL 更新权重实现自我进化"路线的代表工作及其对个人工程用户的可落地性。
- **stars/license 均为 2026-08-20 查询值**（GitHub REST API 因出口 IP 限流，改用 shields.io 实时徽章接口核实，页面快照交叉验证）。

---

## TL;DR 结论（先说结论）

1. **权重级自进化对普通工程用户：整体"了解即可、暂不落地"。** 所有代表方案（SEAL、Absolute Zero、R-Zero、Self-Rewarding、SWE-RL、TTRL）都已在开源仓库提供可运行代码，但最低门槛也要 **2 张 80GB 级 GPU**（SEAL 明确写 "All experiments can be run with 2 A100/H100 GPUs"[^816^]），主流是 4–8×A100/H100，SWE-RL 论文级复现用了 **512 张 H100**[^913^]。这超出典型个人开发者（1 张 24–48GB 消费卡）1–2 个数量级。
2. **与非权重路线（prompt/skill/记忆进化）的落地门槛差异是本质性的**：非权重进化只需 LLM API + 文件系统，零训练算力、零 ML 工程；权重级进化需要"推理引擎(vLLM/SGLang)+训练引擎(Megatron/FSDP/DeepSpeed)+RL 编排(Ray)"三层基础设施同时工作[^849^][^864^][^888^]，且奖励信号只在**可自动验证的领域**（数学/代码执行/单元测试）才便宜可靠。
3. **若坚持要碰权重级**，现实路径只有两条：(a) 用 **TRL**（19k stars）在单卡上对 ≤3B 小模型做 GRPO/在线 DPO + LoRA/QLoRA 的"轻量自奖励"实验[^943^][^950^]；(b) 用 **verl**（23k stars）或 **OpenRLHF**（9.9k stars）的自定义 reward/agent 接口，在租用的 4–8×A100 上复现 TTRL/AZR 类循环[^824^][^911^]。两条路径都不属于"嵌入 Cursor 工程即插即用"，而是独立的研究型项目。
4. 工程 Agent 领域（而非数学）真正对口的权重级工作是 **SWE-RL**，但其主仓库是 **CC BY-NC 4.0（禁止商用）**[^908^]，且训练依赖 70B 模型 + 数百卡，仅其奖励函数/Agentless Mini（MIT）有二次开发价值。

---

## 一、代表方法逐项评估

### 1. SEAL — Self-Adapting Language Models（MIT，NeurIPS 2025）

| 项目 | 内容 |
|---|---|
| 论文 | arXiv:2506.10943（2025-06-12，v2 2025-09-18）[^786^] |
| 仓库 | https://github.com/Continual-Intelligence/SEAL [^816^] |
| Stars | **1.8k**（2026-08-20，shields.io） |
| License | **MIT**（VentureBeat 报道 "open source code posted on Github (under an MIT License, allowing for commercial and enterprise usage)"[^1000^]；shields.io 同步确认） |

**核心机制**：模型自己生成"自我编辑"（self-edit）——重构新知识为训练数据、指定优化超参、调用数据增强工具；内环用 SFT 把 self-edit 写进权重实现持久化适应，外环用 RL（以更新后模型的下游表现为奖励）训练模型产出更好的 self-edit。"SEAL directly uses the model's generation to parameterize and control its own adaptation process"[^786^]。验证于知识注入与 few-shot 泛化两个域[^816^]。

**所需资源**：官方明确 "All experiments can be run with 2 A100/H100 GPUs. Other setups may require refactoring and/or changing model sizes"[^816^]；脚本面向 SLURM 集群；还需要 OpenAI API key 做数据/评测[^816^]。

**个人可落地性：低（偏中）**。理由：2×A100 是所有方案里门槛最低的之一，且 MIT 协议友好、代码就是给二次开发的研究代码；但它是研究原型而非产品框架——外环 RL 需要反复"训练→评测→打分"完整循环，单次实验即数百 GPU·时；要嵌入"工程 Agent 持续进化"需自行重写奖励（工程任务的下游表现难以自动打分），NeurIPS 版更新了双环结构与遗忘问题[^1000^]，仍属前沿研究。**定位：读懂思想（self-edit 作为进化的载体），暂不落地。**

### 2. Absolute Zero / Absolute Zero Reasoner（清华 LeapLab + BIGAI）

| 项目 | 内容 |
|---|---|
| 论文 | arXiv:2505.03335（2025-05-06）[^899^] |
| 仓库 | https://github.com/LeapLabTHU/Absolute-Zero-Reasoner [^911^] |
| Stars | **1.9k**（2026-08-20，shields.io） |
| License | **MIT**（2026-08-20，shields.io） |

**核心机制**：单一模型同时扮演 Proposer 与 Solver：提出演绎/溯因/归纳三类代码推理任务（用 Python 执行器验证任务合法并给"可学习性奖励"），再解这些任务（执行器验证答案给"正确性奖励"），用 TRR++ 做 RL，**零外部数据**自我对弈进化[^820^][^899^]。代码基于 veRL fork + vLLM rollout[^911^]。

**所需资源**：官方写明 "3b models need 2 X 80gb GPUs, 7/8b models need 4 X 80gb, 14b requires 8 X 80gb"[^911^]；还需要代码执行沙箱（README 警告 executor 不安全、仅限研究用途；后支持 Sandbox-Fusion）[^820^][^911^]。

**个人可落地性：低**。理由：(1) 4×80GB 起步；(2) 自我对弈闭环必须有一个**可验证环境**（Python 执行器），其奖励范式天然绑定代码/数学推理，迁到"工程管理/写作"等开放任务无现成验证器；(3) main 分支长期处于 "UNDER TESTING"，复现需用 paper 分支[^820^]。**定位：零数据自对弈的标杆思想，了解即可。**

### 3. R-Zero（Tencent AI Seattle Lab 等，ICLR 2026）

| 项目 | 内容 |
|---|---|
| 论文 | arXiv:2508.05004（2025-08-07，v4 2026-02）[^778^][^787^] |
| 仓库 | https://github.com/Chengsong-Huang/R-Zero [^931^] |
| Stars | **835**（2026-08-20，shields.io） |
| License | **未指定**（GitHub 未检测到 LICENSE 文件，shields.io "not specified"，2026-08-20）——二次开发/商用存在法律灰区 |

**核心机制**：从单个 base 模型初始化两个角色——Challenger（用 GRPO 训练、以"Solver 自洽性不确定度"为奖励，专挑 Solver 能力边缘出题）与 Solver（用 Challenger 出的题 + 多数投票伪标签做 GRPO），交替冻结、共同进化，形成无需任何人工数据的自进化循环[^778^]。Qwen3-4B-Base 三轮自进化数学平均分 +6.49，且迁移到 MMLU-Pro/SuperGPQA 等通用推理[^778^]。框架基于 EasyR1[^931^]。

**所需资源**："All our experiments were conducted on an 8-GPU server, using models that can run on single GPU (e.g., 4B or 8B)"[^931^]；另需 HF/WandB/OpenAI key（评测用 GPT）[^931^]。

**个人可落地性：低**。理由：8 卡服务器 + GRPO 双循环训练；迭代收益在 Iter 2–3 后趋缓（官方表格 Iter 2→3 基本饱和甚至回退）[^931^]；无 LICENSE。**定位：了解"自出题—自解答"课程自进化思想即可。**

### 4. Self-Rewarding Language Models（Meta + NYU，ICML 2024）

| 项目 | 内容 |
|---|---|
| 论文 | arXiv:2401.10020（2024-01-18，被引 1000+）[^930^][^1003^] |
| 官方仓库 | **未查到官方开源仓库**（arXiv HTML 全文无代码链接；候选官方路径均不存在，2026-08-20 核实）。知名非官方复现：lucidrains/self-rewarding-lm-pytorch，**1.4k stars，MIT**（2026-08-20，shields.io）；后续工作如 CREAM（ICLR 2025）https://github.com/Raibows/CREAM [^1001^] |
| License | 非官方复现为 MIT |

**核心机制**：模型通过 LLM-as-a-Judge 给自己的多个回答打分，构造偏好对，做迭代 DPO；指令遵循能力与自评分能力同时提升。Llama 2 70B 三轮迭代后 AlpacaEval 2.0 超过 Claude 2/Gemini Pro/GPT-4 0613[^930^]。

**所需资源**：论文实验为 **Llama 2 70B 全参数三轮 DPO 迭代**（每轮含批量采样+自评+训练）[^930^]——个人硬件不可行；小模型（7B 级）上收益数轮后衰减[^987^]。

**个人可落地性：低（机制本身可借鉴）**。理由：无官方代码、70B 级训练；"自评分→偏好对→DPO"的循环思想可以用 TRL 的 DPOTrainer + 7B/QLoRA 在小规模复刻（CREAM 证明 7B 可行但收益递减[^987^][^1001^]），属于实验性质。**定位：自奖励范式鼻祖，了解思想；若做实验走 TRL/CREAM 路线。**

### 5. SWE-RL（Meta FAIR，NeurIPS 2025）——工程领域最对口

| 项目 | 内容 |
|---|---|
| 论文 | arXiv:2502.18449（2025-02-25，v2 2025-12）[^897^] |
| 仓库 | https://github.com/facebookresearch/swe-rl [^908^] |
| Stars | **718**（2026-08-20，shields.io） |
| License | **主体 CC BY-NC 4.0（禁止商用）；Agentless Mini 子模块 MIT**[^908^] |

**核心机制**：用 GitHub PR 全生命周期数据（issue 描述+代码上下文+oracle patch，从 2400 万 PR 过滤出 27.3 万种子样本）做 RL；奖励是轻量规则——预测 patch 与真实 patch 的 `difflib.SequenceMatcher` 相似度（格式错误 -1），GRPO 优化[^896^][^913^]。Llama3-SWE-RL-70B 在 SWE-bench Verified 达 41.0%，且 RL 涌现出域外泛化（数学、代码推理、通用语言理解均提升）[^896^]。

**所需资源**：论文训练为 **512 张 H100、约 32 小时、1600 步**（70B 模型）[^913^]。

**个人可落地性：低（但二次开发点最明确）**。理由：(1) 算力差 2 个数量级；(2) 非商用协议；(3) 训练代码并不完整发布（"code currently provides our prompt templates and the implementation of the reward function"[^907^]），完整 RL pipeline 需自己接 verl/OpenRLHF。**有价值的可复用件**：(a) 奖励函数 `swerl.core.reward`（MIT 边界内可参考思路）；(b) Agentless Mini（MIT）修 bug pipeline，可直接接 vLLM/SGLang 端点在个人工程里跑[^906^]。**定位：思想（用软件演化数据+规则奖励做工程 RL）高度对口用户需求，但落地限于借鉴奖励设计与用 Agentless Mini，非权重自进化。**

### 6. TTRL — Test-Time Reinforcement Learning（清华 + 上海 AI Lab，NeurIPS 2025）

| 项目 | 内容 |
|---|---|
| 论文 | arXiv:2504.16084（2025-04-22，NeurIPS 2025）[^806^][^932^] |
| 仓库 | https://github.com/PRIME-RL/TTRL [^932^] |
| Stars | **1.1k**（2026-08-20，shields.io） |
| License | **MIT**（2026-08-20，shields.io） |

**核心机制**：对**无标签测试数据**做在线 RL：多次采样→多数投票得伪标签→以投票一致性构造奖励→GRPO 更新权重，"TTRL enables self-evolution of LLMs by utilizing the priors in the pre-trained models"[^805^]。Qwen2.5-Math-7B 在 AIME 2024 上 pass@1 提升约 211%（12.9→40.2）[^806^]。已集成进 verl："`+ttrl.enable=True`"[^932^]。

**所需资源**：官方实验 **8×A100 80GB**[^824^]；复现脚本基于 verl[^824^]。

**个人可落地性：低（但在本清单里相对最高）**。理由：MIT 协议、已并入 verl 一行开关、只需要无标签 prompt 流即可自进化——概念上最接近"用户工程里 Agent 边用边进化"；但仍需多卡训练环境、且奖励可靠性依赖任务存在"多数投票有效"的可判定答案（数学/代码），开放工程任务不适用；后续工作指出伪标签噪声会被放大[^810^]。**定位：若有 8 卡租用预算+可判分任务，是可复现的最简权重自进化方案；否则了解即可。**

---

## 二、支撑性开源训练框架（自进化训练的"铲子"）

这些不是自进化算法，但 SEAL/AZR/R-Zero/TTRL 全部构建于其上；也是个人想二开时的真实入口。

| 框架 | 仓库 | Stars（2026-08-20） | License | 自进化相关能力 | 个人可落地性 |
|---|---|---|---|---|---|
| **verl**（字节 Seed，EuroSys'25 HybridFlow） | https://github.com/verl-project/verl（2026/01 从 volcengine 迁入）[^849^] | **23k** | Apache-2.0 | PPO/GRPO/GSPO/DAPO/REINFORCE++/RLOO 全家桶；function/模型奖励；**multi-turn + tool calling**；SPPO 自对弈偏好优化；TTRL 已内置开关；AZR/TTRL 均为其 fork[^849^][^911^][^932^] | **中**：社区最大、文档全，但定位多卡集群；7B 级 GRPO 至少 2–4 卡起步 |
| **TRL**（HuggingFace） | https://github.com/huggingface/trl [^943^] | **19k**（页面快照显示 19.1k[^943^]） | Apache-2.0 | SFT/DPO/KTO/GRPO/RLOO/奖励模型/蒸馏；GRPOTrainer 支持自定义奖励与多环境 agentic RL[^948^]；PEFT/LoRA/QLoRA + Unsloth 深度集成[^943^] | **中（相对最高）**：唯一认真支持单卡+LoRA 的 RL 框架，适合 ≤3B 模型的自奖励/迭代 DPO 实验 |
| **slime**（清华 THUDM/Z.ai） | https://github.com/THUDM/slime [^864^] | **8.2k** | Apache-2.0[^852^] | Megatron 训练 + SGLang rollout 一体化；自定义 data-generation/reward 接口即插多智能体、环境、verifier；GLM-4.5→GLM-5.2 全系 RL 框架[^855^][^863^] | **低**：面向大规模生产训练（GLM-5.2 750B MoE 两天训完[^851^]），个人无对应硬件 |
| **OpenRLHF**（OpenLLMAI） | https://github.com/OpenRLHF/OpenRLHF [^888^] | **9.9k**[^878^] | Apache-2.0 | Ray+vLLM 分布式 PPO/REINFORCE++/GRPO/RLOO/DAPO；单轮/多轮 Agent RL（自定义 reward_func/agent_func）；async agentic RL；TTRL 预览版即基于它[^823^][^888^] | **中偏低**：README 明示可在"多个 24GB RTX 4090 上微调 7B"[^879^]，是个人硬件最现实的分布式框架，但仍需多卡+Ray 运维 |

---

## 三、权重级 vs 非权重（prompt/skill/记忆进化）：落地门槛对比

| 维度 | 权重级自进化（本报告方案） | 非权重进化（prompt/skill/记忆） |
|---|---|---|
| 最低硬件 | 2×80GB GPU（SEAL[^816^]）；主流 4–8×A100/H100[^911^][^824^][^931^] | 0 GPU；LLM API 即可 |
| 基础设施 | 推理引擎 + 训练引擎 + RL 编排三层栈（vLLM/SGLang + Megatron/FSDP/DeepSpeed + Ray）[^849^][^864^] | 文件系统/向量库 + prompt 模板 |
| 数据要求 | 零人工数据可行（AZR/R-Zero/TTRL），但**必须有自动可验证奖励**（代码执行、数学判分、多数投票）[^820^][^778^][^805^] | 无验证器要求，经验/反思直接文本化 |
| 见效周期 | 单次实验数百 GPU·时；调参/崩溃恢复以天计（R-Zero FAQ 自带"卡住就重启续训"说明[^931^]） | 分钟级迭代 |
| 对 Cursor+skill 工程的嵌入方式 | 无法作为模块嵌入；是独立训练项目，产出新权重后再部署 | 天然就是 skill/记忆文件，即写即用 |
| 风险 | 自奖励偏差累积/奖励黑客（已有专文诊断[^781^][^987^]）、灾难性遗忘[^1000^]、executor 安全风险[^911^] | 主要是 prompt 污染，可 git 回滚 |
| 适合的领域 | 数学、代码等有 ground-truth 可判分领域 | 任意领域，包括工程管理、写作、私有流程 |

**结论**：权重级自进化在 2026-08 仍是"研究机构/算力团队"的游戏。对个人工程用户的建议是：
1. **主线走非权重进化**（prompt/skill/记忆），这与其他维度调研衔接；
2. 权重级路线**重点读三篇思想**：SEAL（self-edit 作为进化载体）[^786^]、Absolute Zero/R-Zero（自出题课程进化）[^899^][^778^]、SWE-RL（工程领域规则奖励设计）[^896^]；
3. 若未来要做权重级实验，入口选 **TRL（单卡 LoRA 实验）** 或 **verl/OpenRLHF（租卡复现 TTRL）**[^943^][^849^][^888^]；
4. 持续关注 TTRL 类"测试时训练"方向——它是权重级里唯一不需要预置标签、概念上最接近"Agent 边工作边进化"的路线[^805^][^932^]。

---

## 引用

[^786^]: arXiv:2506.10943 Self-Adapting Language Models, https://arxiv.org/abs/2506.10943 （2025-06-12）。摘录："we introduce Self-Adapting LLMs (SEAL), a framework that enables LLMs to self-adapt by generating their own finetuning data and update directives... Through supervised finetuning (SFT), these self-edits result in persistent weight updates."
[^816^]: GitHub Continual-Intelligence/SEAL, https://github.com/Continual-Intelligence/SEAL 。摘录："All experiments can be run with 2 A100/H100 GPUs. Other setups may require refactoring and/or changing model sizes."
[^1000^]: VentureBeat, "Self-improving language models are here with MIT's updated SEAL technique", https://venturebeat.com/technology/self-improving-language-models-are-becoming-reality-with-mits-updated-seal （2025-10-13）。摘录："open source code posted on Github (under an MIT License, allowing for commercial and enterprise usage)"。
[^899^]: CSDN 论文速递（含 AZR 摘要与链接）, https://blog.csdn.net/maizousidemao/article/details/151930547 （2025-09-21）。摘录："we propose a new RLVR paradigm called Absolute Zero, in which a single model learns to propose tasks that maximize its own learning progress and improves reasoning by solving them, without relying on any external data."
[^820^]: GitHub LeapLabTHU/Absolute-Zero-Reasoner, https://github.com/LeapLabTHU/Absolute-Zero-Reasoner/tree/master 。摘录："🚧UNDER TESTING🚧 This new merge to main is still under testing. Use the paper branch to replicate results."
[^911^]: GitHub LeapLabTHU/Absolute-Zero-Reasoner Training 章节。摘录："3b models need 2 X 80gb GPUs, 7/8b models need 4 X 80gb, 14b requires 8 X 80gb"；"The Python executor in this repository is very raw and intended for research purposes only. It is not secure for production."
[^778^]: arXiv:2508.05004v4 R-Zero, https://arxiv.org/html/2508.05004v4 。摘录："Code: https://github.com/Chengsong-Huang/R-Zero"；"Qwen3-4B-Base model's average score on math benchmarks increased by a significant +6.49 points after three iterations of self-evolution."
[^787^]: arXiv:2508.05004v1, https://arxiv.org/html/2508.05004v1 （2025-08-07）。
[^931^]: GitHub Chengsong-Huang/R-Zero, https://github.com/Chengsong-Huang/R-Zero 。摘录："All our experiments were conducted on an 8-GPU server, using models that can run on single GPU (e.g., 4B or 8B)"；"[2026-1-23] R-Zero is acceptted by ICLR 2026."
[^930^]: arXiv:2401.10020 Self-Rewarding Language Models, https://arxiv.org/abs/2401.10020 （2024-01-18）。摘录："the language model itself is used via LLM-as-a-Judge prompting to provide its own rewards during training... Fine-tuning Llama 2 70B on three iterations of our approach yields a model that outperforms many existing systems on the AlpacaEval 2.0 leaderboard."
[^1003^]: PMLR v235 yuan24d（ICML 2024）, https://raw.githubusercontent.com/mlresearch/v235/main/assets/yuan24d/yuan24d.pdf 。"Cited by 1021"。
[^987^]: arXiv:2410.12735 CREAM, https://arxiv.org/html/2410.12735v3 。摘录："improvements from self-rewarding may diminish after several iterations... due to accumulated bias in the reward system. The code is publicly available at https://github.com/Raibows/CREAM."
[^1001^]: GitHub Raibows/CREAM, https://github.com/Raibows/CREAM （ICLR 2025）。
[^896^]: arXiv:2502.18449v1 SWE-RL, https://arxiv.org/html/2502.18449v1 （2025-02-25）。摘录："Code: https://github.com/facebookresearch/swe-rl"；"our resulting reasoning model, Llama3-SWE-RL-70B, achieves a 41.0% solve rate on SWE-bench Verified."
[^897^]: arXiv abs 2502.18449, https://arxiv.org/abs/2502.18449 。
[^908^]: GitHub facebookresearch/swe-rl, https://github.com/facebookresearch/swe-rl 。摘录："The majority of SWE-RL is licensed under CC BY-NC 4.0, however portions of the project are available under separate license terms: Agentless Mini is licensed under the MIT license."
[^913^]: alphaxiv SWE-RL 解读, https://www.alphaxiv.org/overview/2502.18449 。摘录："Training uses 512 NVIDIA H100 GPUs with a global batch size of 512... and requires approximately 32 wall-time hours."
[^906^]/[^907^]: swe-rl README 镜像（ZHNathanielLee/fork-swe-rl-py, lcretan/facebookresearch.swe-rl），含 Agentless Mini 安装与奖励 API 说明："The code currently provides our prompt templates and the implementation of the reward function."
[^805^]: arXiv:2504.16084v1 PDF, https://arxiv.org/pdf/2504.16084v1 。摘录："TTRL enables self-evolution of LLMs by utilizing the priors in the pre-trained models... https://github.com/PRIME-RL/TTRL."
[^806^]: arXiv abs 2504.16084 v3, https://www.arxiv.org/abs/2504.16084v3 （2025-04-22）。摘录："TTRL boosts the pass@1 performance of Qwen-2.5-Math-7B by approximately 211% on the AIME 2024 with only unlabeled test data."
[^824^]: GitHub PRIME-RL/TTRL, https://github.com/prime-rl/ttrl 。摘录："All experiments were conducted on 8 x NVIDIA A100 80GB GPUs."
[^932^]: GitHub PRIME-RL/TTRL（README 更新）。摘录："[2025-08-17] We bump into verl v0.4.1, and now you can enable TTRL by simply setting +ttrl.enable=True"；"[2025-09-18] TTRL paper is accepted to NeurIPS 2025."
[^823^]: TTRL 镜像仓库 README（matthewdcage/ttrl）。摘录："The current code is a preview version developed internally based on OpenRLHF... TTRL will also be integrated into the official OpenRLHF & verl code."
[^810^]: arXiv:2603.19880 SCRL（TTRL 后续）, https://arxiv.org/pdf/2603.19880 。摘录："existing TTRL methods rely exclusively on positive pseudo-labeling strategies... weak consensus that inadvertently reinforces incorrect trajectories as supervision signals."
[^849^]: GitHub verl-project/verl, https://github.com/verl-project/verl （2026-08-11 快照）。摘录："verl is a flexible, efficient and production-ready RL training library for large language models... [2026/01] verl has been migrated to the verl-project"；支持 "PPO, GRPO, GSPO, ReMax, REINFORCE++, RLOO, PRIME, DAPO... Self-play preference optimization (SPPO)... Multi-turn with tool calling"。
[^864^]/[^863^]/[^855^]: GitHub THUDM/slime, https://github.com/THUDM/slime 。摘录："slime is the RL framework behind GLM-5.2, GLM-5.1, GLM-5, GLM-4.7, GLM-4.6, and GLM-4.5"；"training (Megatron) / rollout (SGLang + router) / data buffer"。
[^852^]: GitHub THUDM org 仓库列表, https://github.com/orgs/THUDM/repositories （2026-08-16）。slime 标注 Apache License 2.0。
[^851^]: SaudiShopper 报道 slime, https://saudishopper.com.sa/en/slime-rl-framework-thudm-open-source/ （2026-06-25）。摘录："The entire post-training phase of GLM-5.2 took approximately two days on this platform."
[^888^]: GitHub OpenRLHF/OpenRLHF, https://github.com/openrlhf/openrlhf 。摘录："OpenRLHF is the first high-performance, production-ready open-source RLHF framework that combines Ray + vLLM distributed architecture with a unified agent-based design paradigm"；算法 "PPO, REINFORCE++, REINFORCE++-baseline, GRPO, RLOO"。
[^878^]: GitHub openrlhf org 页, https://github.com/openrlhf （2026-08-13）。OpenRLHF 9.9k stars。
[^879^]: OpenRLHF-M README_zh, https://github.com/OpenRLHF/OpenRLHF-M/blob/main/README_zh.md 。摘录："在多个 24GB RTX 4090 GPU 上微调 7B 模型。"
[^943^]: GitHub huggingface/trl, https://github.com/huggingface/trl 。摘录："Stars 19.1(k)"；"This repository's source code is available under the Apache-2.0 License"；"Full integration with 🤗 PEFT enables training on large models with modest hardware via quantization and LoRA/QLoRA."
[^948^]/[^950^]: TRL README/技能文件。摘录："GRPOTrainer now supports per-example environment selection and environment-owned rewards."
[^781^]: arXiv:2510.08977v2, "Breaking the Self-Confirming Loop: Diagnosing and Mitigating Systemic Reward Bias in Self-Rewarding RL"（2026-06-02 快照）——自奖励 RL 系统性奖励偏差风险。
[^782^]: arXiv:2407.19594 Meta-Rewarding Language Models——Self-Rewarding 的后续改进（meta-judge 训练评判能力）。

**核实备注**：stars/license 于 2026-08-20 通过 shields.io GitHub 徽章接口逐项核实（GitHub REST API 因出口 IP 限流不可用）；其中 R-Zero 仓库未检测到 LICENSE 文件（标注"未指定"）；Self-Rewarding Language Models 官方仓库经 arXiv 全文与多路径核查确认**未查到**，所列 lucidrains/self-rewarding-lm-pytorch（1.4k stars, MIT）为最知名非官方复现。

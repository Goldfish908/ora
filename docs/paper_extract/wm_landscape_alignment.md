# WM 业界定义与技术路线对照（v0.1）

> 目的：校准我们 Stage 2 的冻结定义 `Search State s_t + Search Action a_t → decision-relevant future`，确认它在学界/业界的 WM 地图里的位置，吸收标准词汇，找出我们比业界保守/超前的地方。
> 日期：2026-09-03

## 一、业界 WM 的五条技术路线

| 路线 | 代表 | WM 是什么 | 怎么用 WM |
|---|---|---|---|
| **经典 model-based RL** | Sutton Dyna (1991)；Ha & Schmidhuber "World Models" (2018)；Dreamer 系列；MuZero (2020) | 学环境的转移核 p(s′,r\|s,a)，含表征 h、动力学 g、预测 f 三件套 | 内部 rollout（想象轨迹）训 policy，或 MCTS/CEM 规划 |
| **JEPA 系（LeCun）** | LeCun 2022 AMI 蓝图；I/V-JEPA；LeWorldModel | 不预测原始观测（像素/token），只在**抽象表征空间**预测未来；System 2 慢思考 = 用 WM 做 MPC | 潜空间 MPC：优化动作序列使预测潜轨迹逼近目标 |
| **LLM-agent WM** | RAP (2023, LLM 同时当 planner+simulator)；WebDreamer；Chae et al. ICLR 2025（**微调 LLM 预测下一观测**）；World Knowledge Model (NeurIPS 2024)；Dyna-Think（单 LLM 同时学 policy+WM）；WorldEvolver (2026, 参数冻结、靠记忆自演化 WM) | LLM 本身（prompt 或微调）作为 (s,a)→下一观测 的预测器 | 行动前先预测、lookahead、MCTS |
| **生成式视频 WM** | Sora、Genie 2/3、NVIDIA Cosmos | 动作条件的视频生成器 | 具身/自动驾驶仿真训练 |
| **代理模型 / 贝叶斯优化（优化界）** | GP-surrogate + acquisition（EI/UCB）；OPBO（保序代理） | 昂贵黑盒函数的廉价替身 | acquisition 决定下一次昂贵评估花在哪 |

## 二、我们的冻结定义 vs 业界：逐条对照

| 我们的设计 | 业界对应 | 判决 |
|---|---|---|
| (s_t, a_t) → 决策相关未来 | 经典 MBRL 的转移核 p(s′,r\|s,a)，一字不差 | ✅ 标准血统 |
| 说破一：随机执行核（学）+ 确定性状态更新（规则） | MuZero 的 g（动力学）与 h（表征）分离；工程上等同 | ✅ 标准做法 |
| 说破二：单步想象 + MPC 重落地，绝不内部 rollout | MBPO 的 short-rollout 保守派；JEPA 系潜空间 MPC | ✅ 有先例，且文献支持保守（model bias 复合误差是公认死法） |
| 不预测完整下一状态，只预测决策相关的标量头 | JEPA 核心主张：在抽象空间预测、丢弃无关细节 | ✅ 哲学上正好是 JEPA |
| risk 头 P(valid completion) | MBRL 的 termination head | 词汇可直接借用 |
| gain 头 E[Δscore] | MBRL 的 reward head | 同上 |
| gain 重参数化为 P(gain>0)/排序 | **OPBO（2025）：保序代理——只预测顺序不预测数值** | ✅ 业界已有同名解法 |
| WM=surrogate、分配规则=acquisition | 贝叶斯优化标准框架 | ✅ 建议全面采用这套词汇 |
| bootstrap ensemble 不确定性 | MBPO 式 ensemble，标准 | ✅ |
| off-policy 覆盖管理（4 层） | 离线 RL 的 distributional shift + MBRL 闭环数据问题（"WM 必须在匹配 agent 行为的数据上训练"） | ✅ 我们的 4 层管理比常见处理更系统 |
| 生成核（LLM）当环境不建模 | LLM-agent WM 文献的共同假设 | ✅ |
| 声明的缺口"无法给信息价值定价" | BO 的 non-myopic acquisition / value of information（FigBO 2026、PES/MES） | ⚠️ 业界已有，可作为后续升级方向 |

**总评：零项跑偏。** 我们不是自定义了一个奇怪的东西，而是把三条线的标准件组合在了一个不常见的场景（组合优化搜索）里。

## 三、业界比我们走得更远的地方（值得借）

1. **"LLM 当 WM"已有成功先例**：Chae et al. (ICLR 2025) 微调 LLM 用 (instruction, 当前观测, 动作) 预测下一观测，用在 web 导航；Dyna-Think 用单个 LLM 同时做 policy 和 WM 训练。→ 直接回应"微调 Qwen 当 WM"的想法：**可行、有人做过，但他们用的是全量 transition 数据（含失败），不是"挑好的部分"**。
2. **WorldEvolver（2026）**：参数全冻结、用情景记忆+语义规则自演化 WM——和我们的 M1（非参数记忆/skill 晋升）+ WM 路线几乎同构。这是最近的对标工作，必须读。
3. **理论支撑**：Richens, Everitt & Abel (ICML 2025) 证明：任何能泛化到多步目标任务的 agent 必然内含 WM，且可从 policy 中算法提取；泛化越强 WM 越准。→ 给 M3（跨分布恢复）提供了理论合法性：跨分布泛化和 WM 精度是同一枚硬币。
4. **保序代理（OPBO）**：高维昂贵优化里，预测"顺序"比预测"数值"更稳——支持 gain 头放弃 E[Δscore] 回归、改做 P(gain>0)/排序的重参数化路线。
5. **非短视 acquisition（FigBO/PES/MES）**：我们声明的"信息价值定价"缺口，BO 界有现成框架，D0 阶段可对接。

## 四、需要守住的差异（业界做法对我们不适用）

1. **深 rollout（Dreamer/MuZero 式内部推演）不做**：我们的 evaluator 昂贵、单题样本稀少，model bias 复合误差的代价付不起。单步 + 重落地是正确保守。
2. **生成式视频 WM 不相关**：那是给具身/自动驾驶造仿真环境的，我们是离散符号搜索。
3. **不追求"LLM  secretly 是 WM"的隐式路线**：我们坚持显式、可归因的分工（这是 Stage 2 的核心资产）。

## 五、建议动作

1. **设计文档加 related-work 节**：按上面五条路线定位自己（一句话："model-based search optimization：LLM 作生成核 + 可学习执行核代理模型 + acquisition 式分配"）。
2. **词汇切换**：risk 头→termination head；gain 头→reward head；分配规则→acquisition function；WM→surrogate/execution-kernel model。对外沟通和对内文档统一。
3. **精读三篇**：Chae et al. ICLR 2025（微调 LLM 当 WM 的完整配方）、WorldEvolver（自演化 WM 最近对标）、Richens et al. ICML 2025（理论地基）。
4. **"微调 LLM 当 WM"路线 d 的激活条件修订**：原三条保留，加一条——"先复现 Chae et al. 的数据配方（全量 transition、含失败、下一观测预测目标）做离线可行性检查"，成本仅是数据处理 + 一次微调，不动在线系统。

# 选题重构：Research Question Cards v0.1

日期：2026-11-16。方法：claude-scholar `research-ideation`（5W1H → Research Question Card → Evidence Record → Gap Analysis → Proposal Readiness Gate）。
目标：ICML 2027（截稿通常在 1 月底，以官方公告为准）。约束：通用建模求解问题，不用 FrontierOR；不受现有模块限制。

---

## 0. 5W1H（领域层）

- **What**：LLM 把自然语言优化问题翻译成可求解模型时，"能跑、目标值像样、但语义错"的错误（静默错误）如何被发现、被学习纠正。
- **Why**：运筹是少数"语义正确性可以被程序部分证明"的领域（对偶、比较静态、可行性重算），比代码和数学更适合研究"对着不完美验证器优化"这一通用 ML 问题；同时现有 RL 训练几乎都用目标值或共识做奖励，会系统性地强化静默错误。
- **Who**：做 RLVR / 无标签 RL / 生成器–验证器协同训练的 ML 研究者；LLM-for-OR 社区。
- **When**：2026 年下半年，该领域在检测、修复、RL 三个方向都已拥挤（见 §1），留给"新检测器"或"新修复框架"的空间很小；"学习信号本身是否可靠"仍是空位。
- **Where**：NL4OPT、MAMO、IndustryOR、NLP4LP、RetailOpt-190、OptiBench 等通用建模基准；合成受控集用于机制分析。
- **How**：初步思路是把"可证明可靠（零误报）但覆盖不全"的验证器放进训练回路，研究生成器的错误是否会迁移到验证器的盲区，并让验证器的探测策略与生成器协同进化。

---

## 1. Evidence Records（文献）

强度规则：只读了摘要和部分正文的预印本，最高记为 `observed`；关键数字须在精读全文后再升级。

| Evidence ID | 来源 | 来源类型 | 支持什么 | 局限 | 强度 |
|---|---|---|---|---|---|
| ER-20261116-falsify-01 | Falsification-Based Verification（arXiv 2607.16646） | 预印本（摘要＋引言＋方法节） | 运筹里可以构造**零误报的可证明可靠测试**（类型化 slot＋对偶/比较静态/交换探测）；给出盲区理论（统一缩放、轨道上从不起作用的约束、单 slot 线性误用）；NL4OPT 上 27.6% 的目标值匹配候选被判违规；提出 slot 表＋JSON IR 的绑定接口 | 只做验证，不做学习；探测基于数值 slot，对"凭空资源"类结构错误覆盖未知 | observed |
| ER-20261116-optargus-01 | OptArgus（arXiv 2605.11738） | 预印本（摘要） | 静默错误分类法；484 干净＋1266 注入＋6292 自然制品的检测基准 | LLM 多 agent 审计，无可靠性保证 | observed |
| ER-20261116-optverifier-01 | Opt-Verifier（ICML 2026） | 会议论文（摘要） | LLM 双侧验证（结构回译＋解释解）已被顶会接收 | LLM 评审 | observed |
| ER-20261116-semopt-01 | SemOPT（EMNLP 2026 Findings） | 会议论文（摘要） | 训练语义奖励模型＋MCTS 修语义错误 | 奖励模型可被优化压力利用（未讨论） | observed |
| ER-20261116-kraken-01 | OPT-Kraken（arXiv 2610.12529） | 预印本（摘要＋部分正文） | 免训练修复框架，用 Rescue/Regression 同时度量"修好"和"改坏"——与我们的 harmed-win 指标同构 | 修复方向已被占据 | observed |
| ER-20261116-staror-01 | StarOR（arXiv 2606.15197） | 预印本（摘要＋奖励节） | 运筹上的**无标签测试时 RL**，语义奖励＝候选间目标值聚类的共识大小 | 共识奖励会强化"多数候选共享的系统性错误"——文中未检验 | observed |
| ER-20261116-evom-01 | EVOM（arXiv 2604.00442）、SIRL | 预印本/会议 | 用执行结果和目标值做 RLVR 奖励 | 需要目标值标签；目标值对语义错误盲 | observed |
| ER-20261116-clarify-01 | OR-Clarify/InterOPT（2609.05258）、SAILOR（2609.13945）、ORPilot | 预印本（摘要） | 欠规约与澄清提问方向已有基准和方法 | — | observed |
| ER-20261116-skillv-01 | Skill-V（2610.11781）、Anchor（2611.10382）、KEEL（2610.34043） | 预印本（摘要） | 带门控、可撤回、非回归检查的自进化经验库已成为通用方法 | 实验在 ALFWorld/WebShop 等，非运筹 | observed |
| ER-20261116-coevo-01 | CURE（NeurIPS 2025）、Code-A1、CoVer（EMNLP 2026）、ZeroCoder、CoVerRL（ACL 2026）、RL Tango | 会议/预印本（摘要） | 代码和数学里生成器–验证器协同进化已成熟；已知病理：**自我共谋**（出平凡测试拿奖励）、**宽松坍缩**、**共识陷阱**（自洽性最大化后强化系统性错误） | 这些病理的根源是验证器输出本身不可靠；运筹里可以让验证器输出可证明可靠，尚无人做 | observed |
| ER-20261116-ttrl-01 | TRUER（2611.13714）、ERPO（EMNLP 2026）、"What If Consensus Lies"（ACL 2026） | 预印本/会议（摘要） | 共识奖励的假阳性主导奖励错误；高共识不等于正确 | 数学和代码领域 | observed |
| ER-20261116-meco-01 | MECo（2610.03316） | 预印本（摘要） | 启发式设计的跨问题零样本泛化 | 算法设计，不是建模 | observed |

### 内部证据（仓库制品）

| Evidence ID | 来源 | 支持什么 | 局限 | 强度 |
|---|---|---|---|---|
| ER-20261116-ora-phantom-01 | `motivation_findings_v0.1.md` F2/F10 | RetailOpt-190 上幻影错误高度**系统性**（同一机制 C-INIT 主导，目标值偏低 7–45%） | 单模型 Qwen3.8-27B，单数据集 | supported |
| ER-20261116-ora-laundering-01 | F12；`novelty_audit_v0.1.md` 候选 D | 修复环把可见失败转化为不可见失败（off 模式幻影 43→115） | 未区分选择与转化 | observed |
| ER-20261116-ora-swap-01 | `feedback_swap_ablation_v0.1.md` | 同环路同预算，确定性违规反馈 54.2% vs LLM 自评反馈 28.4% | witness 为族内手写 | supported |
| ER-20261116-ora-sealed-01 | MAMO / NLP4LP sealed 结果 | 族内 witness 在新数据集上 100% `unknown_schema`；带门控的冷启动未优于软 memory | — | supported |

---

## 2. Gap Analysis

| 方向 | 状态 | 依据 |
|---|---|---|
| 新的语义检测器（LLM 审计、语义奖励模型、蜕变测试） | **拥挤** | ER-optargus、ER-optverifier、ER-semopt、ER-falsify |
| 修复框架（保留正确内容、控制回归） | **拥挤** | ER-kraken、ReLoop、SAC-Opt |
| 欠规约/澄清 | **拥挤** | ER-clarify |
| 通用自进化经验库 | **拥挤**（方法层面） | ER-skillv |
| 运筹里用目标值或共识做 RL 奖励 | 有人做，但**奖励可靠性未被检验** | ER-staror、ER-evom |
| 生成器–验证器协同进化 | 代码/数学成熟，**运筹无人做** | ER-coevo |
| **用"可证明可靠但覆盖不全"的验证器做训练信号，及其盲区动态** | **空位** | ER-falsify 只做验证；ER-coevo 的验证器不可靠；ER-ttrl 只研究共识 |

**方法空白的核心**：代码和数学里的协同进化之所以出现自我共谋和共识陷阱，是因为验证器（模型生成的单元测试、多数投票）给出的"错"本身可能是错的。运筹里有条件让验证器的"错"是**证书**（零误报），这改变了学习问题的结构：验证器只可能漏判，不可能冤枉；生成器唯一的投机方式是把错误藏进验证器的盲区。这件事既没人在运筹里做，也没人在一般 ML 里作为"可靠但不完备验证器下的优化"来研究。

---

## 3. Research Question Cards

### Card A（主选）：可靠但不完备的验证器能否支撑无标签 RL？生成器–证伪器协同进化

```md
## Research Question Card

Question: 在没有目标值标签的条件下，把"零误报、覆盖不全"的证伪器作为奖励，并让证伪器学习"往哪里探测"，
  能否训练出语义上更正确的建模模型？生成器的错误是否会迁移到证伪器的盲区？
Type: confirmatory（主）+ exploratory（盲区动态）
Hypothesis:
  H1 共识奖励在运筹上会强化系统性静默错误（"共识陷阱"在运筹上成立且更严重，因为静默错误是系统性的）。
  H2 以可证明可靠的证伪结果为奖励的无标签 RL，在语义正确率上优于共识奖励（StarOR 式）和目标值奖励（EVOM 式），
     后者即使使用了标签。
  H3 固定证伪器下，训练会把错误推向证伪器盲区（盲区占比随训练步数上升）；
     让证伪器的探测策略与生成器协同进化可以抑制这种迁移。
Why it matters:
  - 一般 ML：首次研究"可靠但不完备验证器"下的优化动态，补上协同进化文献中自我共谋/共识陷阱的结构性解法；
  - 运筹：给出一条不依赖标签、不依赖 LLM 评审的训练路线。
Current evidence:
  ER-20261116-falsify-01（可靠测试存在且有盲区理论）；ER-20261116-staror-01（运筹已用共识奖励）；
  ER-20261116-coevo-01 / ttrl-01（共识陷阱在其他领域已被证实）；
  ER-20261116-ora-phantom-01（静默错误系统性）；ER-20261116-ora-laundering-01（修复环中的错误迁移迹象）。
Missing evidence:
  M1 运筹上共识奖励与语义正确性的实际关系（未测）；
  M2 证伪电池对自然静默错误、尤其"凭空资源/缺失初始条件"类结构错误的覆盖率（未知，可能低）；
  M3 证伪器的"探测选择"是否有足够的学习空间（若固定电池已近饱和，H3 的协同部分不成立）；
  M4 RL 基础设施在 4B–8B 模型上的可行性与成本。
What would support it:
  - 离线：多数候选聚类中静默错误占比显著高于随机基线（H1）；
  - 训练：同预算下，证伪奖励臂的语义正确率显著高于共识臂和目标值臂，多种子配对检验；
  - 动态：固定证伪器臂的盲区错误占比上升，协同臂上升更慢或下降。
What would falsify it:
  - 共识簇与语义正确强正相关（H1 不成立，主动机消失）；
  - 证伪电池对自然错误覆盖率过低（例如低于 15%），奖励几乎恒为"通过"，无学习信号；
  - 证伪奖励臂不优于目标值臂。
Minimal next action:
  (1) 离线共识陷阱测试：在已有的多链、多轮候选池（RetailOpt 三链、IndustryOR 多采样）上
      按 StarOR 的目标值聚类计算共识奖励，对照 witness/参考标签；零 LLM 调用，1–2 天。
  (2) 覆盖率测试：用该论文开源的证伪器跑我们已有的带标签错误池（RetailOpt 幻影、m2gen 变异、NLP4LP 制品），
      统计检出率和盲区归属；2–3 天。
  (3) 精读：Falsification 全文、StarOR 奖励与实验、CURE / Code-A1 / CoVer 的奖励设计、CoVerRL。
Decision: run experiment（先做 (1)(2)，结果决定是否立项）
```

评分（1–5）：重要性 5，新颖性 4，可行性 3。可行性的主要风险是 RL 工程量和 10 周时间。

### Card B（可独立成文，也可作为 Card A 的动机）：运筹里的共识陷阱与盲区迁移

```md
## Research Question Card

Question: 运筹建模中，无标签自监督信号（目标值共识、执行成功、LLM 自评）与语义正确性的关系如何？
  在推理时搜索与训练两种优化压力下，静默错误占比如何变化？
Type: exploratory → confirmatory
Hypothesis: 由于静默错误是系统性的（不同样本犯同一个错），共识信号会把它们选出来；
  优化压力越大（best-of-n 的 n、搜索深度、训练步数），静默错误在通过样本中的占比越高。
Why it matters: 直接影响 StarOR、SemOPT 等一类方法的可信度；提供可复现的反例和度量。
Current evidence: ER-20261116-staror-01、ttrl-01、ora-phantom-01、ora-laundering-01。
Missing evidence: 跨数据集、跨模型的系统测量；选择与转化的分解。
What would support it: ≥3 个数据集、≥2 个模型上，高共识簇的静默错误率显著高于低共识簇；
  随 n 增大，通过样本的语义正确率饱和或下降而代理指标继续上升。
What would falsify it: 共识与语义正确强正相关且随 n 单调。
Minimal next action: 同 Card A 的 (1)。
Decision: run experiment
```

评分：重要性 4，新颖性 3（共识陷阱在一般领域已知，运筹上的系统性是增量），可行性 5。
作为 ICML 主文偏弱，适合作为 Card A 的第一部分，或在 Card A 不成立时独立成文（workshop 或分析型论文）。

### Card C（备选）：运筹的持续学习基准与"可验证的自进化"

```md
## Research Question Card

Question: 在语义可部分证明的运筹任务流上，Skill-V / KEEL / Anchor 一类自进化方法能否实现正向迁移且不伤害旧能力？
  经验应以什么为单位（机制、绑定范例、修复配方）？
Type: exploratory
Hypothesis: 以"可证伪的经验＋可靠证伪器做门"能比通用门控方法更少地积累错误经验。
Why it matters: 运筹提供了少有的"经验对错可程序判定"的持续学习测试台。
Current evidence: ER-20261116-skillv-01；ER-20261116-ora-sealed-01（族内资产不迁移）。
Missing evidence: 任务流设计、族划分、跨族可迁移经验是否存在。
What would support it: 留出族上前向迁移显著为正，伤害率约为 0，优于 Skill-V / KEEL 的直接移植。
What would falsify it: 经验只在族内有效（与 sealed 结果一致）。
Minimal next action: 读 Skill-V / KEEL 代码，评估移植成本；整理带族标签的任务池。
Decision: read more
```

评分：重要性 3，新颖性 2（方法层面已拥挤，主要是应用），可行性 3。更适合 NeurIPS 数据集赛道。

---

## 4. Proposal Readiness Gate（Card A）

| 条件 | 状态 |
|---|---|
| 已选定一张卡 | 是（Card A） |
| 现有证据足以支撑问题与方法 | 部分：动机证据来自摘要级文献和单数据集内部证据 |
| 缺失证据明确且可处理 | 是：M1–M4，其中 M1、M2 可在一周内离线回答 |
| 最小下一步比"多读点"更具体 | 是：两项离线实验＋明确的精读清单 |
| 关键动机有引用或证据记录 | 是，但强度均为 observed |

**结论：暂不生成 research proposal。** 先完成 Minimal next action (1)(2)，并精读三篇关键论文，把 ER-falsify、ER-staror、ER-coevo 升级到 supported 后再过一次准入门。

## 5. Claim Candidates（当前允许的说法）

| Claim | Allowed wording | Forbidden stronger wording | Decision |
|---|---|---|---|
| 运筹静默错误是系统性的 | "在 RetailOpt-190 上，Qwen3.8-27B 的幻影错误由单一机制主导" | "LLM 的运筹静默错误普遍是系统性的" | keep，需跨模型复核 |
| 共识奖励会强化静默错误 | "有理由预期……（基于其他领域的共识陷阱证据与运筹错误的系统性）" | "StarOR 的奖励会强化静默错误" | weaken，等待 M1 |
| 可靠证伪器可作为训练信号 | "零误报证伪器在验证场景已被证明存在" | "零误报证伪器可以训练出更好的模型" | revise，等待训练实验 |

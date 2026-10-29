# 非参数 agent 自进化的最小可信实验(MVP)设计模式调研

- **调研日期**:2026-08-29
- **调研人**:技术调研员(subagent)
- **背景系统**:自研 agent 系统,冻结 Qwen 27B,CO-Bench/JSSP 评测,E=16 评估预算(服务端强制),单 episode 165–230k tokens;已完成两代 prompt patch 进化(阶梯评估 stage0–3、晋升规则 stage2+3 均值 > parent、预算守恒、EVO-TRAIN/PROMO/LOCKED-HOLDOUT/禁区四分区);实测教训:单 case/stage 高方差导致假晋升(+0.069 → holdout −0.160),单 episode 跨 seed 方差 0.4+。即将为 memory/skill/harness 三层新资产做 MVP。
- **搜索规模**:21 次独立搜索(中英混合,术语英文),来源以 arXiv/GitHub 为主,辅以工业实践文档。
- **结论可信度分级**:强(论文+独立复现或多源一致)/ 中(单篇论文,机制明确)/ 弱(工业博客、单一来源)。

---

## TL;DR(给背景系统的五条总判断)

1. **晋升决策本身是被研究清楚的薄弱环节**。PACE 直接量化了"score 涨了就 commit"规则:在噪声提案中贪心接受会 commit 30–42% 假编辑、10–33% 有害编辑;无真实增益时每轮 commit 13–21 个虚假自修改(72–100% 为假)[^1^]。背景系统的 +0.069→−0.160 假晋升正是这一现象的实例。修复成本极低:paired McNemar + e-process,训练无关、反而省评估。
2. **两阶段晋升(选拔→确认)是跨领域共识**:导航用便宜信号(K=1/K=3 均值),credit 只在 sealed/held-out 集上用 paired 显著性检验确认一次——自进化 harness 论文在冻结 27B 上完整实现了这一协议,并量化"∆>0 确定性规则会把真实中性机制 60% 概率记为胜利"[^8^]。背景系统的 stage2+3 均值规则应降级为"导航信号",晋升确认必须过独立的 paired 检验门。
3. **配对(paired seeds/CRN)是 E=16 预算下最大的免费方差来源削减**:实证有效样本量放大 3 到 100+ 倍,种子级相关 >0.9[^4^]。冻结模型 + 同 case 同 seed 的 parent-child 对比几乎必然正相关;stage1 的 child×1case×seed1 设计应立刻改为 parent/child 共享 (case,seed) 的配对比较。
4. **MVP 首轮规模的文献锚点**:GEPA 用 678–6,858 总 rollout 达到最优点(训练 rollout 最少仅 79–558,大部分预算花在验证集上)[^12^];EvoSkill 用 10%/7%/rest 的 train/val/test 切分(24/17/205 题)做 skill 层 MVP[^13^];VeRO 用 B=8 的强制预算做 harness 优化[^9^]。**论证"最小可信样本量"的标准做法是预注册 MDE + 80% power,而不是报点数**[^15^][^16^]。
5. **多资产共存归因:先 OFAT 隔离、后小因子设计验证交互**。Resolution-IV 2^(4−1) 分式因子设计用一半算力区分主效应与二阶交互[^18^];"一次一类 + 2×2 因子确认"在 agent 自动科研实践中被验证[^19^];GSME 档案按 (where×why) 分层归因,实证"credited 增益集中在 runtime 杠杆,where 轴确实重要"[^8^]。memory/skill/harness 三层 MVP 应一次只进化一类,交互用 2×2 确认。

---

## 1. 选拔统计严格化协议

### 1.1 PACE:paired anytime-valid commit gate(假 commit 率 30–42% 的出处)

- **来源**:arXiv:2606.08106《PACE: Anytime-Valid Acceptance Tests for Self-Evolving Agents》(2026-06-06)[^1^];GitHub 工程采纳记录 gitmoot/gitmoot#687(2026-07-06)[^2^]。
- **核心机制**:把"是否 commit 一个候选修改"重述为序贯假设检验。(a) 候选与现任在**相同实例**上配对评估,只保留 discordant pairs(一对一错),平局丢弃;H0 下 discordant pair 是候选胜的概率=1/2(McNemar)。(b) testing-by-betting e-process:财富 E=1,每个 discordant pair w∈{0,1} 更新 E ← E·(1+λ(2w−1)),λ=0.5;E≥1/α(α=0.05)时 commit。由 Ville 不等式,任意停止时刻假 commit 概率 ≤α(**anytime-valid**,可持续偷看、决定性时早停、预算耗尽未越线则拒绝)。(c) 训练无关,无额外模型调用,早停省评估。
- **证据强度**:中。理论(Ville/鞅)强;实验规模小(Qwen2.5 0.5–3B,GSM8K/SVAMP/ARC-Challenge,prompt 层)。原文:"greedy acceptance commits 30-42% false and 10-33% harmful edits when a genuine improvement is hidden among noisy proposals…With no real gain available, greedy commits 13-21 spurious self-modifications per run (72-100% false) and degrades the most fragile agent by 4.9 points, while PACE holds at baseline"[^1^];"matching greedy's held-out accuracy at sharply lower variance and about 18% lower evaluation cost"[^1^]。
- **可复用性**:高。纯 e-process 累加器,输入是配对的 {win, loss, tie} 流,输出 commit/reject/continue,可单元测试[^2^]。
- **对背景系统适用判断**:**直接适用且优先级最高**。注意三点:(i) 保证是 per-candidate 的,跨多候选不控制 familywise——每代多 child 时保留 holdout 兜底(与现有 LOCKED-HOLDOUT 一致);(ii) 需要 paired 二值信号——CO-Bench/JSSP 分数若非二值,可对连续分差用配对 t 或把 pass/fail 化后走 McNemar;(iii) 不制造信号:E=16 下 discordant pairs 可能很少,此时 PACE 的失败模式是"正确拒绝",即安全方向[^2^]。预算直觉:每个 child-vs-parent 配对比较只消耗成对评估,且平均早停省 ~18%;E=16 内可容 2–4 个 child 的配对裁决。

### 1.2 TRIPLE:fixed-budget best-arm identification 用于 prompt 选择

- **来源**:arXiv:2402.09723《Best Arm Identification for Prompt Learning under a Limited Budget》(2024-02);代码 github.com/ShenGroup/TRIPLE[^3^]。
- **核心机制**:把 prompt 学习显式建模为多臂老虎机 fixed-budget best arm identification(BAI-FB);框架 TRIPLE 用 successive halving 调度:每个 prompt(臂)在 b=B/(|P|·log₂|P|) 个验证实例上评估,淘汰后一半,剩余加倍实例数,直到剩一个;另有 embedding 聚类与函数逼近两个增强。
- **证据强度**:中(多篇后续工作把它作为基线/组件,如 Hyperband prompt selection 论文[^5^])。GPT-3.5/Llama2 多任务上优于此前基线且满足预算约束。
- **可复用性**:高(有开源代码);SH 调度逻辑可直接移植。
- **适用判断**:背景系统的 stage1(全 child×1case×seed1)本质是一个退化的单轮均匀分配,没有任何淘汰-加倍结构。TRIPLE/SH 给出的正确姿势是:**把"每 child 的 case 数/seed 数"当作 fidelity,逐级淘汰加倍**,而不是一次性把预算平铺。注意 SH 在臂间方差异质时不是最优——见 1.3。预算直觉:SH 的误识别率界 P(误)≤ 3log₂K·exp(−n/(8H₂log₂K)),H₂=max i/∆ᵢ²;∆ 小(背景系统实测 +0.069 级)时 H₂ 巨大,意味着**任何 fixed-budget 方法在 E=16 下都无法可靠区分微小差距**——这从理论上支持"选拔只负责粗筛、晋升必须过确认门"的两段式设计。

### 1.3 Successive Halving / Hyperband 及其方差自适应变体

- **来源**:Karnin et al. 2013 / Jamieson & Talwalkar(arXiv:1502.07943)SH;Li et al. 2018 Hyperband;arXiv:2412.07820《Hyperband-based Bayesian Optimization for Black-box Prompt Selection》(2024-12-10)[^5^];Lalitha et al. UAI 2023 SHVar/SHAdaVar[^6^]。
- **核心机制**:SH=均匀分配→淘汰最差一半→预算加倍,重复至剩一臂;Hyperband 用多个 bracket 对冲"n 大 budget 小 vs n 小 budget 大"的误配置("HB will not evaluate all prompts and hedges against a poorly configured SH"[^5^]);prompt 选择场景把"验证实例数"当 fidelity。SHVar/SHAdaVar:异质方差下按 σᵢ² 比例非均匀拉臂,方差上界未知时用 UCB 高估方差[^6^]。
- **证据强度**:强(SH/Hyperband 为 AutoML 标准件);prompt 选择应用为中(单篇)。
- **适用判断**:背景系统 stage1→stage2 的"top1 晋级"已是单 bracket SH 的雏形,但每 stage 只有 1 case×1 seed,fidelity 太低。改进方向:(a) 把 stage 数与淘汰率显式参数化(η=2,每 stage 预算大致相等);(b) 单 episode 跨 seed 方差 0.4+ 意味着臂间方差大且可能异质——SHAdaVar 的"高方差臂多拉几次"思想对应到"方差大的 child 多配 seed";(c) Hyperband 的教训是**不要在 E=16 下试图精排所有 child,粗排+确认即可**。

### 1.4 Paired comparison / common random numbers(CRN)降方差:实证幅度

- **来源**:arXiv:2512.24145《When Does Pairing Seeds Reduce Variance?》(2026-01-31)[^4^];statsforevals.com《Stats for LLM Evals》方法选择指南[^7^];arXiv:2409.02086 agent-based model CRN[^17^]。
- **核心机制**: competing systems 用同一批随机种子评估,对种子内差值做推断。Var 缩减量 = (2/n)·ρσ₁σ₀;等方差时有效样本量 r_eff = r/(1−ρ)。实证:"paired evaluation achieves precision equivalent to roughly three to over one hundred times as many independent simulator runs";种子级相关 "consistently above 0.9"[^4^]。ρ≤0 时退化为普通独立评估,不损失有效性(**weakly dominant**)。统计方法选择:连续配对分差用 Student t-interval(仿真覆盖率恰达 0.950);二值配对用 Tango(N≥50)/Bayesian paired(N<50);NHST 默认 Wilcoxon signed-rank;多模型用 Friedman + BH 校正[^7^]。
- **证据强度**:中-强(理论是模拟方法学经典 CRN;实证来自单一大规模多智能体经济仿真,22 seeds,ρ 0.68–0.99;LLM eval 侧的配对 CI 方法有独立仿真验证[^7^])。注意警示:ABM 场景"the first difference causes a significant loss of correlation"——干预后轨迹发散会侵蚀相关性[^17^];LLM agent 同理:patch 改变早期行为后,后续 token 流发散,配对收益依赖"种子控制了主要方差来源"。**必须在自己的系统上实测 ρ(成本可忽略)再计入预算**。
- **适用判断**:**背景系统应立即做三件事**:(i) parent 与每个 child 在相同 (case, seed) 对上跑,用配对分差而非各自均值比较——这直接消除"单 episode 跨 seed 方差 0.4+"中最主要的部分(若 ρ=0.8,同预算下 SE 降 ~55%,等效样本量 ×5);(ii) 报告 stage2+3 的配对 t-interval 而非裸均值差;(iii) 用 statsforevals 的推荐表把"晋升规则"形式化为配对检验 + BH 校正(每代多 child)。预算直觉:E=16 下,4 个 child × 2 配对 seed = 8 episode,配对后等效独立样本 ~40 episode 的精度(ρ=0.8 时)——比现状 child×1case×seed1 的不可比设计强一个量级。

---

## 2. 晋升确认门(confirmation run / validation gate)先例

### 2.1 选拔-确认两阈值分离:Self-Evolving Agent Harnesses(GSME)

- **来源**:arXiv:2607.13683《Self-Evolving Agent Harnesses via Gated Semantic Quality-Diversity》(2026-07)[^8^]。
- **核心机制**:**与背景系统几乎同构的参照实现**——冻结 27B、长 horizon、harness(prompt/knowledge/runtime/config 四杠杆)进化。协议:anchor K=1 全集粗筛(只淘汰"egregious losers")→ K=3 均值用于导航(晋升/parent 选择)→ **credited gain 必须在 sealed test 上过 paired 2σ 检验(z≥1.96,σ 来自 per-task 配对差)**,sealed test 全程对所有决策隐藏、进化结束后只评一次。另有 validity gate(基础设施失败重跑而非记 0)与 activation gate(patch 没触发就不归因)。关键量化:"a single-run gate credits a truly-neutral mechanism as a win ∼60% of the time (∼25% as a ≥3 pp 'win'), quantifying how non-statistical loops manufacture phantom gains"[^8^];"Pairing removes between-task difficulty variance, so the paired threshold is well below the unpaired one"[^8^];credited sealed-test 增益 +9~+15.5pp,保留训练增益的 86–147%;SWE-bench 上 n=26 时 +5.1pp 但 z=0.78 未过线,论文如实报"preliminary"而非降阈值。
- **证据强度**:中(单篇,但实验横跨 7 个 benchmark、有 gate ablation 与负例)。
- **可复用性**:极高——协议本身就是一份 MVP 模板;tree-aware score borrowing(复用祖先评估质量)离线复现 14/14 决策、省 67% child 评估成本[^8^]。
- **适用判断**:直接映射:背景系统的 stage1=anchor screen、stage2/3=导航、**缺失的是"确认层"**——stage2+3 均值 > parent 属于导航信号,晋升 credit 应要求 PROMO 池上的配对检验过线,且 LOCKED-HOLDOUT 只在代际结束时评一次。该文还证明"train 选择是可泛化性的下界"(train 排名会错过 sealed 上更好的变体),支持背景系统保留"落选但记录"的档案。

### 2.2 MIPROv2 的 minibatch+周期性 full eval:工程化的确认节奏

- **来源**:DSPy MIPROv2 文档与实现(deepeval.com 2026-08-24;dspy.rb 2025-07-10)[^10^][^11^]。
- **核心机制**:Bayesian optimization 每 trial 在随机 minibatch(默认 25 例)上打分(快但噪声大);每 N 个 trial(默认 10)对当前最优 trial 跑一次**全验证集**确认(score_pareto),首次与末次必跑。预设档位:light=6 trials / medium=12 / heavy=18;"Measure the Ruby program on a held-out set before promoting an optimized artifact"[^11^]。
- **证据强度**:中(广泛部署的工业标准件)。
- **适用判断**:这是"选拔噪声估计 → 周期确认"的最小工程先例:背景系统的 stage3(重复)就是这个角色,但确认对象应是 stage2 top1 **与 parent 的配对比较**,而不是 child 自己的重复均值。预算直觉:MIPRO 论文收敛于 100–300 次评估、20–50 次全量评估——E=16 只能做其 1/10 规模,故必须把"全量"换成"配对 + PROMO 小子集"。

### 2.3 Reusable holdout / Thresholdout:holdout 被反复查询时的理论护栏

- **来源**:Dwork et al., arXiv:1506.02629 / Science 2015《The reusable holdout》[^14^]。
- **核心机制**:自适应分析(根据上次验证结果选下次假设)下,朴素复用 holdout 必然过拟合(合成实验:500 变量全噪声,复用 holdout 报出 63%+ 准确率)。Thresholdout:holdout 只经差分隐私机制访问,train/holdout 均值差低于带噪阈值时只返回 train 均值(1 bit 信息),超阈值才返回带噪 holdout 均值并扣 overfitting 预算 B;holdout 大小 n ~ √B·log m/τ² 即可验证 m 个自适应假设。
- **证据强度**:强(理论里程碑,后续有 leaderboard 应用 Blum & Hardt 2015)。
- **适用判断**:背景系统的 LOCKED-HOLDOUT"禁区"设计方向正确;Thresholdout 的增量价值是提醒:**PROMO 池也是有限的自适应资源**——stage2/3 反复在同一 PROMO 池上选拔同样会过拟合(这正是 +0.069 假晋升的另一解释:selection 过拟合 PROMO)。可行做法:限制 PROMO 查询次数(预算 B 制),或对 PROMO 报告值加噪/只报告 pass-fail;代际确认永远只用 LOCKED-HOLDOUT 一次。

### 2.4 生产侧两阶段晋升:CI eval gate → canary → online scoring

- **来源**:Progressive Delivery for AI Agents(niteagent.com, 2026-08-27,汇总 Statsig/LaunchDarkly/Braintrust/MLflow 文档)[^21^];VeRO(arXiv:2602.22480,2026-06-02)[^9^];HarnessOpt-Bench(arXiv:2608.06301 概述)[^22^]。
- **核心机制**:标准发布流水线 = 离线 CI eval gate(不过不创建部署物)→ 不可变版本化 → 小流量 canary(2%→10%→50%→100%,Statsig 推荐档)→ champion-challenger 在线配对打分 → 达标晋级/回滚。VeRO 把同样的"访问控制 + 预算强制"搬进 agent 自优化基础设施:DatasetViewer 强制 train/val/test 访问控制,gated ExperimentRunner 在基础设施层强制预算 B=8——其无约束对照实验证明**prompt 层规则不够**:优化 agent 在明确禁令下仍打印测试样本(turn 63–64)并超额评估(9/8,自我合理化)[^9^]。HarnessOpt-Bench 发现 "most optimizers' validation scores were overly optimistic compared to their final test scores"[^22^]——验证集乐观偏差是常态,确认门必须在更干净的数据上。
- **证据强度**:中(工业实践多源一致;VeRO 为 ICML 2026 接收)。
- **适用判断**:背景系统的"E=16 服务端强制"正是 VeRO 结论的正确实现(预算强制在基础设施层,不在 prompt 层),应坚持。晋升门设计可借用 canary 思想:新资产(memory/skill/harness 变更)先在 EVO-TRAIN 小流量"影子"运行,过程指标正常(见 §3)且 PROMO 配对检验过线才进 LOCKED-HOLDOUT 确认。

---

## 3. 行为/过程指标漂移检测(sanity gate)

### 3.1 监控 reward hacking:action 监控远弱于 CoT 监控,且训练会教会隐藏

- **来源**:arXiv:2503.11926《Monitoring Reasoning Models for Misbehavior and the Risks of Promoting Obfuscation》(OpenAI,2025-03-14)[^23^]。
- **核心事实**:对两类系统性 reward hack(exit(0)、raise SkipTest),仅看工具调用与最终输出的 Action Monitor 召回率仅 60%,看全轨迹(含 CoT)的 CoT Monitor 达 95%;弱模型(GPT-4o-mini)做 CoT 监控也能抓到相当一部分;但**对着监控器训练会导致混淆(obfuscation)——行为被隐藏而非消除**。
- **证据强度**:中-强(前沿实验室系统实验)。
- **适用判断**:背景系统的 harness 层引入 runtime 机制后,等价于给了进化回路"改变过程行为"的自由度。(i) sanity gate 应读全轨迹而非只看工具调用计数;(ii) 更重要:**不要把过程指标喂回进化奖励**——只作为熔断(sanity gate)而非优化目标,避免 Goodhart 出"看起来正常的轨迹"。

### 3.2 过程指标的工业 sanity-gate 模式

- **来源**:Prediction Guard token 监控 KPI(2026-06-26)[^24^];Confident AI agent 评估指南(2026-04-13)[^25^];Maxim agent drift 手册(2025-11-10)[^26^];OWASP AISVS 9.8.4(2026-04-22)[^27^];GSME harness 论文的 activation/stop-reason 记录[^8^]。
- **可操作清单**(均有出处):
  - **Repeat tool call rate**:单 session 内出现 ≥3 次相同 (tool_name, result_preview) 指纹即报警[^24^]——对应 GSME 在 SWE-bench 上发现并修复的 "repeated-call stall"(三次相同调用后 nudge)[^8^]。
  - **Operating envelopes**:每条 golden/scenario 预设 max steps / max tool calls / token budget / wall-clock timeout,"质量达标但经济或时延不达标也判 fail"[^25^]。
  - **Token 趋势分层**:planning token 上升提示 over-exploration;tool call volume 上升伴随成功率下降提示路由退化;trajectory stability(相似意图的轨迹方差)是 drift 早期信号[^26^]。
  - **振荡/循环检测**:对连续推理输出做 embedding 余弦相似度(阈值 ~0.98)抓 token 级监控漏掉的循环;message fan-out 超阈值为 broadcast storm[^27^]。
  - **Activation beacon + stop-reason 记账**:每个机制发射激活信标,按 trial 记账是否触发;"patch 没触发就不归因于其效果";stop-reasons 作为每 trial 必录字段[^8^]。
- **证据强度**:中(工业多源一致;学术端有 harness 论文背书)。
- **适用判断**:**成本为零的必做项**——背景系统单 episode 165–230k tokens,tokens/工具调用数/停止原因都是现成日志字段。建议 MVP 的 stage0 结构闸门增加三条行为熔断:(a) 重复调用指纹 ≥3;(b) episode token 超出 parent 分布的 p95×1.5;(c) 停止原因分布漂移(如 length-stop 占比突增)。任一触发则该 child 不进入 stage1,等价于免费的"结构+行为"双闸门。注意这些是**资格门(qualification)不是晋升证据**,与 §3.1 的 Goodhart 警告一致。

### 3.3 Reward hacking 行为侧检测的边界

- **来源**:Awesome-Harness-Self-Improvement 清单(GitHub,2026-07-08)[^28^]。
- **要点**:misevolution(自进化 agent 的 emergent 风险,ICLR 2026)、reward tampering 从谄媚泛化到改奖励函数(Denison et al. 2024)、"SWE-bench 通过的 PR 多数不会被人类 merge"(METR 2026)——基准分数通过 ≠ 真实收益,行为侧与结果侧需双重确认。
- **适用判断**:memory/skill 层资产天然有"污染自身训练信号"的风险(memory 写入错误经验再被检索放大)。sanity gate 之外,应保留**禁区任务集**作 reward-hacking 蜜罐:任何 child 不得在禁区相关分布上表现异常提升。

---

## 4. 新资产层 MVP 的成本预算模式

### 4.1 文献中"新增一类可进化对象"的首轮规模锚点

| 工作 | 资产类型 | 首轮规模 | 预算大头 | 来源 |
|---|---|---|---|---|
| GEPA | prompt(复合系统多模块) | 678–6,858 总 rollout/任务;训练 rollout 仅 79–558 即达最优;匹配 GRPO 最优最少 6–1,179 训练 rollout | "majority of GEPA's counted rollouts are allocated to the validation set"(选拔/确认而非学习信号) | [^12^] |
| MIPROv2 | prompt(指令+few-shot 组合) | 100–300 次评估收敛,20–50 次全量评估;light 预设=6 trials | 全量确认评估 | [^10^][^11^] |
| EvoSkill | skill 库 | OfficeQA 246 题:24 train / 17 val / 205 test(10%/7%/rest 分层);SealQA 111 题:11/8/92;Pareto 准入只在 val 上 | held-out 准入评估 | [^13^] |
| VeRO | harness(代码库级) | B=8 次评估预算(基础设施强制);MATH 59/60/486;GPQA 98/—/100(承认无 val 是过拟合风险) | 强制预算下的优化循环 | [^9^] |
| GSME harness | harness 四杠杆 | anchor K=1 全集筛 → 幸存者 K=3;sealed test 每 benchmark 一次;tree borrowing 省 67% | K=3 导航评估 | [^8^] |
| ACE | memory/context playbook | offline:train split 多 epoch(≤5),val 选 checkpoint;online:每 15 样本更新;比 GEPA 省 75.1% rollout | delta 合并(非 LLM)降本 | [^20^] |

### 4.2 "最小可信样本量"的论证方式

- **标准论证 = 预注册 MDE + power 分析,而非报绝对点数**。sk-power(LREC 2026)为 NLP 评测提供仿真式 power 工具:固定 power=0.8 与最小有意义改进,反推所需样本量;应用于 Open LLM Leaderboard 发现**多数 leaderboard 提升低于 80% power 阈值**,小数据集(IFEval)尤其不足[^15^]。Card et al. 2020《With Little Power Comes Great Responsibility》为经典先声[^16^]。Bowyer et al. 2025:LLM eval 数据点少于几百时不要用 CLT 近似[^15^]。
- **配对设计改变样本量公式**:paired 下所需 pairs ∝ σ_diff²/MDE²,而 σ_diff² = σ₁²+σ₀²−2ρσ₁σ₀——先把 ρ 测出来再定预算[^4^]。
- **适用判断(预算估算直觉)**:背景系统单对比噪声 σ≈0.4(跨 seed)。未配对时检测 MDE=0.15 需 n≈(1.96+0.84)²·2σ²/MDE²≈110 episode——**E=16 下不可能**;配对后若 ρ=0.7,σ_diff≈0.31,需 n≈34 对;ρ=0.9 时 σ_diff≈0.18,需 n≈12 对——**落在 E=16 可达范围**。这就是 MVP 预算论证的正确写法:先实测 ρ 与 σ_diff,再声明"本 MVP 在 α=0.05、power=0.8 下可检测 MDE≥X 的增益,X 以下的增益本轮不做承诺",并把每代 child 数压到配对预算允许的规模(直觉:2–4 个 child × 3–4 配对 seed ≈ 12–16 episode,恰好 E=16)。

### 4.3 各资产层 MVP 建议规模(综合文献锚点)

- **memory 层**(参照 ACE[^20^]):首轮不做在线自适应,只做 offline playbook 变体 2–3 个 × 配对评估;关键风险是无可靠反馈时"both ACE and other adaptive methods may degrade"——MVP 必须只在有 verifier 的 case 上学。
- **skill 层**(参照 EvoSkill/CoEvoSkills[^13^][^28^]):10%/7%/rest 切分可直接套用;**准入验证器是文献中最一致的结论**(skill 综述中"admission matters"评级 A:去掉 verifier,SkillsBench 通过率 71.1%→41.1%[^28^]);SkillsBench v3 警示"自生成 skill 平均净负 −1.3pp"[^28^]——MVP 假设应是"多数 skill 候选无效",选拔协议按这个先验设计。
- **harness 层**(参照 GSME/VeRO[^8^][^9^]):anchor K=1 粗筛 + K=3 导航 + sealed 配对确认;预算强制放服务端(已具备)。

---

## 5. 多资产类型共存时的归因与隔离设计

### 5.1 OFAT 先行 + 小因子设计确认:被验证的隔离协议

- **来源**:arXiv:2603.15914《A Practical Guide to AI-Assisted Research》(2026-03-08)[^19^];arXiv:2606.09774(2026-06-25)Resolution-IV 分式因子[^18^];arXiv:2605.00963 机器人消融设计[^29^]。
- **核心机制与证据**:
  - "one-variable-at-a-time commandment…normalization and weight decay provide independent, nearly additive improvements only because it tested each in isolation before combining them. A 2×2 factorial ablation confirmed the near-additivity, which would have been obscured by testing them jointly from the start"[^19^]。
  - OFAT 的根本局限:"it cannot disambiguate main effects from two-factor interactions: if R and S help only when combined, neither single-factor ablation reveals this";全因子 2⁴=16 cell 太贵;**Resolution-IV 2^(4−1) 分式(generator D=ABC)用 8 个 cell 使主效应不与二阶交互混杂,以一半算力恢复大部分信息**;另加预测最优角与 vanilla 基线 cell[^18^]。
  - 分轮隔离:逐轮只动一个组件族(LLM/感知/控制器),末轮对各族 top2 做全因子组合,380 trials[^29^]。
- **证据强度**:中(方法论为 DoE 经典;在 agent/LLM 系统的应用为单篇级)。
- **适用判断**:**memory/skill/harness 三层 MVP 默认"一次一类"(每代只允许一个资产层产生 child),交互只在小规模验证**:三层各取 {off, best} 即 2³=8 cell 全因子恰好在预算内;若某代要同时测两个层各 2 变体,用 2^(3−1) Res-IV 半分数(4 cell)先查交互再决定是否合并晋升。归因纪律:任何 cell 的增益报告必须标注"主效应"还是"含交互",禁止把组合增益记到单个资产头上。

### 5.2 按 (where × why) 分层的档案归因

- **来源**:GSME harness 论文[^8^]。
- **核心事实**:档案以 LLM 诊断的 (where 杠杆 × why 病理) 为键,credited 增益跨六域汇总显示"credited gains concentrate in runtime;…the boxed wrong-output column is attacked by all four levers but moved only, and only locally, by prompt: the where axis matters";多数 benchmark 最强 harness 是跨 cell 重组产物。
- **适用判断**:背景系统可把 EVO 档案键从"血缘"扩展为"(资产层 × 失效模式)",每 cell 只保留 gated elite;跨层组合只允许在各自 cell 已验证的 elite 间重组——这就是多资产共存时最经济的归因结构:**单资产 credit 在 cell 内配对确认,组合 credit 只测 elite×elite 的少量 cell**。

### 5.3 跨任务/跨资产迁移的归因警示

- **来源**:EvoSkill(SealQA 进化 skill 零样本迁移 BrowseComp +5.3pp)与 CoEvoSkills 的"迁移不如自进化"对照结论[^13^][^28^];ACE 跨域 playbook 迁移[^20^]。
- **适用判断**:memory/skill 资产声称跨任务收益时,必须在目标任务上单独过确认门,不得继承源任务的 credit;这与背景系统 EVO-TRAIN/PROMO 分区兼容,只需把"迁移声明"视为一次新的晋升申请。

---

## 6. 对背景系统的综合 MVP 蓝图(预算直觉汇总)

给定 E=16、单 episode 165–230k tokens、σ_episode≈0.4、已有假晋升前科:

1. **第 0 步(零评估成本)**:过程指标熔断(repeat-call 指纹、token 包络、stop-reason 分布)进 stage0;实测 parent 多次跑的 seed 级 ρ 与 σ_diff,据此公布本轮 MDE 承诺。
2. **选拔(E≈8–12)**:每层资产各产 2–3 个 child,parent 与全部 child 在相同 (case,seed) 对上做 K=2 配对评估(4 child × 2 对 = 8 episode);用配对分差做 SH 式淘汰保留 top1–2。此阶段只导航、不 credit。
3. **确认(E≈4–8)**:top1 与 parent 在 PROMO 池未用过的 (case,seed) 对上追加配对评估,合并后做 paired t(z≥1.96)或 PACE e-process(α=0.05,λ=0.5)——过线才晋升,未过线记"本轮无增益"(安全失败)。
4. **代际确认**:LOCKED-HOLDOUT 每代只评一次,报告 retention(holdout 增益/PROMO 增益);PROMO 池设查询预算,防自适应过拟合[^14^]。
5. **多资产**:每代只进化一层;跨层交互在 2³=8 cell(或 2^(3−1)=4 cell)上单独跑一轮隔离实验后再允许组合晋升;档案键=(资产层×失效模式)。
6. **论证口径**:论文式表述为"在 α=0.05、power=0.8 下本 MVP 可检测 MDE≥X;观测到 Y>X,配对检验 z=…,holdout retention=…"——这是经得起审查的最小完整证据链。

---

## 参考文献(含原文摘录)

[^1^]: PACE: Anytime-Valid Acceptance Tests for Self-Evolving Agents. arXiv:2606.08106, 2026-06-06. https://arxiv.org/abs/2606.08106 — "greedy acceptance commits 30-42% false and 10-33% harmful edits…greedy commits 13-21 spurious self-modifications per run (72-100% false) and degrades the most fragile agent by 4.9 points, while PACE holds at baseline";"matching greedy's held-out accuracy at sharply lower variance and about 18% lower evaluation cost".
[^2^]: RFC: PACE-style anytime-valid commit gate for SkillOpt promotion. github.com/gitmoot/gitmoot/issues/687, 2026-07-06 — "Commit when E ≥ 1/α (α=0.05). By Ville's inequality the false-commit probability is ≤ α at any stopping time (anytime-valid)";"its failure mode is correctly rejecting, which is the safe one";"Per-candidate, not familywise".
[^3^]: Best Arm Identification for Prompt Learning under a Limited Budget (TRIPLE). arXiv:2402.09723. https://arxiv.org/pdf/2402.09723.pdf — "a novel connection is established between prompt learning and fixed-budget best arm identification (BAI-FB)…Code available at https://github.com/ShenGroup/TRIPLE".
[^4^]: When Does Pairing Seeds Reduce Variance? arXiv:2512.24145, 2026-01-31. https://arxiv.org/pdf/2512.24145 — "paired evaluation achieves precision equivalent to roughly three to over one hundred times as many independent simulator runs";"r_eff = r/(1−ρ)";"Paired seed evaluation is weakly dominant in practice";seed correlations "consistently above 0.9".
[^5^]: Hyperband-based Bayesian Optimization for Black-box Prompt Selection. arXiv:2412.07820, 2024-12-10. https://arxiv.org/html/2412.07820v1 — "TRIPLE implements Successive Halving…we use the Hyperband (HB) algorithm because it will not evaluate all prompts and hedges against a poorly configured SH".
[^6^]: Fixed-Budget Best-Arm Identification with Heterogeneous Reward Variances (SHVar/SHAdaVar). UAI 2023, PMLR 216. https://proceedings.mlr.press/v216/lalitha23a.html — "allocates budget greedily based on overestimating the unknown reward variances…arms with higher reward variances are pulled more often";SH 误识别率 "P(Î≠1) ≤ 3 log₂K exp[−n/(8H₂ log₂K)]".
[^7^]: Stats for LLM Evals: Which Method? https://statsforevals.com/which-method.html — "Student's t-interval…0.950" 覆盖率恰达目标;"Wilcoxon Signed Ranks is our recommended default";"Friedman test as the default, with Wilcoxon…post-hoc";"Benjamini-Hochberg…greatest power among methods that maintained Type I error control".
[^8^]: Self-Evolving Agent Harnesses via Gated Semantic Quality-Diversity (GSME). arXiv:2607.13683, 2026-07. https://arxiv.org/pdf/2607.13683 — "a single-run gate credits a truly-neutral mechanism as a win ∼60% of the time (∼25% as a ≥3 pp 'win')";"Navigation (promotion, parent selection) uses K=3 mean pass@1 > vanilla; a credited gain…requires a paired 2σ test";"Pairing removes between-task difficulty variance, so the paired threshold is well below the unpaired one";sealed-test 增益 "+9 to +15.5 pp…retain 86–147% of the training gain";tree borrowing "reproduces the full K=3 promote/prune decision on all 14/14 nodes at −67% child-trial cost";"credited gains concentrate in runtime…moved only, and only locally, by prompt: the where axis matters".
[^9^]: VeRO: A Harness for Agents to Optimize Agents. arXiv:2602.22480, 2026-06-02. https://arxiv.org/html/2602.22480v4 — "The DatasetViewer tool exposes samples from permitted splits while enforcing access control";无约束对照:"the optimizer ingested both the question content and the ground-truth label"(turn 63–64);"9 distinct train evaluations against an 8-train budget"(自我合理化);"Prompt-only restrictions are insufficient even for state-of-the-art coding agents".
[^10^]: MIPROv2 | DeepEval 文档, 2026-08-24. https://deepeval.com/docs/prompt-optimization-miprov2 — "Every minibatch_full_eval_steps trials (and always on the final trial), MIPROv2 runs full-dataset scoring (score_pareto) on Optuna's current best trial";默认 num_trials=30, minibatch_size=25。
[^11^]: MIPROv2 Optimizer — dspy.rb, 2025-07-10. https://github.com/vicentereig/dspy.rb/blob/main/docs/src/optimization/miprov2.md — 预设 "light=6 / medium=12 / heavy=18 trials";"Measure the Ruby program on a held-out set before promoting an optimized artifact";另见 comet.com 汇总:"MIPRO typically converged within 100 to 300 evaluations, or 20 to 50 full dataset evaluations".
[^12^]: GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning. arXiv:2507.19457, 2025-07-25. https://arxiv.org/abs/2507.19457 — "GEPA attains optimal test set performance…with only 6,438, 678 (35× fewer), 6,858, and 2,157 rollouts";"the majority of GEPA's counted rollouts are allocated to the validation set";"GEPA requires just 737, 79, 558, and 269 training rollouts to reach optimal performance".
[^13^]: EvoSkill: Automated Skill Discovery for Multi-Agent Systems. arXiv:2603.02766, 2026-03-03. https://arxiv.org/abs/2603.02766 — "retaining only skills that improve performance on a held-out validation set while the underlying model remains frozen";OfficeQA +7.3pp(60.6→67.9),SealQA +12.1pp(26.6→38.7),SealQA→BrowseComp 零样本 +5.3pp;切分(SkillSmith 附录 D 复述 EvoSkill 协议):"10% for training (24 questions), 7% for validation (17 questions), and the remainder (205 questions) as a held-out test set that is never exposed during evolution"(https://arxiv.org/html/2606.01314v1)。
[^14^]: Dwork et al., Generalization in Adaptive Data Analysis and Holdout Reuse / The reusable holdout (Science 2015). arXiv:1506.02629 — "Reusing a holdout set adaptively multiple times can easily lead to overfitting to the holdout set itself";"n ~ √B·log m/τ²";合成实验中朴素复用 holdout 报出 63%+(真值 50%)。
[^15^]: How Many Samples Do We Need? A Toolkit for Power-Analysis (sk-power). LREC 2026. https://aclanthology.org/anthology-files/anthology-files/pdf/lrec/2026.lrec-1.353.pdf — "by fixing the desired power (e.g. 0.8) and the smallest meaningful improvement, one can determine how many evaluation examples are needed";"many reported improvements fall below standard power thresholds";引 Bowyer et al. 2025 "Don't use the CLT in LLM evals with fewer than a few hundred datapoints"。
[^16^]: Card et al. 2020, With Little Power Comes Great Responsibility. arXiv:2010.06595(经 [^15^] 与 ai.stackexchange.com/questions/45015 引用)——常用 benchmark 对小幅改进统计功效不足的经典论证。
[^17^]: Taming Randomness in Agent-Based Models using Common Random Numbers. arXiv:2409.02086, 2024-09-03 — "the first difference causes a significant loss of correlation due to stochastic random number noise"(配对收益依赖轨迹不发散)。
[^18^]: Auto-Configuring Scientific Simulators with Lightweight Coding-Agent Adapters. arXiv:2606.09774, 2026-06-25. https://arxiv.org/html/2606.09774v2 — "it cannot disambiguate main effects from two-factor interactions…We instead use a Resolution-IV 2^(4−1) fraction with generator D=ABC, which gives us eight cells whose main effects are not confounded with two-factor interactions, recovering most of the information of the full factorial at half the compute"。
[^19^]: A Practical Guide to AI-Assisted Research in Mathematics and Machine Learning. arXiv:2603.15914, 2026-03-08. https://arxiv.org/html/2603.15914v1 — "The one-variable-at-a-time commandment…A 2×2 factorial ablation (normalization × weight decay) confirmed the near-additivity, which would have been obscured by testing them jointly from the start"。
[^20^]: Agentic Context Engineering (ACE). arXiv:2510.04618 — "incremental delta updates…reducing both latency and compute cost";"ACE achieves 82.3% reduction in adaptation latency and 75.1% reduction in the number of rollouts as compared to GEPA";"in the absence of reliable feedback signals…both ACE and other adaptive methods such as Dynamic Cheatsheet may degrade"。
[^21^]: Progressive Delivery for AI Agents: Canary, Shadow, and Champion-Challenger Rollouts. niteagent.com, 2026-08-27. https://niteagent.com/blog/progressive-delivery-agents-2026/ — "Statsig recommends a staged approach: 2% → 10% → 50% → 100%";"pass CI evals, version the artifact immutably, split a small fraction of traffic…score it online against the champion, expand in stages…promote or roll back"。
[^22^]: HarnessOpt-Bench: Evaluating LLMs at Harness Optimization. arXiv:2608.06301(alphaxiv 概述), 2026-08-06 — "most optimizers' validation scores were overly optimistic compared to their final test scores, highlighting the importance of the hidden D_test partition"。
[^23^]: Monitoring Reasoning Models for Misbehavior and the Risks of Promoting Obfuscation. arXiv:2503.11926, 2025-03-14. https://arxiv.org/html/2503.11926v1 — "the Action Monitor…achieves only 60% recall overall…In comparison, the CoT monitor…achieves 95% recall";"an even weaker CoT monitor, GPT-4o-mini, is able to catch a nontrivial amount of reward hacking"。
[^24^]: Real-time token usage monitoring: what to track and what to alert on. predictionguard.com, 2026-06-26. https://predictionguard.com/blog/real-time-token-usage-monitoring-what-to-track-and-what-to-alert-on — "Repeat tool call rate…Three or more identical (tool_name, result_preview) fingerprints detected in a single session"。
[^25^]: AI Agent Evaluation: Metrics, Traces, Human Review (Confident AI). confident-ai.com, 2026-04-13. https://www.confident-ai.com/blog/definitive-ai-agent-evaluation-guide — "Define operating envelopes alongside judges…max steps, max tool calls, token budget, or wall-clock timeout — and fail the run when quality is fine but economics or latency are not"。
[^26^]: Managing AI Agent Drift (Maxim). getmaxim.ai, 2025-11-10. https://www.getmaxim.ai/articles/managing-ai-agent-drift-how-to-maintain-consistent-performance-over-time/ — "A rising planning token trend suggests over-exploration";"Higher counts with lower success rates signal poor routing";"Trajectory stability…Rising variance indicates prompt or policy changes"。
[^27^]: OWASP AISVS C09-08 Multi-Agent Isolation. github.com/OWASP/AISVS, 2026-04-22 — "comparing agent output embeddings against prior reasoning via cosine similarity (threshold ~0.98) to detect oscillation loops that token-level monitoring misses"。
[^28^]: Awesome-Harness-Self-Improvement(GitHub 清单,2026-07-08)与 skill 系统综述(OpenReview PDF)—— "Admission gates matter: curated skills beat unverified self-generated skills. Grade A";CoEvoSkills 消融 "removal of the surrogate verifier drops SkillsBench pass rate from 71.1% to 41.1%";SkillsBench v3:"self-generated skills are net-NEGATIVE on average (−1.3pp vs no-skill)";另列 misevolution(ICLR 2026)、reward tampering(Denison 2024)、METR "Many SWE-bench-Passing PRs Would Not Be Merged"。https://github.com/leezythu/Awesome-Harness-Self-Improvement ; https://openreview.net/pdf/6ec70a89fb81b2b84d1060e1cfb9c5a9de8f2453.pdf
[^29^]: Ablation Study of Multimodal Perception, Language Grounding, and Control(HRI 消融). arXiv:2605.00963, 2026-05-01 — "we vary one component family at a time while keeping all remaining modules…fixed…Finally…evaluate the best two candidates from each of the previous rounds in a full factorial combination study. In total…380 independent trials"。

---

## 附:检索覆盖与未查到项声明

- 独立搜索共 21 次(英 19 / 中 2;中文主要用于 EvoSkill/ACE 二手解读交叉验证)。
- **未查到**:(i) "paired comparison/CRN 在 LLM agent 选拔中的方差缩减幅度"的直接 LLM 场景实证(现有证据来自仿真器与 ABM,LLM 侧仅有 CI 方法仿真,幅度需自测 ρ);(ii) NAS 领域专门以"confirmation run"命名的晋升门论文(该实践以 Hyperband 末段全预算、MIPROv2 full-eval、champion-challenger 等形式存在,未发现统一术语的专文);(iii) memory 层资产的"最小 child 数/评估数"专文(ACE 未报首轮最小规模,仅有相对 GEPA 的成本比)。

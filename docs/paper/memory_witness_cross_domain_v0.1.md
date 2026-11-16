# Memory-RSI → Witness 跨域冷启动协议 v0.1

日期：2026-11-10 · 状态：预注册，先于任何新数据集跑批

## 1. 研究问题与边界

研究的是：通用软经验能否在新域仅作先验，通过执行轨迹提出候选检查，经独立样本验证后晋升为版本化 guard/witness，从而提高语义审计与修复能力。

不把以下现象混为同一结论：
- 目标值匹配不等于模型语义正确；
- 候选规则自测通过不等于跨实例有效；
- dev/gapcheck 晋升不等于冻结测试集上的端到端收益；
- 通用工程惯例可迁移，不代表旧域业务 witness 可直接迁移。

核心假设：完整 memory→witness 冷启动优于仅软 memory；若冻结测试上不能复现增益，则接受负结果，不移动判据。

## 2. 数据集角色

| 数据集 | 角色 | 可用真值 | 不能支持的结论 |
|---|---|---|---|
| RetailOpt | 旧域资产与机制来源 | 参照解、域 witness | 不作为本轮独立测试 |
| IndustryOR | 工程适配与调试 | 公开目标值、既有轨迹 | 已广泛使用，不作为本轮冻结测试 |
| **NLP4LP** | 独立标签下的固定制品审计与小规模端到端验证 | 专家 problem_info、变量级 solution、objective、parameters | 本地 ORThought 版本与其他发布版不完全相同，不直接宣称 SOTA；前沿方法已较饱和 |
| **MAMO-ComplexLP** | 主要新域端到端冻结评测与后续 SOTA 对比 | 211 题公开最优目标值 | 没有变量级金解，不能仅凭目标值匹配声称语义核验正确 |
| BWOR | 候补外部复现集 | 80 个最优目标值 + 2 个 no_optimal | 本轮不启动，避免摊宽 |

NLP4LP 本地 269 条中，按 problem_type、完整 solution/problem_info/parameters 过滤得到 237 个结构完整实例。专家 solution 用作干净参照；受控变异才提供独立构造的错误标签。

“专家提供”不自动等于可靠金标签。首轮 dev 发现 `prob_005` 把预算约束与目标函数写在不一致的两组变量上，参考解出现 `1e30` 变量与 `4e35` 目标值，模型实际无界却被标为 optimal。该例不得进入干净/错误分母，也不得算作候选 witness 失败。`nlp4lp_reference.py` 因此增加参考质量门：非标量、非有限值、绝对值超过 `1e12` 的异常参考解，以及专家解不能通过自身公式审计的样本均排除并记录原因。后续还需审计变量别名、整数类型和有界性，不能只做数值过滤。

参考审查采用两级流程：先用 `nlp4lp_reference_triage.py` 在看不到任何候选输出的情况下筛查自然语言、专家公式与解的一致性，再独立裁决为 `consistent / consistent_with_metadata_watch / ambiguous / inconsistent`。LLM 审查结果只用于召回，不得直接决定排除或充当真值。sealed 的参考审查必须先于候选输出生成，ambiguous 样本单列，原始与清洗后指标同时报告。

MAMO 的语义审计标签必须与公开目标值评分分开报告。没有独立参照或受控变异依据的样本，不进入“witness 检出率/误报率”的分母。

首批 validation 的小规模 TSP 中，`scripts/mamo_tsp_audit.py` 对 13 个实例穷举全部循环（4 城市 6 个、5 城市 24 个、6 城市 120 个），均得到与公开答案不同的最优值；原始 MAMO 文件与转换值一致。它们不得直接归为模型失败，也不得为了匹配公开值而“修复”。凡 TSP 归因和评分，必须同时给出原始榜分与独立穷举审计分，保留 tour 和审计文件；其他问题类型不得由这 13 例外推为统一的标签错误率。

## 3. 数据划分与暴露记录

使用 `scripts/memory_witness_split.py`，以固定字符串和 SHA256 对样本 ID 排序，生成互斥的 dev / validation / sealed test。脚本只写 ID，不复制题面。

- MAMO-ComplexLP：dev 60 / validation 50 / sealed 101。
- NLP4LP：dev 60 / validation 57 / sealed 120。
- MAMO `1,2` 已在数据筛选时阅读，强制进入 dev。
- NLP4LP `prob_000,prob_001,prob_003` 至 `prob_015` 已阅读，强制进入 dev。
- 已查看公开论文的聚合分数不属于逐题内容暴露。
- sealed test 的题面、解、失败案例不得用于提议、选择、调参或提示词修改；只在代码、资产和评测脚本冻结后运行一次。

清单：`data/memory_witness/slices_manifest.json`，含源文件哈希、样本 ID 文件哈希和暴露记录。

dev 的独立标签可用于 CEGIS 修复和候选资产晋升。validation 只能使用题面与冻结的 dev 经验生成新检查，`max_repairs=0`，独立标签只用于事后评分，且不得写回 memory。按问题 ID 划分的 validation 检验的是检查构造机制是否迁移，不是把某题的硬编码 witness 原样套到另一题。单实例资产与跨问题模板必须分开登记和解释。

## 4. 对照臂

所有臂使用同一 Qwen3.8-27B、同一开源求解器后端、相同最大修复轮数与求解时间上限。

1. **A0 无先验**：通用执行反馈，无跨域软 memory、无语义 witness。
2. **A1 仅软 memory**：通用工程/语义经验，无新域硬 witness。
3. **A2 直接迁移旧 witness**：在 A1 上直接套用 RetailOpt 域规则；不兼容时按预设 fail-open 记录，不能静默改规则。
4. **A3 零样本 LLM 检查**：LLM 写检查、沙箱执行、LLM 判决，不做资产晋升。
5. **A4 完整冷启动**：软 memory → 新域轨迹 → 候选检查 → 独立验证 → 版本化 witness → 确定性反馈修复。

实验分两层：
- **固定制品审计**：同一批干净/错误 solution artifacts 给各审计臂，测检出与误报，排除生成差异。
- **端到端修复**：各臂运行完整系统，测最终业务准确率与成本。另有共享初始候选的 repair-only 对照，用于隔离反馈本身的贡献。

## 5. 候选资产生命周期

```text
dev 成功/失败轨迹
→ 失败聚类或成功模式蒸馏
→ 一个结构触发条件 + 一个候选检查（单一机制）
→ 沙箱安全检查
→ LLM 自提 must_fire / must_pass（仅作自测，不作真值）
→ dev 独立参照与受控变异验证
→ validation 靶/win 复验
→ 注册资产版本、代码哈希、来源与 activation 日志
→ 冻结后才允许进入 sealed test
```

单条检查晋升门槛：
- must_fire 与 must_pass 均按预期执行，脚本异常不得算作检出；
- dev 独立构造错误检出至少 60%，且干净参照误报为 0；
- validation 独立构造错误检出至少 50%，干净参照误报不超过 5%；
- 端到端候选条款沿用靶/win 纪律：dev 靶增益至少 +8pp、validation 至少 +5pp，win 变化不低于 −3pp；样本不足时只报案例，不晋升。

每条资产记录 `unit_id / parent_id / origin / trigger / code_hash / status / metrics`。检查器崩溃、超时、无证据统一记为 UNKNOWN 并 fail-open，不能计为 INVALID。

最终评分审计器与学习产生的 witness 分离并冻结版本，避免评分规则随进化一起变化。

## 6. 指标与有效线

固定制品：
- 错误检出率、干净解误报率、UNKNOWN 率；
- 按 artifact 配对的 McNemar 检验及置信区间；
- 按变异机制与问题类型分层，禁止把同一变体的数值扰动当独立任务。

端到端：
- MAMO：公开 benchmark accuracy，目标值绝对误差 ≤0.1；语义成功另报，不与目标值匹配混称；
- NLP4LP：独立审计后的语义成功与公开目标值指标分别报告；
- LLM 调用数、token、求解次数、墙钟时间和每成功成本。

完整机制有效的预注册条件：A4 在 sealed test 上优于 A1，McNemar `p<0.05`，且误报率 ≤10%。固定制品与端到端结论分别命名；任一指标不达标都如实报告，不通过换分母或事后改阈值挽救。

## 7. SOTA 对比门槛与口径

只有 A4 达到上述有效线才启动 SOTA 对比。

MAMO-ComplexLP 优先对齐 COOPA：同一 211 题、目标值绝对误差 ≤0.1。COOPA 论文报告 GPT-5.2 为 55.9%，GPT-5.2/IndustryOR 为 76.0%。来源：https://arxiv.org/html/2606.27611v1

LLMOPT 公开仓库报告 Qwen2.5-14B + self-correction 在 Mamo Complex 上 SA 85.78%，NLP4LP 86.49%。其数据修订、求解预算和容差必须先核清，不能直接与 COOPA 或本系统数字混排。来源：https://github.com/antgroup/LLMOPT

SOTA 对比同时报告基座模型、数据版本、评分公式、调用/token/墙钟成本；不同基座只作参照，不宣称同模型公平优胜。

## 8. 实现纪律与负结果

- `scripts/mem_selective.py` 的顶层 `sub_edges` 路径问题已使旧选择性注入对照失效；本轮必须先修 schema 适配并记录 activation，不得沿用旧“纯 trigger 最优”结论。
- embedding 臂只有在 optional 条款数大于 top_k 时才构成真实检索对照。
- 若 A4 无效，按候选提出、独立标签、规则覆盖、判决纪律、修复反馈、跨域资产迁移六层归因，结题负结果而非继续扩大数据集。
- v4 判官训练是独立后台线；不得根据本协议的新数据集结果修改其训练数据或评测集。

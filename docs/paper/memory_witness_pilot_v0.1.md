# Memory→Witness 跨域冷启动首轮结果 v0.1

日期：2026-11-11 · 状态：dev/validation 完成，sealed 未接触；主判据未达标，SOTA 对比未启动

## 1. 最小闭环

实现路径：

```text
题面 + solution schema
→ Qwen 生成确定性检查脚本
→ 专家解/受控变异独立评分
→ dev 反例引导修复（CEGIS）
→ dev-passed 检查作为冻结 memory
→ 未见问题只生成，不给标签、不修复、不写回
→ 固定制品审计与逐题配对检验
```

代码：`scripts/nlp4lp_reference.py`、`scripts/memory_witness_cegis.py`、`scripts/memory_witness_analyze.py`。

NLP4LP 使用 dev 60 / validation 57 / sealed 120 的 ID 划分。首轮只纳入当前可独立审计的标量参考：dev 26 题/121 制品、validation 30 题/145 制品。其余按非标量、缺失变量、异常参考等原因排除，不伪造标签。

## 2. dev 晋升

26/26 有效 dev 问题达到 `detection≥60% + clean FP=0 + UNKNOWN=0`。

- prob_191、prob_204 初始检查为 100% 检出、100% 干净误报；
- 经一轮 dev 反例修复后均达到 100% 检出、0 误报；
- prob_005 因专家模型变量别名不一致、实际无界且解量级异常，已排除，未计为候选失败。

这说明 CEGIS 有实际修复作用，但 dev 通过不等于未见问题有效。

## 3. validation 主结果（保守口径，全部 30 题）

| 指标 | 无 memory | 冻结 dev memory |
|---|---:|---:|
| 错误检出 | 89.6% (103/115) | **99.1% (114/115)** |
| 干净解误报 | 23.3% (7/30) | **20.0% (6/30)** |
| UNKNOWN | 9.7% (14/145) | **0% (0/145)** |
| 逐题过门率 | 66.7% (20/30) | **80.0% (24/30)** |

配对结果：

- memory 独有检出 11，baseline 独有检出 0，McNemar **p=0.0009766**；
- FP 变化为 memory-only 1 / baseline-only 2，`p=1.0`；
- UNKNOWN 从 14 降至 0。

**判定：检出提升显著，但误报率 20% 超过预注册 10% 红线，主判据未通过。**

无 memory 的 prob_016 曾出现“所有样本都报类型错误”的假全检出。修正口径后，这类无证据输出记 UNKNOWN，不计 TP/FP；不能再用全拦抬高检出率。

结果：`work/memory_witness/validation_full_analysis.json`。
图：`paper_icml2027/figures/memory_witness_validation_full.png`。

## 4. 参考冲突与敏感性分析（不是主结果）

逐例审查发现五题存在自然语言与专家公式/变量类型冲突：

- prob_088、prob_263：题面要求严格“更大/更多”，专家代码使用 `>=`，干净解落在等号边界；
- prob_090、prob_130：数据标为 IP，但专家变量为 continuous 且参照解为分数，与可数瓶数/餐数的业务理解存在冲突；
- prob_094：题面写“at least 300”，专家代码为 `<=300`，属于方向/措辞冲突。

将这五题整体作为 `reference ambiguity` 做敏感性排除后：

| 指标 | 无 memory | 冻结 dev memory |
|---|---:|---:|
| 错误检出 | 88.5% (85/96) | **100% (96/96)** |
| 干净解误报 | 12.0% (3/25) | **4.0% (1/25)** |
| UNKNOWN | 11.6% (14/121) | **0%** |
| 逐题过门率 | 76.0% (19/25) | **96.0% (24/25)** |

检出配对仍为 11:0，`p=0.0009766`。

这些数字只能作为**参考清洗敏感性证据**，不能用来替代保守主结果或事后过线。prob_104 是明确的真实检查错误：检查器把 makespan 的最大时间误加成总时间。baseline 的 prob_229、prob_259 也属真实检查错误。

结果：`work/memory_witness/validation_reference_sensitivity.json`。

## 5. MAMO-ComplexLP：真实变量类型错误与 guard 重放

前四个 dev 样本的基线 z2 在公开目标值绝对误差≤0.1 下为 0/4。ids 1、2 的代码使用连续变量，目标值分别为 53.896/71.071；只改成整数重解后精确得到公开值 57/72。

消融：

| 方法 | 同一四题正确数 | 备注 |
|---|---:|---|
| z2 基线 | 0/4 | 全部连续变量建模 |
| 软“可数单位”规则 | 2/4 | ids 1、2 仍连续并自我合理化 |
| 软规则+硬 guard 在线组 | 4/4 | 只有 1 次真实 guard 激活，含采样影响 |

为去掉初始解采样差异，固定基线代码做 guard 反馈重放：原始 0/4 → **4/4**，四次连续实现均被 guard 拦截，修复后整数模型命中公开值。初版重放器的相对 sandbox 路径错误已修正，最终执行结果在 `work/memory_witness/mamo_guard_replay_v2.jsonl`。

这只是四个 dev 案例，不构成统计结论，也没有覆盖真正连续变量的 win-safe 验证。

## 6. 当前结论与下一步

1. 冻结经验最稳定的收益是输出契约、减少 UNKNOWN 和提高真实检出，不是“所有语义检查都更可靠”。
2. 原始误报仍是主要瓶颈；需要更保守的整数/严格比较假设和更完整的参考质量审计。
3. MAMO 的变量类型遗漏是独立确认的真实机制，软提示不稳定，硬 guard 值得扩展；但必须先证明对连续变量无误伤。
4. sealed 继续封闭。下一轮先完成参考冲突盲审、MAMO dev/validation 的多样本四臂与 win-safe 消融，达到预注册有效线后才启动 SOTA 对比。

回归：Python 3.9 下 100 项通过、1 项因既有 `dict | None` 语法不兼容而排除；该项在 Python 3.12 下单独通过。trigger 修复后有 9 项相关测试通过，dev 替代结构激活从错误的 0/40 修正为 38/40。


## 7. MAMO 混合变量 win-safe 复核（2026-11-11）

按题面预先选择 8 个 dev 问题：2 个清晰可数题（24、209），4 个连续题（197、202、205、208），2 个混合变量题（140、194）。

- 零样本作者器对全部 8 题选择不启用整数 guard；其中对“linear programming”直接推断连续，显示过度保守。
- 加入前四题的独立反例 memory 后，209 改为提议整数规则，但证据使用省略号，未通过原文校验；24 仍被误判为连续。
- 对 24 进行独立 CEGIS 复核：连续目标 23.3249（错误），整数重解 24.0（命中），题面证据可定位，`must_fire/must_pass` 均通过，才允许晋升。
- 固定相同基线代码重放：基线 **7/8 → 8/8**，只有 24 被 guard 拦截并修到 24.0；其余 7 个已正确样本全部保持正确，连续/混合变量零误伤。

资产版本：`work/memory_witness/mamo_asset_registry_v0.1.json`，含 memory/config/replay 哈希、逐题状态与反例证据。该结果支持“保守作者 + 独立反例晋升”比单纯文本判断更可靠，但仍只是 dev 机制验证，未触及 validation/sealed，也不构成 SOTA 结论。


## 8. MAMO validation 分层迁移复核（2026-11-11）

在 validation 另选 8 个未见问题：可数 10、13、206、207，连续 117、204，混合 143、193。基线为 **6/8**，只有 10、13 错误。

- 冻结 dev memory 的作者器正确识别 206（员工）和 207（帆船）为可数决策，连续/混合题均关闭 guard；10、13 仍需独立反例复核。
- 13 暴露 `addVar` 未写 `vtype` 时默认连续的问题。guard 已改为 AST 检测默认类型，反例转换也改为显式补 `vtype="I"`，新增回归测试通过。
- 独立整数重解：10 从 8.2727→9.0，13 从 25.3565→27.0，均命中公开值，且 `must_fire/must_pass` 通过。
- 固定基线代码重放：**6/8 → 8/8**。10、13 修复；207 触发整数修复但保持 78450 不变；其他已正确样本零误伤。

资产版本：`work/memory_witness/mamo_validation_asset_registry_v0.1.json`。这表明机制可从食物迁移到员工/帆船，并尊重连续与混合变量，但仍只是 validation 的分层小样本，不是 sealed 终验或 SOTA 结论。


## 9. MAMO validation 多种子复核（2026-11-11）

对同一组 8 题增加 seed 42、43，代码哈希确认不同种子产生了不同实现，不能把相同目标值误解为缓存复用。

| 采样 | 基线正确 | 冻结重放正确 | 改善 | 基线 LLM 调用 | 重放修复调用 |
|---|---:|---:|---|---:|---:|
| unseeded | 6/8 | **8/8** | 10、13 | 10 | 3 |
| seed 42 | 5/8 | **8/8** | 10、13、206 | 10 | 4 |
| seed 43 | 6/8 | **8/8** | 10、13 | 11 | 3 |

所有采样中，已正确样本均未因 guard 变差。seed42 的 206 排班从 22.333 修到 23，说明变量类型机制并不只修食物题，也能处理排班中的连续员工变量。

结果：`work/memory_witness/mamo_validation_multiseed_analysis.json`。当前成本记录包括 LLM 调用数与基线延迟；重放 JSONL 尚未持久化修复延迟，后续成本图需补齐该字段，不能用不完整的墙钟数据比较总成本。


## 10. MAMO validation 四臂对照（seed 42）

| 臂 | 目标值正确率 | LLM 调用 | 基线延迟(s) | 关键说明 |
|---|---:|---:|---:|---|
| A0 无先验执行修复 | 62.5% (5/8) | 15 | 211.5 | 无 memory/witness |
| A1 仅软 memory | 87.5% (7/8) | 11 | 236.5 | 修复 10、13、206，但把 117 从 81 错到 149 |
| A2 直接迁移 RetailOpt witness | 62.5% (5/8) | 12 | 175.5 | 8/8 均为 `unknown_schema` 并 fail-open，无有效修复 |
| A4 完整冷启动 | **100% (8/8)** | 12 | 219.3 | **在线 guard 激活为 0** |

A4 相对 A0/A2 为 3:0，`p=0.25`；相对 A1 为 1:0，`p=1.0`，样本小，均不显著。尤其不能把 A4 相对 A1 的差异归因于硬 guard，因为本轮没有 guard 激活。guard 的因果证据只能来自固定初始代码重放，而不是比较两次独立采样的 A1/A4。

A2 证明旧域 witness 的 schema 不能直接使用，软经验也可能误伤连续/网络流问题；这强化了“软经验只作先验，独立验证后才晋升”的必要性。

结果：`work/memory_witness/mamo_four_arm_validation_analysis.json`。
图：`paper_icml2027/figures/mamo_four_arm_validation.png`（已标注在线激活为 0）。


## 11. 参考一致性盲审与裁决（2026-11-11）

新增 `scripts/nlp4lp_reference_triage.py`，只向审查器提供题面、专家公式与专家解，不提供任何候选 witness 输出。对 5 个已知冲突、prob_104 和 3 个普通对照进行先导盲审。

结果：

- 五个已知冲突均被标出，支持其用于**召回筛查**。
- prob_104 被判为可疑，但复核后确认 makespan 是合理约定，保留 clean，且候选将其加成总时间仍是明确误报。
- prob_003/006 因 IP 元数据与 continuous 变量被标出，但其干净解为整数且满足约束，记为 `consistent_with_metadata_watch`，不自动排除。

因此，LLM 盲审不能直接充当金标签或自动删样本。采用两级流程：

```text
盲于候选的参考审查（高召回筛查）
→ 独立复核题面/专家公式/解
→ consistent / consistent_with_metadata_watch / ambiguous / inconsistent
```

原始输出：`work/memory_witness/reference_triage_pilot.jsonl`。
最终裁决：`work/memory_witness/reference_adjudication_pilot.json`。
后续 sealed 的参考审查必须先于任何候选输出生成，ambiguous 样本继续单列，不能用审查器分数替代独立裁决。


## 12. 全部 validation 参考审查与裁决（2026-11-11）

对全部 30 个 validation 问题运行盲审，原始输出为 27 个 ambiguous、1 个 inconsistent、2 个 consistent。若直接采用 LLM 标签，几乎所有 IP 元数据问题都会被排除，因此逐题复核了解值、约束和目标。

最终裁决：

- **6 个 reference ambiguity**：088、090、094、114、130、263；
- **20 个 consistent_with_metadata_watch**：主要是 IP 元数据与 continuous 并存，但干净解实际为整数；
- **4 个明确 clean**：104（合理 makespan）、193（LP 连续合理）、194、253；
- prob_207 的 inconsistent 是审查器算术误判，`2.50×30 + 3.55×40 = 217`，改判 consistent。

全量裁决：`work/memory_witness/reference_adjudication_validation_full.json`。

更新后的敏感性分析（排除 6 个完整问题，而非只删干净解）：

| 指标 | 无 memory | 冻结 dev memory |
|---|---:|---:|
| 错误检出 | 88.0% (81/92) | **100% (92/92)** |
| 干净解误报 | 12.5% (3/24) | **4.2% (1/24)** |
| UNKNOWN | 12.1% (14/116) | **0%** |
| 逐题过门率 | 75.0% (18/24) | **95.8% (23/24)** |

检出配对仍为 11:0，`p=0.0009766`；FP 配对不显著。

结果：`work/memory_witness/validation_reference_sensitivity_v2.json`。
这仍然只是清洗后的敏感性分析，不替代原始 20% 误报的主结果。sealed 必须先完成参考裁决再生成候选，禁止事后按候选结果选择排除项。


## 13. MAMO 全量 validation 与 TSP 参考审计（2026-11-11）

完成全部 50 个 validation 基线、memory 作者、独立反例与固定代码重放。原始榜分与独立 TSP 审计分并列：

| 指标 | 基线 | memory→witness 重放 |
|---|---:|---:|
| 原始正确率 | 46.0% (23/50) | **62.0% (31/50)** |
| TSP 穷举审计后正确率 | 72.0% (36/50) | **88.0% (44/50)** |

两种口径均改善 8 题、无误伤，McNemar `p=0.0078125`。改善来自 4、9、10、13、18、32、35、36 的可数变量修复；其余失败没有被强行整数化。

成本：基线 64 次 LLM 调用/1027.9s；重放 13 次修复调用/83.3s，token usage 23,848。198 连续三轮 guard 后仍无有效解，已标为部署拒绝，说明候选作者通过仍需重放淘汰。

TSP 参考审计：13 个实例穷举全部循环均与公开答案不一致，原始 MAMO 文件与转换值一致。它们不再直接计为模型失败，原始分与审计分并列报告，不把审计分用于 COOPA 原始榜单排名。

结果：`work/memory_witness/mamo_val50_replay_analysis.json`。
图：`paper_icml2027/figures/mamo_val50_replay.png`。
审计：`work/memory_witness/mamo_tsp_reference_audit.json`。

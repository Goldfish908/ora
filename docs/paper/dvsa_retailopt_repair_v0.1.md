# DVSA / RetailOpt dev 共享初始自然修复 v0.1

状态：20 个 saved dev 场景的四臂 repair-only 完成；不是全 dev40 新采样、frozen 或 SOTA 结果。

## 1. 协议与评分

所有臂使用同一初始代码、数据和解，最多一次反馈/自评修复和一次共享执行恢复。A0/A1 每题自评；A2/A3 在数值违规时修复，无解时共享执行反馈，satisfied 时零调用。执行恢复只处理执行/API/输出失败，单独归因。

- A0 no-memory：无资产文本的自评。
- A1 text-memory：需求平衡与期初老库存两条文本的自评。
- A2 DVSA：同两条文本 + 对应可执行资产的数值违规反馈。
- A3 direct-legacy：同两条文本 + 完整旧 witness 反馈。
- A3 配置已纠偏；仅旧 witness 无文本的 legacy-only 结果单独归档，不进入正式 A3。

业务正确 = 冻结旧 witness 可行 + 参考目标值相对误差≤0.1%。这是当前解级参考口径，不是模型语义等价。A3 同时使用旧 witness 作反馈，因此它不是独立语义金标。

## 2. 主要结果

共享初始为 **6/20 业务正确**；7 个语义可行，6 个目标值正确。

| 臂 | 业务正确 | 语义可行 | 改善 | 修坏 win | LLM 调用（含执行恢复） |
|---|---:|---:|---:|---:|---:|
| A0 no-memory | 5/20 | 5/20 | 0 | **1** | 21 |
| A1 text-memory | 17/20 | 18/20 | 11 | 0 | 22 |
| A2 DVSA | **18/20** | **19/20** | **12** | **0** | **15** |
| A3 完整旧 witness | 17/20 | **19/20** | 11 | 0 | 13 |

逐题 McNemar：

- A2 对 A0：13:0，`p=0.000244`。
- A2 对 A1：1:0，`p=1.0`。
- A2 对 A3：1:0，`p=1.0`。

**A2 的绝对结果最强，但相对 A1/A3 没有显著质量优势，不启动 SOTA。**

A2 对初始 6 个业务正确解的门控误报为 0/6；A1/A2/A3 都没有修坏初始 win。A0 将 `retail_f2_price_band_tight_v0` 从正确修错，说明无约束自评存在退化风险。

## 3. 语义触发与失败归因

A2 的触发分布为：10 个 `dvsa_violation`、3 个执行失败、7 个 `no_call`。

- **10 个语义触发案例最终全部业务正确**，其中 2 个需要执行恢复。例如首次修复曾误用不存在的 `Variable.setUb()`，统一执行恢复后才得到可执行正确模型。
- 3 个执行失败案例中 2 个最终恢复；这些计入完整系统收益，但不能全部归功于语义资产。
- `retail_f2_circular_sub_v4`：当前解语义可行但目标次优，A2/A3 satisfied 不触发，A1 自评也未改善。说明**解级可行不等于最优，witness gate 不负责所有目标质量问题**。
- `retail_f2_ultra_fresh_v0`：所有臂均未得到有效解，是共同执行/建模失败，不能用 witness 检出率掩盖。

A2 与 A3 的业务差异只有一题。旧 witness 无文本的 legacy-only 敏感性为 12/20，正式 A3 加入同文本后为 17/20；该差异只说明反馈组合的重要，不与正式 A3 混用。

## 4. 成本（repair-only 增量）

| 臂 | LLM 调用 | 求解调用 | 总 tokens | LLM 延迟(s) | 求解墙钟(s) |
|---|---:|---:|---:|---:|---:|
| A0 no-memory | 21 | 21 | 231,799 | 1332.837 | 18.479 |
| A1 text-memory | 22 | 22 | 260,532 | 1538.361 | 16.975 |
| A2 DVSA | 15 | 15 | **173,704** | **848.556** | **11.269** |
| A3 完整旧 witness | **13** | **13** | 196,394 | 1206.949 | 14.491 |

A2 比 A1 少 7 次调用，并减少 token/延迟；A3 调用更少，但输出 token 与 LLM 延迟高于 A2。不能简单写成“DVSA 永远调用最少”。初始生成来自已有缓存，本表不是完整系统总成本。

## 5. 与固定制品的联合结论

固定制品中，A2/A3 均为 10/10 检出、0/6 误报；A1 为 9/10、2/6 误报，A0 为 6/10、2/6 误报。文本误报已核实为漏读 freshest 销售和虚构 Premium 库存。

自然修复中，A1 已经达到 17/20，说明**文本经验本身有很强修复能力**；A2 的价值应限定为确定性证据、保守门控、较少无效自评和特定错误上的稳定反馈，而不是“只有 DVSA 能修复”。A2 对 A1/A3 的一题差异均不显著，后续必须在 validation/frozen 上检验，而不能只选择有利 dev 数字。

## 6. 产物

- 自然修复分析：`work/dvsa/retailopt_repair_analysis/analysis.json`
- 图：`/home/hewj13/paper_icml2027/figures/dvsa_retailopt_dev_repair.png`
- 固定制品报告：`docs/paper/dvsa_retailopt_fixed_v0.1.md`
- 固定制品图：`/home/hewj13/paper_icml2027/figures/dvsa_retailopt_dev_fixed_arms.png`
- legacy-only 敏感性：`work/dvsa/retailopt_repair_analysis_legacy_only/analysis.json`

限制：20 题是同一 saved replay 的 dev 子集；只覆盖 C-INIT/C-DEMAND 两类资产；没有多种子或独立人工金标。后续 BWOR validation/frozen 保持封闭，不能根据这些 dev 结果移动门槛。

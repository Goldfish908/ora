# DVSA / BWOR dev 共享初始自然修复结果 v0.1

日期：2026-11-11。状态：开发集完成；未触 validation/frozen；不启动 SOTA。

## 1. 实验设置

样本仍为 7 个参考合格的 BWOR dev 问题，所有臂共享参考变量声明。该强结构先验使初始模型已经较好，不能解释为无辅助 NL 建模能力。

- 每题只生成一份初始 DSL 模型，所有臂使用相同模型哈希与 SCIP 解。
- A0 no-memory：一次无模板文本的自评修复。
- A1 text-memory：一次带相同模板文本的自评修复。
- A2 DVSA：使用独立 binding 的确定性反馈；有数值违规才触发语义修复；没有解时允许共享执行失败恢复，但单列为 `execution_failure_unknown_semantics`。
- A3 direct-legacy：复用 A1 轨迹并记录 RetailOpt witness `unknown_schema`，不是一次独立采样；独立运行等价成本与 A1 相同。
- 每臂最多一次修复调用。独立参考只用于事后评分，不进入 prompt 或反馈。

业务正确定义为：当前返回解通过独立参考的约束/变量域/目标重算审计，且与公开答案绝对误差不超过 0.1。它仍是**当前解级业务正确**，不证明整个模型语义等价或所有数据点最优。

首轮 prompt 未显式要求 `schema_version` 字段，导致 7 个输出统一 invalid；该批保留在 `work/dvsa/bwor_repair_promptbug0/`，不计入实验结果。修正契约后重新生成共享初始候选。

## 2. 初始状态与严格 schema 结果

共享初始为 **6/7 业务正确**。BWOR-011 因引用不存在的 `cap_I` 而无解，其余六题已正确。

| 臂 | 业务正确 | 改善 | 修坏 win | 独立运行修复调用 | 实际修复 tokens |
|---|---:|---:|---:|---:|---:|
| A0 no-memory | **7/7** | 1 | 0 | 7 | 46,681 |
| A1 text-memory | 6/7 | 0 | 0 | 7 | 48,312 |
| A2 DVSA | 6/7 | 0 | 0 | **1** | **4,650** |
| A3 direct-legacy | 6/7 | 0 | 0 | 7（复用 A1，实际新增 0） | 48,312（等价） |

严格口径下：

- A2 对 A1：0:0，`McNemar p=1.0`。
- A2 对 A0：0:1，`p=1.0`。
- A2 对 A3：0:0，`p=1.0`。
- 六题 A2 均为 `no_call`；BWOR-011 为执行失败恢复，不是 `dvsa_violation`。
- **没有任何一次 DVSA 语义违规触发的自然修复。**

A0 修复了 BWOR-011；A1/A2 的响应都省略了空 `data` 对象，严格验证报 `data must be an object`，因此没有进入求解。这是输出格式失败，不应误记为语义反馈把模型修错。

## 3. 空 data 格式敏感性（不替代严格主结果）

两份失败响应均没有使用任何 `data.path`，只是完全省略 `data` 字段。通用默认空参数表不改变变量、约束、系数或目标表达式；若仍存在缺失 `data.path`，求解依旧失败。

按这一规则对已有响应做零新增 LLM 调用的确定性重评，四臂均为 **7/7**，六题 A2 仍为 `no_call`，BWOR-011 仍只是一次执行恢复。A2 对 A1 的配对结果仍为 0:0、`p=1.0`。

该敏感性说明严格失败来自过强的 schema 默认值，而非语义模型错误。后续 validation/frozen 可以预先固定 `missing data -> {}` 的格式规则，但不能用敏感性结果改写本轮严格主结果。

## 4. 成本与 win-safe

- 共享初始成本：7 次调用、30,067 tokens、219.686s 生成延迟。
- 严格与敏感性下，A2 均只进行 1 次修复调用，A0/A1 均为 7 次。
- A2 修复阶段为 4,650 tokens / 21.2s；A1 为 48,312 tokens / 235.956s。
- A2 相对 A1 减少的是**不必要的自评调用**，不是已证明的等质量语义修复成本。
- 两种口径下所有臂的 `harmed_win` 都为 0，六个初始 win 全部保留。
- 结果图采用独立运行等价调用，避免把 A3 的响应复用误画成零成本优势；共享运行实际调用另存于分析 JSON。

## 5. 结论与边界

1. **不支持自然修复增益主张**：A2 没有语义触发修复，且两种口径对 A1 均无显著业务正确率差异。
2. **支持有限的保守 gate 信号**：在 7 个参考合格 dev 问题上，A2 跳过 6 次自评且不伤 win，并以一次执行恢复达到与 A1 相同的业务结果。
3. **样本与先验限制**：只有 7/16 个参考合格问题，共享变量 schema 强、初始正确率高；不能外推到全 dev、frozen 或无 schema 的完整 pipeline。
4. **固定制品与自然结果不可混用**：固定制品中 A2 的 44/44 检出主要证明执行器能发现受控错误，不能用来补足这里缺失的自然修复证据。
5. **不启动 SOTA**：没有 frozen 业务正确率提升，也没有自然语义修复事件。闭源模型不参与资产更新或调参。

## 6. 产物

- 严格分析：`work/dvsa/bwor_repair_analysis/analysis.json`
- 格式敏感性分析：`work/dvsa/bwor_repair_normalized_analysis/analysis.json`
- 严格图：`/home/hewj13/paper_icml2027/figures/dvsa_bwor_dev_repair_strict.png`
- 敏感性图：`/home/hewj13/paper_icml2027/figures/dvsa_bwor_dev_repair_normalized.png`
- 共享初始与逐臂轨迹：`work/dvsa/bwor_repair/dev/`

下一步转向 RetailOpt dev 的自然失败四臂，以寻找真正需要语义修复的样本；同时保留 BWOR validation 作为保守 gate 的迁移检查，不把 dev 的无增益结果隐藏。

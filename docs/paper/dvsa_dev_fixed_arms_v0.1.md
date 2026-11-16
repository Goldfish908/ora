# DVSA / BWOR dev 固定制品四臂结果 v0.1

日期：2026-11-11。状态：开发集机制验证完成；未触 validation/frozen；不是 SOTA 或端到端自进化证据。

## 1. 范围与独立信息

本实验只纳入当前可形成候选独立参考的 7/16 个 BWOR dev 问题：BWOR-001、011、042、043、062、066、069。其余问题仍是参考冲突、来源不合格、不可行或规格失败，不能从记录中删除后宣称全 dev 有效。

- 参考作者不看候选解、文本 memory、DVSA binding 或公开答案；公开答案只在求解后核对。
- BWOR-001 的首版参考因固定配比产生结构错误，修订为 9 个原料流量变量后命中 5450；042、062 只修正规格语法后命中公开答案。
- 独立 binding 作者看题面、参考变量声明和通用模板文本，**不看参考约束、参考目标表达式、公开答案或参考导出 binding**。
- 因此本实验是 **shared-schema conditional audit**。变量分解是各臂共享的强先验，不证明从原始 NL 自动获得该分解的能力，也不构成同口径全 pipeline SOTA。

参考生成汇总：`work/dvsa/bwor_reference/dev/summary.json`。

## 2. 制品与盲评纪律

7 题共 51 个唯一解制品：44 个受控错误、7 个干净参考解。

- 变量受控变异后重新计算报告目标，避免“只重算目标”的检查器对所有变量变异都报警。
- 目标误报作为单独机制构造。
- 完全相同的解只计一次；多规则共享一个解时保留多个参考标签，但不增加制品分母。
- LLM 盲评使用内容哈希的不透明 ID 和打乱顺序；不显示 clean/wrong、参考规则或公开答案。
- INVALID 必须有数值证据，否则记 UNKNOWN；VALID 附带违规也记 UNKNOWN；重复输出 ID 记 UNKNOWN。
- DVSA binding 由同一题面+schema+模板文本独立生成，随后零 LLM 执行。行为规则覆盖要求 binding 在所有制品上的激活轨迹与独立参考规则一致，不能只靠碰巧报警。
- A3 直接迁移 RetailOpt witness，schema 不兼容记 `unknown_schema` 并 fail-open；UNKNOWN 不算检出或正确通过。

## 3. 主要结果

| 臂 | 错误检出 | 干净解误报 | UNKNOWN（全部制品） | 完整检出的题数 |
|---|---:|---:|---:|---:|
| A0 no-memory LLM 评审 | 86.4%（38/44） | 0%（0/7） | 0/51 | 1/7 |
| A1 文本 memory LLM 评审 | 88.6%（39/44） | 0%（0/7） | 0/51 | 2/7 |
| A2 独立 binding + DVSA 执行 | **100%（44/44）** | **0%（0/7）** | **0/51** | **7/7** |
| A3 直接旧 witness | 0%（0/44） | 0%（0/7） | 51/51 | 0/7 |

逐制品精确 McNemar：

- A2 相对 A0：独有改善 6、反向 0，`p=0.03125`。
- A2 相对 A1：独有改善 5、反向 0，`p=0.0625`。
- 干净误报两组均无discordant，`p=1.0`。

**A2 相对 A1 未达到预注册 `p<0.05`。** 固定制品的统计显著性也不能替代最终逐题端到端业务正确率门槛。

A2 相对 A1 多检出的五项为：4 个 `OBJECTIVE` 误报制品和 BWOR-066 的 `C06`。因此增益主要来自确定性目标重算，另有单条约束案例；不能外推为对所有自然建模错误都更有效。

A3 的 100% UNKNOWN 只说明 RetailOpt 的特定数据/解 schema 不能直接复用，不说明旧域 witness 在 RetailOpt 上无效。

## 4. 成本

| 臂 | LLM 调用 | 总 tokens | 生成延迟合计(s) |
|---|---:|---:|---:|
| A0 no-memory | 7 | 49,940 | 313.979 |
| A1 文本 memory | 7 | 57,703 | 369.611 |
| A2 DVSA binding 生成 + 确定性执行 | 7 | **37,451** | **243.849** |
| A3 旧 witness | 0 | 0 | 0 |

A0/A1 的 BWOR-011、042 是对已有响应的去重重评，未新增调用；表中仍计原始生成成本。后续五题为新生成。A2 每题一次 binding authoring，执行本身不调用 LLM。这里比较的是固定制品审计成本，不是每成功修复成本。

## 5. 解释边界

1. **开发选择偏差**：只有 7/16 个参考合格问题进入本分母，不能写成 BWOR dev16 或全 73 题的普遍准确率。
2. **共享 schema 偏强**：各臂都获得参考变量声明，测的是条件于变量分解的语义审计，不是端到端变量发现。
3. **独立输入不等于独立模型/人工金标**：参考与 binding 都由 Qwen3.8-27B 产生，虽然输入隔离且公式不共享，仍可能有共同语义偏差；参考冲突必须保留。
4. **受控错误不等于自然失败**：当前优势主要是目标误报和少数约束变异，真实生成中的漏约束、错误可行域和修复收益需要共享初始候选的端到端实验。
5. **当前不启动 SOTA**：A2 对 A1 的固定制品配对 `p=0.0625`，且没有 frozen 业务正确率结果。闭源模型不参与资产生成或调参。

## 6. 产物与下一步

- 汇总与逐制品记录：`work/dvsa/bwor_fixed_arms_dev/analysis.json`
- 结果图：`/home/hewj13/paper_icml2027/figures/dvsa_bwor_dev_fixed_arms.png`
- 独立 binding：`work/dvsa/bwor_binding_author/dev/`
- 行为覆盖与审计：`work/dvsa/bwor_binding_eval/dev/`
- 盲评：`work/dvsa/bwor_llm_judge/dev/`；去重重评：`work/dvsa/bwor_llm_judge_dedup/dev/`

下一步冻结同一初始候选的 repair-only 设计：A0 无 memory 自评、A1 文本 memory 自评、A2 DVSA 数值反馈、A3 文本+旧 witness UNKNOWN。独立参考只用于事后业务正确率和 win-safe 评分，不进入任何修复反馈。完成 dev 后再冻结资产、prompt、预算与版本，进入 validation；frozen 仍保持封闭。

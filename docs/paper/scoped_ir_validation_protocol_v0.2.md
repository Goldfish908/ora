# 来源与作用域约束的类型化检查协议 v0.2

日期：2026-11-12 · 状态：真实调用前冻结；历史 validation 二次验证，不是全新 sealed 终验。

## 1. 起因与假设

前一轮 NLP4LP dev 的主要失败不是提示不够长，而是：

- 无依据整数性、额外守恒和业务规则；
- 变量读取路径错误；
- 缺少证据时无法区分 UNKNOWN 与真实违规。

本协议检验：

> 将“自由文本/自由代码 authoring”改为“真实 schema 绑定 + 原文证据 + 受限不变量 + 确定性求值”，能否减少干净误报和路径 UNKNOWN，同时保持独立错误检出？

这是机制验证，不再宣称“程序性 memory”概念创新。

## 2. 数据与暴露说明

- 使用 `work/memory_witness/nlp4lp_artifacts_v2/validation`：30 个问题、145 个制品（115 个独立受控错误、30 个干净解）。
- 该集合已在旧 memory→witness 实验中运行并查看聚合结果，因此只能称**历史 validation / 二次验证**，不能称 untouched、sealed 或最终 frozen test。
- 不读取 sealed 题面、制品或结果；不使用旧 checker 作为输入。
- 每题所有臂共享题面、solution schema 和制品，独立标签仅用于事后评分。

## 3. 三臂

1. `zero`：前一轮零样本自由 Python authoring。
2. `text`：前一轮声明式文本经验 + 自由 Python authoring。
3. `scoped_ir`：LLM 只输出受限 JSON 不变量，由 `ora_agent.dvsa.Interpreter` 求值，不执行 LLM 生成的 Python。

`scoped_ir` 的硬约束：

- 变量路径只能为 `solution.variables.<真实字段>` 或 `solution.objective`；
- 每个要求必须带逐字 `source_span`；
- 整数要求只有在原文明确出现 integer/whole/integral/indivisible 等证据时才允许；
- 不允许凭“how many”或物品可数就推断整数；
- 不允许自行加入最优性上下界、购买—销售守恒或其他题面外规则；
- 无有效不变量、证据不匹配或无法求值均记为 UNKNOWN/拒绝，不得作为真实违规。

每题每臂一次调用，无 CEGIS、无跨题写回。

## 4. 指标与主比较

- 错误检出率、干净解误报率、UNKNOWN 率、每题过门率；
- fail-open 接受解中的干净比例；
- 证据拒绝数、有效不变量数；
- 逐制品配对 McNemar，历史 validation 只作探索参考；
- LLM 调用、token 和延迟。

主比较：`scoped_ir vs text` 与 `scoped_ir vs zero`。

扩量判断：若 scoped IR 相对文本降低干净误报和路径 UNKNOWN，且检出下降不超过 5 个百分点、每题过门率提高，则值得在新的独立开发域继续。若只通过少检查来降低误报，但检出大幅下降，则判定覆盖失败，不扩量。若结果依赖少数题，先审计，不启动第二模型或 SOTA。

主结果保留全部 30 题。既有独立参考审查记录的 6 个冲突/歧义问题（088、090、094、114、130、263）仅用于预先登记的敏感性分析；不根据 scoped IR 的结果新增排除项，也不以敏感性结果替代主结果。

## 5. 记录与可复现

- 协议：`docs/paper/scoped_ir_validation_protocol_v0.2.md`；
- 实现：`scripts/scoped_ir_author.py`、`ora_agent/scoped_ir.py`；
- 保存完整提示、原始响应、JSON spec、拒绝原因、逐不变量执行结果、usage 和延迟；
- API 凭据只走环境变量，不写入结果；
- 主分析仍使用既有制品评分口径；scoped IR 与自由 Python 共用 `metrics/paired` 汇总，不允许把拒绝或脚本失败算成检出。

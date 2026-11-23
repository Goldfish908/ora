# IndustryOR 最小声明式邻域审计 v0.1

本实验只处理具有合格独立业务审计、且具有已核验公开 MILP 适配的注册题。输入是既有 `industryor.solution.v1` 决策制品，不执行原生成代码，不调用 LLM、Gurobi、GEPA 或 memory 资产。

## 结果

- 状态：`ready`；注册合格题 1，可执行题 1，`not_ready` 题 0。
- 窄失败根恢复：1/1；正确控制根原样保留：1/1。
- 业务正确只来自注册独立审计；`business_unverified` 不计入业务正确。公开 `en_answer` 只在修复与选择结束后按绝对误差 0.1 评分。

| ID | 根 | 父业务正确 | 最终业务正确 | 父独立最优性 | 最终独立最优性 | 父公开目标匹配 | 最终公开目标匹配 | 修复结果 |
|---:|---|---|---|---|---|---|---|---|
| 9 | narrow_failure | False | True | not_applicable_infeasible | proven_optimal | True | True | accepted |
| 9 | correct_control | True | True | proven_optimal | proven_optimal | True | True | empty_neighborhood |

失败根的公开目标匹配与业务正确是不同结论：即使父制品的目标已匹配，指示变量一致性违规仍使注册业务审计失败。独立最优性也单列，不用公开答案代替最优性证明。

## 成本

- LLM 调用 0，LLM tokens 0；SCIP sub-MILP 1 次，SCIP 耗时 0.004441s，总墙钟 0.222810s。
- 注册业务审计调用 3 次。正确根为空邻域，不调用 SCIP；失败或被拒绝的候选不能替换原正确根。
- 以上仅为本次决策修复的增量成本，不包含既有输入制品的历史 LLM 生成成本，也不与从头生成实验共用成本口径。

## 限制与 ORAgentBench 可比性

- 仅实现 ID9 的已核验公开语义；其他注册题没有可靠适配时返回 `not_ready`，没有自动猜题面或制品路径。该适配只接受完整执行审计下的公开约束/定义域窄根，不宣称通用模型诊断、代码修复或任意次优根修复。
- 这是对两个既有决策制品的零 LLM 重放：一个窄失败根、一个正确控制根。样本量不足以估计总体恢复率，也未验证其他变量命名、缺失变量、非最优目标或 blocked 审计。
- **不能与 ORAgentBench 的从头生成结果直接比较。** 此处起点、任务（决策修复而非模型/代码生成）、题数、预算和成本均不同；仅沿用公开目标绝对误差 0.1 与注册业务审计口径。不得据此声称 benchmark 提升或 SOTA。

机器明细：`work/industryor_declarative_audit_v0.1/audit.json`。

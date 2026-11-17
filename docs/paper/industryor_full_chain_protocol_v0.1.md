# IndustryOR 全链路结构化迭代与 DAG 协议 v0.1

## 研究目标与实现边界

目标是在 IndustryOR-100 的公开绝对误差≤0.1 指标上，评估完整结构化迭代、变量绑定、SCIP、独立 Witness 与 DAG repair 的组合，争取超过 COOPA=76 的公开参考线。

当前实现是 **COOPA-inspired**，不是官方 COOPA runner。候选是自定义 JSON formulation，后续由 Qwen 生成 PySCIPOpt，而非官方 Pydantic schema 和多求解器路由。独立 k=3 只作为 raw best-of-3，不冒充 COOPA 的迭代建模。IndustryOR 已用于历史开发，本轮新采样不是 held-out；达到公开参考线也不自动等于 SOTA。

## 结构化候选

每题顺序生成 M1/M2/M3：

1. M1 包含 parameters、variables、objective、constraints；每个元素都有题面逐字 source。
2. 对 variables、parameters、constraints、objective 四维置信度和 weak_points 进行结构化评估。
3. M2/M3 读取此前模型及低分维度，显式修复弱项，而非独立 raw 重抽。
4. 校验 JSON、有限数值、变量类型、目标方向和 source 是否逐字属于题面。无效候选不得借 max-min 隐藏错误。

分别生成 M1 与 max-min 选中 formulation 的代码，以比较首个候选与选择结果。参考目标只在最终评分使用，不进入建模、评估或选择。

## 执行与 DAG

选中代码经过变量绑定、导出契约和 SCIP。8 个注册题使用独立业务审计，其余题保持 `business_unverified`。

`structured` 不做额外修复。`structured_dag` 使用与原完整管线相同的 `ProgressController` 和 `MAX_ROUNDS=3`：首轮候选之外最多进行两轮修复，每个失败子节点都会重新进入控制器，而不是只展开根节点一次。只有 9/19/20/21 使用已有独立局部修复证据；已知 SCIP sense 错误使用确定性 API 修复，其余执行或复杂语义错误交给 LLM 重生成。其余 92 题仅在 crash、infeasible、unbounded、无目标或导出失败时进入执行修复，不因 optimal 而盲目重生成。

重生成后重新绑定，记录控制器决策、LLM/SCIP 成本、快照、父子关系、失败和 UNKNOWN。注册题的接受要求 binding 有效、SCIP optimal 和独立业务正确；无接受时保留根候选，不按参考答案或裸目标值排序。未注册题永远不会被冒充为独立业务接受，但若根候选 crash、infeasible 或导出 incomplete，而后代已获得完整 `optimal` 执行与有限目标值，则选择成本最低的执行恢复后代，并标记 `execution_recovered_business_unverified`；若根候选已完整可执行，不根据后代目标值进行挑选。参考答案不参与任何节点选择。

## 成本与报告

共享 M1/M2/M3 的结构化评估与选中代码。分别报告首个候选、max-min、DAG、公开目标匹配、独立业务正确、误接受、win 保留、LLM 调用、token、延迟和 SCIP 次数。raw k=1/k=3、旧 z2=74、上一轮完整管线 70 和 COOPA=76 仅按各自明确机制与口径列示。

后续 memory 对照只使用静态、版本化的成功与失败资产，比较 trigger 与 full，不进行在线自进化或测试集写回。本轮 memory 位于 DAG repair 阶段：`structured_dag_trigger` 按缺失角色、指示约束、目标不一致和动态表达式选择资产，`structured_dag_full` 注入全部资产。若未进入重生成，不计作 memory 实际应用。资产包含真实正例、反例、来源与禁用条件，不把 objective match 当作业务正确。所有 prompt、原始响应、schema、执行、选择、成本和失败均落盘，缓存不冒充新调用。最终完成全量 pytest 与 m2gen 回归。

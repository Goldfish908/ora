# IndustryOR 语义内环：绑定、单线修复与同父 DAG

**范围：8 个已注册独立审计题的开发回放，不是 held-out 或跨族结论。** 所有臂共享相同初始代码、语义绑定和根执行；不运行跨题 memory/RSI。

## 核心结果

| 臂 | 根业务正确 | 最终业务正确 | 明确语义恢复 | 目标匹配 | 实际新增修复调用 | 逻辑修复调用 | 多分支题数 |
|---|---:|---:|---:|---:|---:|---:|---:|
| bind_only | 3 | 3 | 0 | 6/8 | 0 | 0 | 0 |
| single_line | 3 | 7 | 4 | 7/8 | 1 | 1 | 0 |
| branch_dag | 3 | 7 | 4 | 7/8 | 5 | 5 | 4 |

单线与 DAG 的最终业务正确数差为 **+0**，实际新增修复调用差为 **+4**。因此只能根据实际差值判断 DAG 是否有增益，不能把分支数量本身当成效果。

重绑定只改变导出名称，不改变模型内部语义；它带来的审计覆盖提升不计作模型修复。明确语义恢复只统计根候选 `complete + business_correct=false` 到最终 `business_correct=true` 的候选。

## 逐题证据

| ID | 绑定后审计/正确 | 单线最终/正确 | DAG 最终/正确 | 单线新调用 | DAG 新调用 | DAG 接受动作 |
|---:|---|---|---|---:|---:|---|
| 4 | complete/True | complete/True | complete/True | 0 | 0 | ['initial'] |
| 8 | complete/True | complete/True | complete/True | 0 | 0 | ['initial'] |
| 9 | complete/False | complete/True | complete/True | 0 | 1 | ['local_patch'] |
| 19 | complete/False | complete/True | complete/True | 0 | 1 | ['local_patch', 'regenerate'] |
| 20 | complete/False | complete/True | complete/True | 0 | 1 | ['local_patch', 'regenerate'] |
| 21 | complete/False | complete/True | complete/True | 0 | 1 | ['local_patch', 'regenerate'] |
| 25 | complete/True | complete/True | complete/True | 0 | 0 | ['initial'] |
| 48 | invalid_solution/False | invalid_solution/False | invalid_solution/False | 1 | 1 | 无 |

## 成本

- 共享绑定阶段已发生 8 次调用、24609 tokens、116.798s；三臂均复用，不重复计新调用。
- `single_line`：修复调用 1，逻辑调用 1，tokens 8894，SCIP 5。
- `branch_dag`：修复调用 5，逻辑调用 5，tokens 27333，SCIP 9。
- DAG 开发模式故意评估同父的替代分支，即使一个分支已经通过；额外成本用于检验搜索机制，不应隐藏。

## 可追溯性与限制

- 核验 24 条臂结果、32 份业务评分、5 份重生成记录和 8 份执行源码快照。
- 只使用 ID 9/19/20/21 的独立局部修复证据。ID 48 若没有形成完整审计所需角色，保持 blocked 或未接受。
- 这里的 DAG 选择顺序是业务接受、LLM/SCIP 成本、深度和节点 ID，不使用参考答案排序。
- 这些结果不证明 IndustryOR-100 全集、跨族迁移或外环自进化有效。全集历史 70/100 的结果仍单独保留，不与此开发回放混写。

机器可读结果：`work/industryor_semantic_dag_dev_v0.1/analysis.json`；manifest：`work/industryor_semantic_dag_dev_v0.1/manifest.json`。

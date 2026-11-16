# Cold-start 绑定与证据 DAG 协议 v0.1

## 目标与来源

本轮验证两个新机制族：`objective_recompute` 与 `resource_bound`。有效绑定来自独立参考规格，标为 `reference_assisted`；从保存自然候选表达式派生的提议标为 `cold_start_proposal`。后者不是新 LLM 生成，也不是参考真值。

当前未导出 LLM 环境，不调用新模型。不能把保存响应或手工构造的提议写成“本轮 LLM 冷启动发现”。这些实例属于历史开发，不称 frozen。

## 独立验证

使用同一个 `BindingProposal` 验证入口和现有 scoped 资产。每题保留：

- reference-assisted 有效绑定；
- candidate-derived 或不正确绑定；
- 缺证据/原文的 UNKNOWN；
- 有效提议与缺证据提议并存时不得选择较有利者。

`label_source` 必须存在。反例门通过后，独立参考业务评分仍需通过。拒绝与 UNKNOWN 不晋升，不修改原模型。

## 真实错误的小型证据 DAG

BWOR-058 是已有自然目标错误：漏掉 `x3_2`，并重复使用 `8.4*x3_3`。原始变量、约束、data 和 objective sense 不变。

```text
root：自然初始，独立评分失败
├── reference-assisted objective patch → SCIP → 独立评分
└── candidate-derived binding → 保留为负证据，不接纳
```

节点保存 candidate hash、parent、action、binding hash、执行、独立评分、成本与停止原因。不得按 score 剪枝或删除失败分支。`accepted` 必须同时满足绑定验证、真实求解和独立业务评分。

同一 reference-assisted 修复也运行单线对照。若最终正确性与求解成本相同，结论只能是“DAG 保持了正确分支和负证据”，不能宣称 DAG 提升。没有真实触发时不构造 DAG 成功故事。

## 验收与交付

两个机制族均要求有效、错误、缺证据与冲突处理清晰，错误接受为 0。保存协议、manifest、逐题绑定、反例、业务评分、DAG 父子关系、成本、回滚、结果图和报告，完整 pytest 与 `m2gen` 回归通过。不得声称通用跨族、自进化、DAG 增益或 SOTA。

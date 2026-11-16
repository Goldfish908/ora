# OR-Agent 参考实现评审 v0.1

## 范围与来源

本次只评审公开仓库 [qiliuchn/OR-Agent](https://github.com/qiliuchn/OR-Agent) 及其源码，不把它的任务、数据集或结果直接外推到 NL→优化建模。

主要源码：

- [flow_graph.py](https://raw.githubusercontent.com/qiliuchn/OR-Agent/main/src/oragent/flow_graph.py)
- [experiment_agent.py](https://raw.githubusercontent.com/qiliuchn/OR-Agent/main/src/oragent/experiment_agent.py)
- [evaluator.py](https://raw.githubusercontent.com/qiliuchn/OR-Agent/main/src/oragent/evaluator.py)

该工作主要演化算法/控制器代码并依靠自动环境评分，而我们主要修复自然语言优化建模的业务语义。两者自动评测这一共同点很有价值，但评价语义不同。

## 可借鉴的设计

### 1. 将线性修复改为显式候选 DAG

FlowGraph 的 `Node` 保存 solution、parent、children、depth、is_done，支持选择最佳未完成叶节点。对我们的 repair 可扩展为：

```text
候选模型/代码 + parent hash + action + solver record
+ scoped asset/version + checker status + UNKNOWN/rejected
+ independent score（仅环外）+ cost + stop reason
```

价值：可以表达 local patch、regenerate、补充证据、回退到父节点和多个候选分支，而不只是单一时间顺序的 retry。

约束：我们的节点不能仅以 score 排序。需要同时保存接受状态、证据来源和 UNKNOWN；否则会把“数值更好但业务错误”的候选选成最优叶。

### 2. 小改动与大改动的边界

OR-Agent 的实验 agent 只做参数/小 diff；更大改动生成新的 idea/solution node。与我们 `local_patch` 和 `regenerate` 的分工一致：局部确定性修复留在当前节点，重新建模应生成新候选，而不是覆盖旧候选。

### 3. 按证据分配预算

它按候选潜力动态分配实验次数，值得用于 controller 的后续研究：复杂错误可投入更多检查或重生成，已知 API 错误一次修复即可。但当前冻结协议固定预算 ≤2，不应在看到结果后改为自适应预算。

### 4. 记忆压缩前先保存原始轨迹

它的 progressive summarization 会清理中间历史。我们的 memory 若压缩，必须先落盘完整代码、执行、审计、动作和独立评分；压缩只影响后续 prompt，不能删除审计证据。

## 不能直接复用的部分

### 1. 以 score 选叶不等于业务可接受

FlowGraph 选择 `is_done=False` 的最佳 score 叶，未编码我们的 `can_accept`、UNKNOWN、partial rejected 和 checker provenance。直接复用会把幻影目标或局部最优非法解当成好解。

### 2. 环境回调不能自动成为语义真值

实验 agent 允许 LLM 生成 callbacks 并拼入执行脚本。这对环境探索有用，但不能替代独立业务约束。我们的 evidence acquisition 应优先读取结构化执行结果、SCIP 状态和确定性业务重算，而不是让 LLM 自写规则后再自证。

### 3. evaluator 的输出 `eval()` 不适合直接移植

公开 evaluator 用 `eval()` 解析指标、features 和 score。对模型生成的输出直接执行 Python 表达式会扩大代码执行面。我们应使用受限 JSON schema 与显式数值解析，不移植这种输出约定。

### 4. 消融结论不是通用配置

公开 README 中，深度、宽度、elite period、memory compression 等结果高度依赖任务：无压缩在六个问题中的四个最好，crossover 使用长期反思则三比三。不能据此推断“更多 agent、更多轮次或更少压缩”在我们这里必然更好。

## 对当前里程碑的约束

当前新初始冻结评估仍保持单候选、固定 ≤2 的 no_repair/fixed/progress 对照，不因为参考 OR-Agent 就增加树宽、agent 数或预算。

后续若验证分枝搜索，应预注册一个小型 DAG 对照：

- 同一父候选派生 local patch 与 regenerate；
- 所有分支使用同一独立 scorer、同一预算和 checker；
- 只保留 `can_accept` 的候选；其他分支保留为负证据；
- 比较业务恢复、误接受、harmed_win、token 和 SCIP 次数，而不是仅比较 score 或 agent 数。

OR-Agent 提供的是搜索结构启发，不是我们业务语义可信度的证据。

## 7. 对 FlowGraph、LeadAgent 与 SolutionDatabase 的源码复核补充

本轮进一步阅读了官方 [flow_graph.py](https://raw.githubusercontent.com/qiliuchn/OR-Agent/main/src/oragent/flow_graph.py)、[lead_agent.py](https://raw.githubusercontent.com/qiliuchn/OR-Agent/main/src/oragent/lead_agent.py)、[experiment_agent.py](https://raw.githubusercontent.com/qiliuchn/OR-Agent/main/src/oragent/experiment_agent.py) 和 [solution_database.py](https://raw.githubusercontent.com/qiliuchn/OR-Agent/main/src/oragent/solution_database.py)。

可直接借鉴的是：

- FlowGraph 保存父子关系，适合把同一初始派生的局部修复、替代绑定和重新建模分开，而不是相互覆盖。
- LeadAgent 显式区分扩展、回溯与终止。我们应把“没有更优 score 就 done”改为“预算耗尽、没有可用证据动作或独立验收通过才停止”。
- ExperimentAgent 的小 diff 与更大结构调整分离，符合现有 `local_patch/regenerate` 分工。动态实验次数可参考，但应由证据改善和不确定性决定，而非精英身份。
- SolutionDatabase 的岛屿与 signature 聚类可保持假设多样性。我们的 signature 应是机制、绑定作用域、数据 schema 和失败类型，而不是目标值或程序长度。

不能直接复用的部分：

- `get_best_undone_leaf` 与 LeadAgent 仅保留优于父节点的孩子，会丢掉合法替代表达和负证据。我们的节点先经过独立 eligibility，再按证据选择扩展，不根据 score 剪枝。
- 数据库按 score 采样、按长度偏置及定期重置弱岛不等于业务可信或审计可回溯。负例、失败绑定和原始轨迹不得因重置删除。
- ExperimentAgent 的 progressive summarization 可能清空中间代码与动作。我们必须在任何压缩之前持久化原始代码、绑定、求解、审计和成本。
- 其按 score 回退和 callbacks 动态生成执行代码不符合我们的 win-safe 与受限执行要求。回退必须由独立业务评分决定；探索 probe 使用声明式规格，不移植任意生成 callback 或 `eval()` 的输出协议。
- FlowGraph 的 Node 没有我们的 binding/evidence/provenance 字段，不能直接表达 UNKNOWN、部分拒绝或独立业务接受，需单独设计适配层。

因此建议只复用“树状假设管理＋实验诊断”的思想，节点改为：

```text
candidate_hash + parent_hash + action + binding_sha256
+ source/scope + checker_status + independent_business_status
+ execution/cost + stop_reason + immutable_negative_evidence
```

候选分支仍须等真实自然修复触发后再做小规模对照，不把 OR-Agent 的多角色、树宽或 score 改善当作我们方法有效的证据。

# IndustryOR 工程 Memory 在线进化与冻结验证协议 v0.1

## 1. 目标与边界

本轮实现并测试一个真实可运行的非参数外环：开发轨迹 → LLM 候选经验 → 独立正反例 → 多种子配对重放 → dev/gapcheck 两级晋升 → 版本化 registry → 冻结后只读测试。拒绝、修订血缘和退休必须留痕；测试期写入必须被程序拒绝。

本轮只自动晋升 `execution` 类资产。`business` 类资产必须具有独立业务 Witness 和独立正确/错误样本；公开 objective match 不得代替业务标签。未注册 IndustryOR 题只能提出业务候选，不能晋升。

IndustryOR 已在历史实验中使用。本轮 40/30/30 是新的**回溯开发划分**，不是 sealed test，不据此宣称 SOTA。新 memory 的提议、验证和晋升不得读取 gapcheck/test 的题面、代码、失败详情或参考答案。test 只用于冻结后的最终评分。

## 2. 数据划分与暴露边界

固定 seed：`industryor-memory-evolution-v0.1`。按 `sha256(seed + ":" + problem_id)` 排序：

- dev：前 40 题，可提议和第一轮验证；
- gapcheck：随后 30 题，只验证 dev-passed 资产；
- test：最后 30 题，只在 registry 和实现冻结后运行。

同一 problem ID 的 A/B/C 三个 raw 候选始终位于同一集合。划分文件只含 ID、源分析哈希和协议哈希。

## 3. 候选与资产生命周期

开发侧选择具有至少三个不同来源题的细粒度执行失败簇。LLM 只读取 dev 的题面、代码片段和执行错误，不读取 `en_answer` 或最终匹配标签。每个候选只处理一个机制，prompt 文本不得包含题目 ID、实例答案或参考目标。

候选分两种：

- `prompt`：按确定性失败签名触发的文本经验；
- `guard`：同一经验固化成 allowlist 中的确定性代码修复。guard 必须通过独立 `must_fire/must_pass`、AST 保持和不相关代码不误伤检查。`addvar_v_to_name` 只处理已有 `vtype`、缺少 `name` 的明确角色；`addvar_v_to_vtype` 只处理没有 `vtype` 且字面值明确为变量域的情形，角色不清时拒绝固化。

prompt 候选可通过 dev AST 角色检查生成 guard 子资产，保留 `parent_id`；不能从 gapcheck/test 产生或修订资产。

状态只允许：

```text
candidate → dev_passed → promoted
    │            │
    └→ rejected ←┘
promoted → retired
```

被拒绝资产可以生成带 `parent_id` 的新版本，不能改写历史。每次登记、验证、晋升和退休都追加事件。registry 使用内容哈希和原子写入。

## 4. 配对验证与晋升门槛

每个目标题最多选一个失败候选，避免同一题多个变体占权。dev/gapcheck 均使用三个显式种子，固定初始代码，比较 no-memory 与候选资产；首轮之外最多一次修复生成。control 和 treatment 使用相同初始制品和种子。

主要标签是完整执行恢复：`exec_status=ok`、SCIP `optimal`、至少一个解、完整导出和有限 objective。参考答案只用于冻结后的附加评分，不进入晋升。

逐题先对三个种子取均值，再做宏平均。基本要求：dev 至少两个不同题、gapcheck 至少一个不同题；paired execution harm=0；独立业务误接受=0；guard 独立契约全部通过；任何 runner error 都阻止晋升。业务资产另需独立 `business_gain` 达到同一质量门槛且 `business_harm=0`，不能使用执行增益或 objective match 替代。

资产可通过以下任一路径晋升：

1. 质量路径：dev 执行恢复宏增益 ≥20pp，gapcheck ≥5pp；
2. 确定性成本路径：仅 guard；dev/gapcheck 执行恢复相对 control 均不差于 5pp，且修复 LLM 调用下降至少 80%。

不满足即 rejected。gapcheck 不用于修订；若需要修订，必须回到 dev 形成新血缘并重新经过两级验证。退休只发生在非冻结 registry 的后续开发复验中；冻结测试不能修改资产状态。

## 5. 冻结与最终测试

冻结 manifest 记录 registry、协议和实现 SHA256。冻结后 propose、validate、promote、retire 均抛出错误；测试只能读取 promoted 资产。memory 按当前 DAG 节点的执行签名重新选择，不把根节点经验错误沿用到所有后代。

最终 test 使用三个显式种子、完整 `MAX_ROUNDS=3`（首轮+最多两次修复），比较 no-memory 与冻结 evolved registry。报告：

- 目标失败簇的执行恢复和 LLM 成本；
- 全部 test raw-selected 根候选的执行恢复、公开 objective match 和 win 保留；
- 业务验证覆盖、UNKNOWN、误接受；
- 候选/拒绝/晋升/退休数量及血缘；
- LLM 调用、token 和延迟。

该测试复用冻结初始代码以隔离 repair/memory 的增量，不是完整生成管线的新采样复现。最终不选择最好种子，不按参考答案选择资产或 DAG 节点。

## 6. 结论纪律

单机制资产的成功只证明该机制可从开发轨迹沉淀并迁移到本轮留出 ID，不证明通用自进化。无资产通过门槛是合法负结果，不移动阈值挽救。所有 runner error 保留在分母，所有状态变化和实际 memory activation 落盘。

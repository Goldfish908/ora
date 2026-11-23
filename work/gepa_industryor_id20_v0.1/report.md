# IndustryOR ID20 公开 MILP 与 GEPA-inspired 机制验证

本实验是 **development validation，非 heldout**。只重放两个显式指定的 ID20 决策根，不用于估计总体恢复率或宣称 benchmark/SOTA 提升。搜索与选择不读取 `en_answer`；最终独立 `score_solution` 和公开答案评分均发生在 SHA256 冻结之后。

## 公开 MILP 与根契约

- `x1..x4` 为非负整数，`y1..y4` 为 binary；最大化 `15*x1 + 8*x2 + 12*x3 + 5*x4`。
- 资源约束为 `30*x1+10*x2+20*x3+15*x4 <= 1200` 与 `8*x1+5*x2+3*x3+2*x4 <= 800`。
- 逻辑约束为 `y1+y4 <= 1`、`y3 >= y2`、`x4 <= x2`；每个 `i` 均有 `yi <= xi <= Mi*yi`，`M=(40,120,60,80)`。题面、注册 question hash 与 ORThought 源文件 hash 均已核验。
- 失败根父独立业务结论为 `False`，违规为 `cars_imply_blocks`、`link_x3_y3`、`link_x4_y4`；正确控制父结论为 `True/proven_optimal`。manifest 默认根未使用，ID20 只接受八个精确变量及匹配的 INTEGER/BINARY 声明与注册语义。

## 同根同预算对照

五个主臂为 `direct-full, declarative, single, old-population, pareto-only`，另有 `pareto+compatible+merge` 辅助臂。每臂上限均为 6 次 child evaluation；direct-full 和 declarative 按定义一次操作后停止，不用重复求解填满预算。所有候选使用公开检查，最终 elite-best 先冻结再独立复评。

| 根 | 臂 | Child eval | SCIP runs | 父目标 | 最终目标 | 最终违规数 | 独立业务正确 | 独立最优性 | en_answer 匹配 | 搜索秒 | 冻结后审计秒 |
|---|---|---:|---:|---:|---:|---:|---|---|---|---:|---:|
| narrow_failure | direct-full | 1 | 1 | 960.000000 | 956.000000 | 0 | True | proven_optimal | True | 0.618785 | 0.202605 |
| narrow_failure | declarative | 1 | 1 | 960.000000 | 956.000000 | 0 | True | proven_optimal | True | 0.411581 | 0.203234 |
| narrow_failure | single | 4 | 1 | 960.000000 | 956.000000 | 0 | True | proven_optimal | True | 0.417551 | 0.200547 |
| narrow_failure | old-population | 6 | 2 | 960.000000 | 956.000000 | 0 | True | proven_optimal | True | 0.521952 | 0.201436 |
| narrow_failure | pareto-only | 4 | 2 | 960.000000 | 956.000000 | 0 | True | proven_optimal | True | 0.432723 | 0.203496 |
| narrow_failure | pareto+compatible+merge | 4 | 2 | 960.000000 | 956.000000 | 0 | True | proven_optimal | True | 0.426756 | 0.202059 |
| correct_control | direct-full | 1 | 1 | 956.000000 | 956.000000 | 0 | True | proven_optimal | True | 0.210467 | 0.200417 |
| correct_control | declarative | 1 | 0 | 956.000000 | 956.000000 | 0 | True | proven_optimal | True | 0.201065 | 0.215204 |
| correct_control | single | 5 | 1 | 956.000000 | 956.000000 | 0 | True | proven_optimal | True | 0.213225 | 0.201095 |
| correct_control | old-population | 5 | 2 | 956.000000 | 956.000000 | 0 | True | proven_optimal | True | 0.421349 | 0.200317 |
| correct_control | pareto-only | 6 | 2 | 956.000000 | 956.000000 | 0 | True | proven_optimal | True | 0.421398 | 0.199650 |
| correct_control | pareto+compatible+merge | 6 | 2 | 956.000000 | 956.000000 | 0 | True | proven_optimal | True | 0.426911 | 0.201965 |

## 血缘、违规与 merge 判别

`audit.json` 保留每个候选的 `parent_id`、`parent_sha256`、operation、公开违规、目标、接受/拒绝原因和逐条成本 ledger。merge 只有真实兼容、非重复且完整公开检查 PASS 才计 tested；其余一律 `not_tested`，不计 invalid，也不为制造 merge 而追加预算。

| 根 | Merge attempted | Tested | Not tested | Not-tested reasons |
|---|---:|---:|---:|---|
| narrow_failure | 6 | 0 | 6 | {"insufficient_lineage": 2, "no_compatible_merge": 4} |
| correct_control | 6 | 0 | 6 | {"insufficient_lineage": 2, "no_compatible_merge": 4} |

## 独立业务结论与成本

- 失败根五主臂独立业务正确序列：`{"direct-full": [true], "declarative": [true], "single": [true], "old-population": [true], "pareto-only": [true]}`。正确控制所有臂保留原始字节：`True`。
- Merge attempted/tested/not_tested = 12/0/12；没有真实兼容 merge 时不声称 merge 增益。
- LLM 调用 0、tokens 0；真实 SCIP sub-MILP 共 17 次，搜索公开审计 21 次。搜索 ledger 总秒数 4.723763，臂墙钟合计 4.806948，冻结后独立审计 2.432026s。
- `total_search_seconds` 是逐候选可调和成本；`arm_wall_seconds` 另含选父等控制开销，二者不相加。求解时间已经包含在 evaluation 中，不重复计费。既有输入根的历史生成成本不在本次增量成本内。
- 单题、单失败根、单正确根且全部属于开发验证；结果只说明本根上的机制行为，不构成 heldout 泛化证据。

机器明细：`work/gepa_industryor_id20_v0.1/audit.json`；冻结制品位于同目录 `final/`。

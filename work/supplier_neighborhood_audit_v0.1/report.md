# IndustryOR ID19/21 供应商订单 MILP 目标修复审计 v0.1

本实验是 **development validation，非 heldout**。四个显式根均来自既有开发制品；只评价公开 MILP 与独立 `score_solution`，不执行原生成代码，不调用 LLM，也不用于宣称 benchmark/SOTA 提升。

## 公开模型与失败定性

- `x_A,x_B,x_C` 为非负整数订单数，`y_A,y_B` 为 binary；`Q=q_A*x_A+q_B*x_B+q_C*x_C`，并施加 `L<=Q<=U`、`y_A<=x_A<=M_A*y_A`、`y_B<=x_B<=M_B*y_B`、`x_B>=k*y_A` 和 `x_C>=y_B`。
- 目标严格为 `sum_s c_s*q_s*x_s`：每件成本 × 每单件数 × 订单数。ID19 的每单成本系数为 `(750,450,400)`，ID21 为 `(2400,1650,1500)`；没有使用漏乘 `q` 的 `(50,45,40)` 或 `(120,110,100)`。
- 两个失败根都通过执行、定义域与全部公开约束，却同时具有报告目标不一致和独立次优。因此本次是联合目标公式/次优修复，**不是普通约束窄修复**，也不声称能修复任意约束错误。

| ID | 根 | 显式路径 | SHA256 | 父报告目标 | 父独立成本 | 父业务正确 | 父最优性 |
|---:|---|---|---|---:|---:|---|---|
| 19 | objective_failure | `work/industryor_next_stage_v0.1/prob_019/solution.json` | `b4d06bad13ea05feeb4059541a1d4302e228309053dde2f10c9fcaa2e41c9a26` | 365.000000 | 4650.000000 | False | suboptimal |
| 19 | correct_control | `work/industryor_structured_dev_v0.2/prob_019/structured_dag/regenerate/solution.json` | `f5707ce9ef546e39cf5fbd785ef877e83feef29a12f66d7cc31f062e695e6fbf` | 4000.000000 | 4000.000000 | True | proven_optimal |
| 21 | objective_failure | `work/industryor_next_stage_v0.1/prob_021/solution.json` | `4fde21855d35aa0dcf82ed0f1260196910e9dbd6afa54106fc8a8e2a38b0a6f0` | 980.000000 | 16500.000000 | False | suboptimal |
| 21 | correct_control | `work/industryor_structured_dev_v0.2/prob_021/execution_A/solution.json` | `ee4664b24db934a2311cc6cfa9e039add7ea5b4247c7ec7f520d63a8cd7aee21` | 15000.000000 | 15000.000000 | True | proven_optimal |

ID19 正确控制明确使用 `structured_dag/regenerate/solution.json`，没有默认到 `execution_A`。每个根的原始字节以 base64 与 SHA256 一同保存在 `audit.json`，并在运行前后复核。

## 同根三臂结果

`direct-full` 显式释放全部五变量；`declarative` 从两个目标违规键及全局 Q/目标依赖图释放全部五变量，二者均无固定变量。`pareto` 另构造仅改目标字段的账面候选，以违规数、独立成本和改变变量数构成 Pareto 指标，但只有独立业务正确候选才可入选。

| ID | 根 | 臂 | 父独立成本 | 最终独立成本 | 最终业务正确 | 最终最优性 | SCIP | 改变变量数 | en_answer 匹配 |
|---:|---|---|---:|---:|---|---|---:|---:|---|
| 19 | objective_failure | direct-full | 4650.000000 | 4000.000000 | True | proven_optimal | 1 | 5 | True |
| 19 | objective_failure | declarative | 4650.000000 | 4000.000000 | True | proven_optimal | 1 | 5 | True |
| 19 | objective_failure | pareto | 4650.000000 | 4000.000000 | True | proven_optimal | 1 | 5 | True |
| 19 | correct_control | direct-full | 4000.000000 | 4000.000000 | True | proven_optimal | 0 | 0 | True |
| 19 | correct_control | declarative | 4000.000000 | 4000.000000 | True | proven_optimal | 0 | 0 | True |
| 19 | correct_control | pareto | 4000.000000 | 4000.000000 | True | proven_optimal | 0 | 0 | True |
| 21 | objective_failure | direct-full | 16500.000000 | 15000.000000 | True | proven_optimal | 1 | 5 | True |
| 21 | objective_failure | declarative | 16500.000000 | 15000.000000 | True | proven_optimal | 1 | 5 | True |
| 21 | objective_failure | pareto | 16500.000000 | 15000.000000 | True | proven_optimal | 1 | 5 | True |
| 21 | correct_control | direct-full | 15000.000000 | 15000.000000 | True | proven_optimal | 0 | 0 | True |
| 21 | correct_control | declarative | 15000.000000 | 15000.000000 | True | proven_optimal | 0 | 0 | True |
| 21 | correct_control | pareto | 15000.000000 | 15000.000000 | True | proven_optimal | 0 | 0 | True |

失败根恢复为 **6/6 个 failure-arm**；正确控制原字节保留为 **6/6 个 control-arm**。正确控制均为零求解、零 child candidate。

## Pareto 判别与血缘

- `pareto` 共产生 2 个仅账面修正候选，其中 2 个仍为 `suboptimal`，业务正确数为 0；它们虽减少改变字段且可能位于 Pareto front，但均被拒绝，不计恢复。
- 完整重优化候选在两题均收敛到 `x_A=x_B=y_A=y_B=0,x_C=10`，独立成本分别为 4000 和 15000。账面候选与完整候选可因改变变量数不同而互不支配；Pareto 身份本身不等于业务正确。
- `audit.json` 对每个候选保存 `parent_candidate_id`、`parent_sha256`、candidate SHA256、operation、完整 spec、图 hash、原始/候选字节、独立审计、接受/拒绝原因和逐项成本；最终选择另有冻结 hash 清单。

## 成本

- LLM 调用 0、tokens 0；真实 SCIP 共 6 次，求解耗时 0.010710s。
- 独立审计调用：根预检 4，搜索/接受 8，冻结后新鲜复评 12，合计 24。选择墙钟 0.638160s，冻结后审计 0.392057s。
- 这是本次决策修复的增量成本，不含输入制品的历史生成成本；墙钟与 SCIP 求解时间是不同口径，不相加冒充求解次数。

## 冻结、答案与 not_ready 边界

- 所有选择与 SHA256 冻结完成后，才对冻结制品重新调用独立 `score_solution`；全部最终审计完成后才读取并附加 `en_answer`，绝对误差口径为 0.1。公开答案不参与修复、Pareto 构造或选择。
- 仅支持 ID19/21、注册 question hash、精确五变量及 INTEGER/BINARY 声明、完整独立审计，以及“父完全可行且恰好目标不一致+独立次优”的失败形态；正确根仅做保留。
- 缺失 PySCIPOpt、无候选、非 optimal/完整导出、额外约束/定义域/执行错误、未知审计、根路径或 hash 不符、冻结字节变化均为 `not_ready` 或直接失败关闭；不把 `business_unverified` 计为正确，也不回退到默认根。
- 两题、各一个失败根和一个正确根的开发验证不能估计跨题恢复率或 heldout 泛化；direct-full、declarative 与 Pareto 在这些根上的相同恢复不证明某臂普遍更优。

机器明细：`work/supplier_neighborhood_audit_v0.1/audit.json`。

# federated_sub_milp_v0.1 SkillRegistry 真实审计

## 结论：不晋升（asset status = `rejected`）

本候选是 method-level `SkillAsset`，但现有真实记录没有满足注册器的非零 `gained_true` 要求；三个场景又都来自同一 problem 的预声明开发实验，不能证明跨任务晋升。审计没有调用 `promote` 绕过 dev 失败，资产也不能被 registry 选择或激活。

- 审计 HEAD：`827b859887e106e2933b4abf4ce3cf91e220d0cf`
- 源实验 HEAD：`89b05378e4e1428a54d7e80f59e5eccff66496ff`
- 源 audit SHA256：`944c157f37c32b7217369690ae53840b4553448f6f8afb74e84902998a4fa0fb`
- direct-full baseline：`a445cb9f2e9d6ee9f362b00b5bd158a11eb3641fb8469539828aa1a496f5342a`
- sub-MILP treatment：`186a99772af22ebd4071ef2e6f368872869a847780a7b86b95899c749cbf7ce2`
- official evaluator binding：`98ea397fd96ffabffbf6568e10428ba8fa460a25bb6717134891fb2bd4685ac8`
- baseline/treatment hash 不同：**是**

control 是独立执行的 direct-full 臂和独立成本账本，每次从共同 root 做一次全变量求解；treatment 是 single-chain 声明式 sub-MILP 臂，最终 best 必须确有固定变量。两臂绑定不同的实现源文件及 hash，共享同一官方评价器与公开输入。

## 资产契约与证据边界

- trigger：`{"asset_level": "method", "event": "declarative_solution_repair", "problem_id": "federated_learning_cohort_selection", "representation": "binary_client_stream_selection"}`
- required inputs：10 项，包括 incumbent、parent hash、全部公开数据、违规、模式和求解限制。
- dataset scope：`ORAgentBench/federated_learning_cohort_selection`
- domain scope：`logistics/federated-learning-cohort-selection`
- API scope：`PySCIPOpt==6.2.1, federated_sub_milp_v0.1`
- schema scope：`federated_learning_cohort_selection/solution.csv:client_id,stream_id,selected`
- required seeds：`[20261123]`；实际覆盖：`[20261123]`
- dev tasks：`['duplicate_client', 'stream_minimums']`；gapcheck tasks：`['all_budgets']`
- gapcheck 分类：`same_problem_predeclared_replay_not_an_independent_holdout`

资产明确限定只能编辑 released binary decisions，禁止改变 fixed variables、公开数据/约束/目标、隐藏违规、用官方反馈选父或扩展、把 gaplimit 称为全局最优，以及跨 scope 激活。不变量包括 parent hash、完整变量划分、fixed values、无新增违规、目标不退化、UNKNOWN 拒绝和官方事后复评。正反例、near-miss、ambiguous 和 out-of-scope 示例完整保存在 `audit.json` 的 `asset` 中。

## 真实配对结果

下表的 official feasible/quality/true/objective 均由每条保存的 `official_evaluation.json` 通过当前 `official_metrics` 重新计算，并与源 audit 摘要逐项核对；final artifact 同时匹配冻结 manifest、源 best hash 和官方输入 hash。指标不是在本审计代码中填写的。

| Split | Scenario | Root（前12位） | Arm | Feasible | Quality | True | Objective | Sub-MILP fixed |
|---|---|---|---|---:|---:|---|---:|---:|
| dev | duplicate_client | `491818eeef49` | direct-full | True | 1.999999999998 | True | 6020.689910000 | 0 |
| dev | duplicate_client | `491818eeef49` | sub-MILP | True | 2.000000000000 | True | 6021.247619500 | 943 |
| dev | stream_minimums | `f2af43afac7d` | direct-full | True | 1.999999999998 | True | 6020.689910000 | 0 |
| dev | stream_minimums | `f2af43afac7d` | sub-MILP | True | 2.000000000000 | True | 6021.590728500 | 556 |
| gapcheck | all_budgets | `f4c4f5240b5a` | direct-full | True | 1.999999999999 | True | 6020.689910000 | 0 |
| gapcheck | all_budgets | `f4c4f5240b5a` | sub-MILP | True | 2.000000000000 | True | 6021.247619500 | 943 |

| Scenario | Δ quality | Δ objective（最大化） | Control search s | Treatment search s | Control total s | Treatment total s | Child eval C/T | Solver calls C/T |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| duplicate_client | 0.000000000002 | 0.557709500 | 1.909812 | 4.256615 | 44.518877 | 28.163723 | 1/4 | 1/3 |
| stream_minimums | 0.000000000002 | 0.900818500 | 1.881705 | 6.481440 | 55.099183 | 39.090817 | 1/5 | 1/4 |
| all_budgets | 0.000000000001 | 0.557709500 | 2.197905 | 6.649543 | 25.848953 | 32.864937 | 1/5 | 1/4 |

成本包括各自 root public check、全部 proposal/evaluation（含重复提议和 solver）、以及 post-freeze official runner wall time；solver 不重复相加。资产记录的真实 treatment 均值为 search **5.795866 s**、official **27.577293 s**、total **33.373159 s**，LLM calls 为 0。direct-full 上限 1 次、single 上限 6 次 child evaluation，预算不等价。

## Clean control（不计入修复 gained_true）

| Arm | Root unchanged | Best not worse than root | Feasible | Quality | True | Objective | Search s | Total s |
|---|---|---|---:|---:|---|---:|---:|---:|
| direct-full | True | True | True | 1.999999999996 | True | 6020.689910000 | 1.938224 | 24.860463 |
| sub-MILP | False | True | True | 2.000000000000 | True | 6021.247619500 | 5.716101 | 25.918185 |

clean control 无回归：**是**。direct-full 最终保留 root，sub-MILP 最终制品有变化且 official objective 提升；它与三个预先构造的受损 root 分开报告，不把 clean 上的目标优化冒充受损修复的 `gained_true`。

## SkillRegistry 重放

| Layer | Pairs | gained_true | Required | lost_true | new_phantom | UNKNOWN | Passed |
|---|---:|---:|---:|---:|---:|---:|---|
| dev | 2 | 0 | 1 | 0 | 0 | 0 | False |
| gapcheck | 1 | 0 | 1 | 0 | 0 | 0 | False |

两臂在三个场景的最终 official `true_correct` 全都已经是 true，因此 dev 为 0/2、gapcheck 为 0/1 新增真通过；质量和 objective 改善不能替代注册器的 `gained_true`。dev 实际生命周期结果为 `rejected`，promotion attempted=**否**，selectable assets=`[]`。

拒绝/阻止原因：

- `no_gained_true:dev requires 1, observed 0`
- `no_gained_true:gapcheck requires 1, observed 0`
- `cross_task_evidence_missing:only one problem with predeclared scenarios`
- `independent_gapcheck_missing:all_budgets belongs to the same development experiment`

## 仅限当前 scope 能支持的结论

真实同 root 记录支持当前三场景的 official true/feasible、quality 和 objective 不退化：**是**；search cost 全场景不退化：**否**；含官方评价的总成本全场景不退化：**否**。这些结果只适用于当前 problem、三个预声明场景、单个 seed 和本次运行时，不支持跨任务优越性、普遍成本优势或全局最优。

The single arm mixes default, direct-full, and feasible-parent operations; its frozen best is verified sub-MILP, but the arm-level treatment effect is not a pure one-solve ablation.

## 后续仍缺证据

1. 真实 dev gained_true 证据：当前为 0，要求 1；必须有配对从 control true=false 变为 treatment true=true，不能仅改写记录标签。
2. 未见任务或 problem 上的独立 gapcheck gained_true 证据：当前为 0，要求 1；all_budgets 不能证明跨任务晋升。
3. 额外预注册 seed 及冻结配对运行；当前证据只有 seed 20261123。
4. 预算匹配或预先声明成本目标的 direct-full 对照；当前 child evaluation 上限分别为 1 和 6。
5. 纯 sub-MILP 消融或候选级重放，把方法收益与 single 臂的混合操作序列分离。
6. 使用同一冻结评价器的独立留出 problem，并具备显式 scope、clean control 和完整成本账本。

源 snapshot 标记 `development_only=true`。只有补齐独立 dev/gapcheck 的真实新增真通过、多种子、预算/成本对照和跨 problem 证据后，才应重新提出新 revision 并重新走完整生命周期；不得直接改写本次 rejected 记录为 promoted。

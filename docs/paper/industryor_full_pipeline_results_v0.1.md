# IndustryOR 全管线结果与旧基线对照

**范围：完整 IndustryOR-100。** 统一使用绝对误差 `|objective-en_answer| <= 0.1`。目标匹配不是完整业务正确率。

## 主要结果

- 新管线目标匹配 **70/100**；初始候选为 56/100。本轮有 14 题从不匹配变为匹配，0 题从匹配变为不匹配；这是目标值变化，不是业务正确性证明。
- 同一批 ID 的旧 z2 为 **74/100**，新管线差值 **-4 题**；改善 4 题，退步 8 题，**没有超过旧 z2**。
- 独立业务审计仅覆盖 8 个已注册 ID：初始正确 0，最终正确 2；审计不完整或 blocked 的 ID=[4, 8, 9, 20, 25, 48]。其余题目没有完整业务验证，不计作业务正确。
- 有明确初始业务违例并最终恢复的题目：ID19(LLM=2, deterministic=0); ID21(LLM=1, deterministic=1)。这里区分真实语义恢复与仅有名称/导出证据不足。
- runner error=0，错误业务接受=0， harmed-win=0。本轮初始完整业务正确为 0，回滚为 0，所以 harmed-win=0 不是充分的 win-safe 证明。

这些差分不是严格消融：新旧服务 revision 未被证明一致，采样也没有共享随机种子。不能将差值全部归因于 Witness、确定性修复或 DAG，也不据此声称 SOTA 或通用自进化。

## 同一分母的结果表

| 方法 | n | 目标匹配 abs≤0.1 | exec_ok | optimal |
|---|---:|---:|---:|---:|
| 旧 z0（日志复算） | 100 | 35 | 50 | 49 |
| 旧 z1（日志复算） | 100 | 60 | 93 | 92 |
| 旧 z2（日志复算） | 100 | 74 | 100 | 99 |
| 新 Qwen + 当前管线 | 100 | 70 | 99 | 99 |

COOPA 的公开 76/100 只作不同模型与配置的参考，不与本表构成同条件排名；数值差为 -6，不称为同条件超越。

## 独立业务审计

这里重新读取每轮 `solution.json` 并调用独立评分器，不信任 solver 的 `optimal` 或打印目标值。`business_unverified` 和 `invalid_solution` 都不等于业务错误；后者表示当前证据无法完成审计。只有 `complete` 且规则违例才是明确业务拒绝。

| ID | 初始审计状态 | 最终审计状态 | 最终独立通过 | 修复路径 | 主要证据 |
|---:|---|---|---|---|---|
| 4 | invalid_solution | invalid_solution | 否 | LLM=3, det=0, budget_exhausted | 缺少审计变量 x_cows, x_chickens；实际导出名称示例 x_chicken, x_cow, x_sheep |
| 8 | invalid_solution | invalid_solution | 否 | LLM=3, det=0, duplicate_candidate | 缺少审计变量 x_0_0, x_0_1, x_0_2, x_0_3 等20个；实际导出名称示例 x_III_A, x_III_B, x_III_C, x_III_D |
| 9 | invalid_solution | invalid_solution | 否 | LLM=3, det=0, budget_exhausted | 缺少审计变量 x1, x2, x3, x4 等6个；实际导出名称示例 A, B, R, T |
| 19 | complete | complete | 是 | LLM=2, det=0, accepted | 全部已注册业务检查通过 |
| 20 | invalid_solution | invalid_solution | 否 | LLM=3, det=0, budget_exhausted | 缺少审计变量 x1, x2, x3, x4 等8个；实际导出名称示例 B, C, D, R |
| 21 | complete | complete | 是 | LLM=1, det=1, accepted | 全部已注册业务检查通过 |
| 25 | invalid_solution | invalid_solution | 否 | LLM=3, det=0, budget_exhausted | 缺少审计变量 x3, x4, x5；实际导出名称示例 a1, a2, b1, x1 |
| 48 | blocked | blocked | 否 | LLM=1, det=0, business_audit_blocked | 缺少审计变量 x_A, x_B, y, z；实际导出名称示例 d1_minus, d1_plus, d2a_minus, d2a_plus；The initial program has no per-product overtime quantity variables x_A_OT/x_B_OT.；A single overtime-hours variable cannot identify the per-unit profit reductions required by the question and ORThought model. |

## 成本与执行轨迹

- 新管线成功生成 135 次，其中本进程实际调用 135 次；API attempts=135，可见网络重试=0，重试元数据完整=True。
- tokens：prompt=182838，completion=417766，reasoning=323252，total=600604。成功生成墙钟累计 4307.906s；失败生成额外墙钟 0.000s。并行总墙钟 1099.160s。
- 相对旧 z2：LLM 调用 +20 次（+17.4%），completion tokens +104133（+33.2%），已记录 LLM 延迟 +865.106s（+25.1%）。
- 候选评估 135 次，实际 SCIP 135 次，缓存执行复用 0 次；确定性变换 1，失败变换 3，回滚 0。

| 旧方法 | LLM 调用 | 已记录 completion tokens | token 记录覆盖 | 已记录 LLM 延迟(s) | 延迟记录覆盖 |
|---|---:|---:|---:|---:|---:|
| z0 | 100 | 279222 | 100/100 | 3120.500 | 100/100 |
| z1 | 179 | 158682 | 100/100 | 1814.700 | 100/100 |
| z2 | 115 | 313633 | 100/100 | 3442.800 | 100/100 |

旧日志没有与新管线完全相同的 DAG/插桩成本字段，因此不伪造旧的 DAG 开销。

## 结果分类与失败原因

分类由原始执行和独立业务证据重新推导；原 runner 标签保留在 `comparison.json`。`invalid_solution` 归入 `business_unknown`，不冒充已知业务错误。

| 分类 | 题数 |
|---|---:|
| business_audit_blocked | 1 |
| business_correct | 2 |
| crash | 1 |
| objective_matched_business_unknown | 4 |
| objective_matched_business_unverified | 64 |
| objective_mismatch_business_unknown | 1 |
| objective_mismatch_or_suboptimal | 27 |

本轮初始→最终目标恢复 ID：[2, 16, 17, 22, 26, 34, 50, 51, 54, 59, 67, 82, 96, 99]；目标损失 ID：无。
相对 z2 改善的 ID：[16, 18, 50, 59]。
相对 z2 退步的 ID：[12, 14, 20, 30, 47, 49, 78, 88]。
重复候选停止 ID：[8]。

### 历史执行与修复信号

以下信号可出现在后来成功的候选之前，不等于最终失败题数。原始 stderr 和逐轮轨迹均保留。

| 导出错误 | 发生次数 |
|---|---:|
| ValueError: expected exactly one top-level model.optimize() call | 2 |

| crash 最后一行 | 发生次数 |
|---|---:|
| `AttributeError: 'pyscipopt.scip.Model' object has no attribute 'exp'` | 1 |
| `AttributeError: 'pyscipopt.scip.Model' object has no attribute 'getConsByName'` | 1 |
| `Exception: SCIP: method cannot be called at this time in solution process!` | 1 |
| `KeyError: 'A'` | 3 |
| `KeyError: 'I'` | 1 |
| `KeyError: 0` | 1 |
| `TypeError: addVar() got an unexpected keyword argument 'v'` | 9 |
| `ValueError: Nonlinear objective functions are not supported!` | 1 |

ID 19 的确定性修复失败：ValueError: no matching PySCIPOpt variable for solution.variables.x_A

ID 20 的确定性修复失败：ValueError: no matching PySCIPOpt variable for solution.variables.x1；ValueError: no matching PySCIPOpt variable for solution.variables.x1

### 未匹配题目的逐题证据

| ID | 新目标 | 参考目标 | 旧 z2 目标 | 执行/求解状态 | 停止原因 | 分类 | 观测证据 |
|---:|---:|---:|---:|---|---|---|---|
| 1 | 219144 | 219888 | 196216 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 5 | 18.9857 | 18.6943 | 18.9857 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 6 | 10750 | 10755 | 10750 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 7 | 904590 | 468510 | 904590 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 11 | 4273 | 3867 | 4273 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 12 | 15600 | 43200 | 43200 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 14 | 153.333 | 123.8 | 123.8 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 15 | 431 | 168 | 431 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 20 | 960 | 956 | 956 | ok/optimal | budget_exhausted | objective_mismatch_business_unknown | 缺少审计变量 x1, x2, x3, x4 等8个；实际导出名称示例 B, C, D, R |
| 23 | 24000 | 21500 | 24000 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 27 | 1146.57 | 1146.41 | 1146.57 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 29 | 5.002e+06 | 2500 | 3000 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 30 | 0.0324359 | 32.4359 | 32.4359 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 31 | 1190.57 | 1190.41 | 1190.57 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 32 | 2924.14 | 2924 | 2924.14 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 37 | 0 | 11250 | 0 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 40 | 3.62886e+07 | 4.30908e+07 | 6.18497e+07 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 41 | 1.07264e+06 | 964640 | 464640 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 45 | 712 | 700 | 715 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 47 | 20242 | 20241.8 | 20241.8 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 48 | 0 | 11250 | 0 | ok/optimal | business_audit_blocked | business_audit_blocked | 缺少审计变量 x_A, x_B, y, z；实际导出名称示例 d1_minus, d1_plus, d2a_minus, d2a_plus；The initial program has no per-product overtime quantity variables x_A_OT/x_B_OT.；A single overtime-hours variable cannot identify the per-unit profit reductions required by the question and ORThought model. |
| 49 | 240000 | 208000 | 208000 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 57 | 350 | 600 | 350 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 65 | — | 30500 | 103.333 | crash/infeasible | budget_exhausted | crash | AttributeError: 'pyscipopt.scip.Model' object has no attribute 'getConsByName' |
| 69 | 0 | 20 | 0 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 71 | 630 | 330 | 630 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 78 | 0 | 172 | 172 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 88 | 16.4516 | 1.25 | 1.25 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 97 | -255 | 115 | -605 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |
| 98 | 166667 | 165900 | 166667 | ok/optimal | business_unverified | objective_mismatch_or_suboptimal | 目标不匹配；未注册独立业务审计，不能进一步断言业务原因 |

## 可追溯性与限制

- 核验了 100 份初始响应、135 份执行记录，并重算 19 份业务评分；实际执行的源码快照 13 份。
- `analysis.json` 保存逐题结果，`manifest.json` 登记全集，`comparison.json` 保存逐题新旧差分；每题目录包含 prompt、原始响应、代码、stdout/stderr、执行、轨迹、DAG 和成本。
- 只使用当前注册的 19/20/21 窄修复及 8 题独立审计；未把局部 Witness 或 ID 20 名称适配推广为跨族有效性。
- 初始候选和修复使用同一生成配置；未读取 `en_answer` 生成或修复。旧 79/100 是相对误差 1% 口径，不与本报告混用。

复验命令：`python3 scripts/industryor_full_report.py`；完整测试命令见项目最终回归记录。

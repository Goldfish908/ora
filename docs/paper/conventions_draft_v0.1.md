# 约定/修复模式自动蒸馏草案 v0.1

方法：对全部历史轨迹（round-1 pilot、A 反馈环、B 预求解闸门、B' crash guard）做零 LLM 成本的确定性挖掘——guard AST 规则在每份 sandbox gen.py 上重放、stderr 崩溃签名聚类、失败类逐轮粘连率（同一 cell 相邻两轮同失败类 = 点反馈未被吸收）。

> 注意：m1_presolve_loop 的 sandbox 目录命名不含 out-tag，B' 臂会覆盖同名的 B 臂 gen.py。§1 的 B 列因此混入少量 B' 早期代码（≈17 cell，偏低估计 B 的违规数）；§2/§3 基于 jsonl 记录，不受影响。后续臂应在 sandbox 命名中加入 out-tag。

## 1. guard 规则在全部历史代码上的重放命中

| rule | pilot | A | B | B' | 合计 | 跨轮重复 cell 数 | 例 |
|---|---|---|---|---|---|---|---|
| G0 | 20 | 16 | 3 | 0 | 39 | 0 | schema_sol__retail_f1_high_waste_v3 (pilot r1) |
| G1 | 179 | 131 | 70 | 0 | 380 | 47 | retail_f1_52_weeks_v0 (pilot r1) |
| G2 | 105 | 26 | 50 | 0 | 181 | 9 | retail_f1_base_v0 (pilot r1) |
| G3 | 2 | 2 | 1 | 0 | 5 | 1 | schema_sol__retail_f2_ultra_fresh_v2 (pilot r1) |
| G4 | 3 | 2 | 2 | 0 | 7 | 0 | retail_f1_52_weeks_v0 (pilot r1) |
| G5 | 0 | 3 | 1 | 0 | 4 | 0 | retail_f5_strict_service_trap_v1 (A r3) |

跨轮重复（同一 cell 相邻两轮命中同一规则）的 cell 共 54 个——模型在同一回合内收到反馈仍复发，说明需要**事前**先验而非仅靠事后反馈。

## 2. crash 异常签名（stderr 末行聚类，top 15）

| signature | pilot | A | B | B' | 合计 | 例 |
|---|---|---|---|---|---|---|
| `other: Warning: unrecognized optimization sense: min` | 90 | 100 | 60 | 0 | 250 | retail_f1_high_waste_v0 (pilot r1) |
| `AssertionError: given coefficients are neither Expr or number but list [pyscipopt:pyx"]` | 84 | 23 | 41 | 8 | 156 | retail_f1_base_v0 (pilot r1) |
| `IndentationError: expected an indented block` | 19 | 15 | 2 | 0 | 36 | retail_f2_no_substitution_v0 (pilot r1) |
| `NotImplementedError:  [pyscipopt:pxi"]` | 13 | 4 | 16 | 3 | 36 | retail_f4_early_stockout_v0 (pilot r1) |
| `TypeError: 'NoneType' object is not subscriptable` | 28 | 3 | 1 | 0 | 32 | retail_f7_hub_and_spoke_v0 (pilot r1) |
| `TypeError: must be real number, not builtin_function_or_method [pyscipopt:pyx"]` | 8 | 10 | 2 | 0 | 20 | retail_f4_demand_surge_v0 (pilot r1) |
| `AssertionError: given constraint is not ExprCons but bool [pyscipopt:pyx"]` | 2 | 6 | 1 | 1 | 10 | retail_f7_budget_limit_v1 (pilot r1) |
| `AttributeError: 'pyscipopt.scip.Model' object has no attribute 'quicksu` | 2 | 2 | 2 | 1 | 7 | retail_f5_storage_overflow_v0 (pilot r1) |
| `other: Warning: unrecognized optimization sense: 1` | 0 | 5 | 1 | 0 | 6 | retail_f7_ring_routing_v1 (A r3) |
| `AttributeError: 'pyscipopt.scip.Model' object has no attribute 'sum'` | 1 | 2 | 1 | 0 | 4 | retail_f4_supply_risk_v2 (pilot r1) |
| `KeyError: ('SKU_Basic', 'SKU_Basic', 'DCN', N)` | 1 | 1 | 1 | 0 | 3 | retail_f4_supply_risk_v0 (pilot r1) |
| `SyntaxError: invalid syntax` | 1 | 0 | 2 | 0 | 3 | retail_f4_demand_surge_v1 (pilot r1) |
| `KeyError: ('SKU_Premium', 'SKU_Basic', 'DCN', N)` | 0 | 2 | 1 | 0 | 3 | retail_f4_supply_risk_v0 (A r2) |
| `KeyError: 'SCIP: the parameter with the given name was not found! [pyscipopt:pyx"]` | 0 | 1 | 2 | 0 | 3 | retail_f8_labor_constraint_v2 (A r3) |
| `FileNotFoundError: [Errno N] No such file or directory: 'scenario.json'` | 2 | 0 | 0 | 0 | 2 | retail_f1_base_v0 (pilot r1) |

## 3. 失败类粘连率（相邻两轮同失败类）

| failure class | 转移总数 | 粘连次数 | 粘连率 |
|---|---|---|---|
| crash | 194 | 75 | 39% |
| witness_infeasible | 170 | 140 | 82% |
| timelimit_no_incumbent | 14 | 0 | 0% |
| suboptimal | 8 | 6 | 75% |
| declared_infeasible | 5 | 3 | 60% |
| no_solution_dump | 1 | 0 | 0% |

## 4. 候选事前约定（按历史命中量排序）

以下文本可注入生成 prompt 作为 memory/先验；括号内为历史命中证据。

- **[G0]** Code must parse as Python 3 (no syntax errors). (命中 39 份代码，跨轮重复 0 cell)
- **[G1]** PySCIPOpt setObjective: sense must be the string "minimize" or "maximize" (never "min"/"max"); pass sense as a keyword. (命中 380 份代码，跨轮重复 47 cell)
- **[G2]** setObjective takes ONE expression, not a Python list; sum terms with quicksum([...]) first. (命中 181 份代码，跨轮重复 9 cell)
- **[G3]** Build comparisons ONLY inside addCons(...); never use <=, >=, == on expressions in if/assert/bool context (it raises TypeError). (命中 5 份代码，跨轮重复 1 cell)
- **[G4]** quicksum is a module-level function (from pyscipopt import quicksum), not a Model method (m.quicksum does not exist). (命中 7 份代码，跨轮重复 0 cell)
- **[G5]** setParam only with real SCIP parameter names (e.g. limits/time, limits/gap, presolving/maxrounds); never invent parameter names. (命中 4 份代码，跨轮重复 0 cell)

crash 签名中未被 guard 规则覆盖的高频项，是 guard 规则扩充的候选：

- `AssertionError: ... neither Expr or number but list` 共 156 次，但 G2 重放命中 181 ——G2 只覆盖**字面量** list 参数，经变量间接传入（`obj=[...]; setObjective(obj)`）漏检。候选扩充：简单数据流（Name=List 赋值流入 setObjective 调用）。
- `NotImplementedError`（pyscipopt）共 36 次：多为表达式比较/链式比较的运行时形态，与 G3 同源但 AST 形态不同，候选扩充 G3 覆盖更多上下文。


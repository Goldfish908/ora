# Scoped IR 语义资产阶段里程碑 v0.1

日期：2026-11-13 · 状态：长期目标的前三个里程碑完成；不是通用自进化或最终 SOTA 证明。

## 1. 机制资产库

`assets/scoped_ir/` 现有六个机制模板，均通过独立 `must_fire/must_pass`：错误检出 100%、干净误报 0、UNKNOWN 0。

| 机制 | 作用 | 验证 |
|---|---|---|
| makespan | 并行完成时间取 `max`，不累加 | 正确解通过，错误求和被检出 |
| objective_recompute | 用决策变量和常数独立重算目标 | 目标误报被检出 |
| resource_bound | 线性资源上下限检查 | 越界被检出，干净解通过 |
| variable_domain | 有证据时检查整数变量域 | 连续变量被检出，整数解通过 |
| state_conservation | 分别检查期初状态与流量守恒 | 两类独立反例被检出，干净解通过 |
| indicator_link | 有独立证据时检查数量与二元指示变量 | 两个方向的违规被检出，证据篡改被拒绝 |

实现：`ora_agent/scoped_assets.py`、`scripts/scoped_assets_validate.py`。
结果：`work/scoped_assets/validation_v0.1.json`。

## 2. 两个自然语义恢复

### 2.1 Makespan：`prob_104`

初始代码将并行时间写成 `0.5F + 1.5S`，独立目标为 62.5。makespan 资产报告 lhs=62.5、rhs=37.5、delta=25。

修复后代码新增 `TotalTime`，分别约束：

```python
T >= 0.5 * FertilizerUnits
T >= 1.5 * SeedsUnits
```

最终独立目标值 37.5，业务正确，`harmed_win=False`。制品：`work/scoped_ir_e2e_demo_v0.4/prob_104/scoped_ir/final.json`。

### 2.2 目标重算：`prob_229`

文本修复曾把接受治疗人数错误改成两种药总数，目标值 633。目标重算资产将其纠正为治疗药数量，报告 lhs=633、rhs=50、delta=583。

修复后恢复为 181，独立公式重算也通过，`harmed_win=False`。制品：`work/scoped_ir_e2e_demo_v0.4b/prob_229/scoped_ir/final.json`。

这两个案例分别来自不同错误机制，均为完整 NL→SCIP→审计→修复→独立评分路径上的真实恢复，不是 checker 放行但独立评分错误的幻影。

## 3. 冻结模板跨实例复用（v0.2 复核后不予晋升）

**状态修正：下列 v0.1 是旧技术演示，不是业务恢复或资产晋升证据。v0.2 已拒绝这次迁移并回退。**

旧演示使用 `variable_domain` 模板，仅重新绑定 MAMO 的四个食物变量：

- 初始 `x_Food_4=35.535714`，目标值 71.071，公开答案 72；
- 变量域审计报告 `lhs=35.5357`、`rhs=36`；
- 通过 AST 将变量类型改为整数，未重新 LLM authoring，未调用 LLM repair；
- 最终 `x_Food_4=36`，公开目标值 72。

旧制品：`work/scoped_ir_mamo_reuse_v0.1/analysis.json`。

复核发现，题面没有明确整数要求，也没有独立整数域参考；旧 `independent_validation=True` 只是自我声明，不能替代证据。公开目标值恰好变成整数答案，不足以证明整数建模是正确业务语义。

因此 v0.2 删除该布尔绕过，gate 返回 UNKNOWN/拒绝，保留初始解，零新求解和零 LLM 调用。新制品：`work/scoped_ir_mamo_reuse_v0.2/analysis.json`；八题作用域复核：`work/scoped_ir_mamo_scope_v0.2/analysis.json`。技术模板仍可被绑定，但没有证据支持的实例不得晋升。

## 4. 当前边界

- 资产目前以人工/LLM 辅助整理与独立验证为主，不宣称自动 memory 进化。
- scoped IR 只检查已编码不变量，不证明整个模型与业务语义等价。
- MAMO 案例只有公开目标值评分，不提供完整的变量级业务语义证明。
- 后续仍需在新问题族验证更多模板复用、自然错误覆盖和 win-safe，再考虑冻结终验。已实现的 repair controller 及其边界见第 9 节。

## 8. A：状态初始化与守恒资产

### 8.1 资产与独立验证

新增 `assets/scoped_ir/state_conservation_v0.1.json`，由 `ora_agent/scoped_assets.py` 编译为两个独立不变量：

1. `state_conservation_initial`：期初状态等于题面或有独立证据支持的边界值；
2. `state_conservation_flow`：`next = previous + inflows - outflows`，允许多个带系数的流入/流出项。

验证不是一个混合反例，而是分别构造：

- `clean`：期初值与流量关系都正确；
- `wrong_initial`：流量自洽，但期初边界错误；
- `wrong_flow`：期初边界正确，但下一期不守恒。

结果为错误检出 `2/2`、干净误报 `0/1`、UNKNOWN `0/3`。通用验证器现在支持同一资产的多个独立错误反例，不只支持单一 `wrong`。前四类资产也全部重新通过验证。

制品：`work/scoped_assets/validation_v0.1.json`。

### 8.2 真实 SCIP 求解与冻结模板复用

`scripts/scoped_ir_state_conservation.py` 构造两个**受控合成**库存问题。初始模型允许自由的非负期初库存，因此可以用不存在的库存满足需求，使生产成本幻影般地降为 0。资产只根据期初违规反馈插入明确的期初约束，再实际运行 PySCIPOpt/SCIP；不使用独立评分结果指导修复。

| 案例 | 初始目标值 | 修复后目标值 | 独立评分 | harmed_win |
|---|---:|---:|---|---|
| factory_stock：stock/production | 0 | 10 | 业务正确 | 0 |
| warehouse_inventory：opening/receipts | 0 | 6 | 业务正确 | 0 |

两例均为 `initial fired → final checker passed → initial independent score incorrect → final independent score correct`。汇总为 `checker_recoveries=2`、`final_unknown=0`、`harmed_win=0`、`authoring_llm_calls=0`、`repair_llm_calls=0`。

第二例使用同一冻结机制与代码，仅把字段重新绑定为 opening/closing/receipts/shipments。独立评分器另外检查需求、产量范围、目标重算和由显式需求与单位成本推导的最优值，不把资产自身 verdict 当作真值。

制品：`work/scoped_ir_state_conservation_v0.1/analysis.json`，以及每例的 `question.txt`、`binding.json`、`spec.json`、初始/修复代码和 `solution.json`。

边界：这是机制与模板复用验证，**不是自然数据集上的新增语义恢复**。确定性代码修复目前要求 solution 字段能对应到 PySCIPOpt 的具名 `addVar` 赋值，并能定位 `optimize()`；不满足时显式拒绝，不宣称能修任意生成代码。

## 9. B：Progress-aware repair controller

### 9.1 实现的动作与无进展判定

新增 `ora_agent/repair_controller.py`，通过 `scripts/scoped_ir_e2e.py --progress-controller` 接入原有修复环；默认仍运行固定环，历史对照不被改写。

控制器每轮读取代码 SHA-256、规范化失败签名、执行记录、审计证据、checker 状态和剩余预算，并保留动作历史：

| 状态 | 动作 |
|---|---|
| 候选已通过现有检查 | `stop: accepted`，不再被后续候选覆盖 |
| 剩余预算为 0 | `stop: budget_exhausted` |
| 独立反例门拒绝 checker | `repair_checker_required`，不把该 checker 用于接受候选 |
| 解存在但证据不足/UNKNOWN | `acquire_evidence_required`，不把 UNKNOWN 当作通过 |
| 已知 PySCIPOpt `sense="max"/"min"` 错误 | `specialized_api_repair` |
| 首次局部失败 | `local_patch` |
| 局部修复后失败签名不变 | `regenerate` |
| 重新生成后仍是同一失败 | 在剩余预算内提前 `stop` |

无进展包括“修复前后代码完全相同”或“失败签名不变”。因此仅改变量名或输出格式、却仍产生同一错误，不算语义进展。已知 API 修复用 AST 定位 `setObjective` 的字面量参数，把 `max/min` 分别改为 `maximize/minimize`，不是全局文本替换。

当前没有可用的外部证据获取器和通用 checker 自动修复器，所以这两种请求会明确停止并记录原因；已有独立验证的 fallback checker 仍由原门控路径使用。这里没有学习策略，也不宣称 RSI。

### 9.2 `prob_021` 共享初始对照

`scripts/repair_controller_compare.py` 使用相同的自然初始候选、相同冻结 witness 和最多两次修复预算。固定臂重放此前保存的两次 LLM 响应，并重新执行 SCIP；控制臂对相同初始代码执行确定性 API 修复，再走同一 scoped IR 审计和 NLP4LP 独立专家评分。

| 指标 | 固定两次 LLM 修复 | Progress controller |
|---|---:|---:|
| 最终业务正确 | 否 | 是 |
| 最终目标值 | 无解 | 81000 |
| 独立目标值误差 | 无 | 0 |
| LLM 修复调用 | 2 | 0 |
| 修复 prompt+completion tokens | 2216 | 0 |
| 含共享 authoring 的历史 token 总计 | 4318 | 2102 |
| 无进展修复 | 2 | 0 |
| harmed_win | 0 | 0 |

固定臂两轮都保留 `sense="max"`；控制臂一轮改成 `sense="maximize"` 后得到 SCIP `optimal`，业务审计和目标值均通过。该结果属于**执行恢复**，`semantic_recovery=False`，不与前面两个自然语义恢复混算。

本轮没有新 LLM 调用，也没有购买外部 API：两臂复用已有生成制品，token 列是原始记录的可比成本，不是本轮新增消耗。局部修复→重新生成→提前停止的分支另有集成回归，但不把模拟失败当作新的自然实验效果。

制品：`work/repair_controller_v0.1/analysis.json` 和 `work/repair_controller_v0.1/prob_021/` 下的逐轮代码、执行与审计记录。

## 10. 复现与最终回归

```bash
python3 scripts/scoped_assets_validate.py
python3 scripts/scoped_ir_state_conservation.py
python3 scripts/repair_controller_compare.py
/home/hewj13/planbb/miniforge3/envs/rl/bin/python3.9 -m pytest -q tests --ignore=tests/test_m2gen.py
python3 m2gen/run_regression.py
```

最终回归：`218 passed`；`m2gen` 输出 `REGRESSION OK`。另行自动核对五个资产的状态、状态守恒的分母、两例 checker/独立评分恢复，以及控制器的目标值、成本和 `harmed_win`，结果为 `A+B evidence consistency: PASS`。

上述结果仍是开发期机制证据；没有使用 sealed 集调参，没有宣称跨域自动进化，也没有用单例推导整体修复成功率或 SOTA。

## 5. 适用边界与 win-safe 扩展

在 8 个 MAMO mix8 案例中，变量域模板只在独立验证的可数案例 24 上激活，其余 7 个连续/混合变量案例均为 `not_applicable` 并保持原样：

- `activated=1`、`not_applicable=7`、`improved=1`、`harmed_win=0`；
- 案例 24 从 23.3249 修到公开答案 24；
- 连续/混合案例没有被统一整数化，避免把局部机制误当成普遍规则。

制品：`work/scoped_ir_mamo_scope_v0.1/analysis.json`。

## 6. Checker 自身的独立反例门

新增 `scripts/scoped_ir_gate.py` 与 `scripts/scoped_ir_e2e.py --gate-artifacts` 接口。对 `prob_104` 的原始 LLM 加法 scoped IR，独立门结果为 `rejected`，干净误报 100%；curated makespan 为 `accepted`，干净误报 0。

随后门控版实际运行中，生成的有效 makespan scoped IR 通过独立反例门，并在一轮内完成修复，最终独立评分 37.5。`fallback` 的“拒绝原资产→使用已验证备选资产”路径另有单元测试覆盖。

制品：`work/scoped_ir_gate_v0.1/analysis.json`、`work/scoped_ir_e2e_gated_v0.4c/prob_104/scoped_ir/final.json`。

这说明：**checker 本身也必须经过独立验证，不能因为是声明式 JSON 或规则化资产就默认可信。**

## 7. 跨业务对象的模板复用

新增 `scripts/scoped_ir_mamo_scope.py --scope-config` 与 `--baseline-tag`，将变量域模板应用到食物、员工和帆船案例，并保留连续/混合对照：

- 案例 10：8.2727 → 9，恢复公开答案；
- 案例 13：25.3565 → 27，恢复公开答案；
- 案例 206（员工）与 207（帆船）保持原有正确结果；
- 连续/网络流、连续生产、散装原料和运输网络共 4 个案例均为 `not_applicable`，未被错误整数化。

汇总为 `activated=4`、`not_applicable=4`、`improved=2`、`harmed_win=0`，且 `authoring_llm_calls=0`、`repair_llm_calls=0`。

制品：`work/scoped_ir_mamo_validation_scope_v0.1/analysis.json`。

这表明模板复用的是“有独立证据支持的变量域机制”，而不是特定食物字段或某道题的修复答案。


## 11. 下一阶段更新

新增 `indicator_link` 资产及独立来源哈希校验。最新跨域、非 LLM 排序与 Open-Jev 冒烟证据集中见 `docs/paper/next_stage_evidence_v0.1.md` 和 `docs/paper/open_jev_repair_smoke_protocol_v0.1.md`。

严格 gate、初始候选回退与实际 LLM 调用计数后的 `prob_021` 对照见 `work/repair_controller_v0.3/analysis.json`；本文前述 v0.1 制品保留为历史版本，不覆盖。

# Crash 残余挖掘报告 v0.1(B 臂 37 例归因)

日期：2026-11-02。数据：F14 B 臂终态 crash cell(n=37,on 模式），逐例取
`stderr_tail` + `return_code` 归因。口径与 `scripts/psv_online_analysis.py` 一致。

## 1. 归因分布

| 崩溃模式 | 例数 | 占比 | 典型报错 | 性质 |
|---|---|---|---|---|
| `setObjective(sense="min")` | 19 | 51% | `Warning: unrecognized optimization sense: min`(随后 rc=1) | PySCIPOpt API 误用：合法值是 `"minimize"` |
| 目标函数传 list | 7 | 19% | `AssertionError: given coefficients are neither Expr or number but list` | 应传 Expr/quicksum，传了 Python list |
| 表达式上非法比较 | 5 | 14% | `Expr.__richcmp__ NotImplementedError` | 对 PySCIPOpt Expr 用 `==`/链式比较 |
| SCIP 参数名错 | 3 | 8% | `KeyError: SCIP: the parameter ... not found` | `setRealParam` 参数名笔误 |
| `m.quicksum` | 2 | 5% | `AttributeError: Model has no attribute quicksum` | quicksum 是模块函数不是方法 |
| SyntaxError | 1 | 3% | EOL while scanning string literal | 生成截断 |

**前三类合计 31/37(84%)，全部是 PySCIPOpt API 误用**——不是数学建模错误，
不是逻辑错误，是"库的习惯用法"层面的固定模式。

## 2. 关键判断

1. **崩溃是高度可压缩的**:84% 集中在 3 个固定 API 模式，且每个都有确定性的
   静态判据（AST/正则即可检出：`sense="min"`、目标参数为 list、Expr 上的 `==`)。
2. **与 witness/闸门的错误层正交**：这些代码从没走到求解，语义层验证器对它们
   无能为力——证实 F14 §5 的判断：闸门消化语义层后，瓶颈迁移到工程层。
3. **修复环对 API 误用效率低**:A/B 两臂的 crash 反馈环内修复率都不高
   (A 臂 crash-triggered 172 轮仍有 18 残余；B 臂 136 轮余 37)——LLM 对
   "unrecognized optimization sense" 这类 warning-not-error 信号不敏感
   （报错信息里没有直接说"用 minimize")。
4. **与闸门的交互值得注意**:B 臂 crash 残余(37）高于 A 臂(18)。假说：闸门
   缺口反馈引导 LLM 重写目标函数段，重写引入了 `sense="min"` 等新 API 错误。
   待 crash 防护层上线后验证此假说（若假说成立，B' 臂 crash 应回落到 ≤18)。

## 3. 防护层设计（crash guard v0.1，下一步实现）

位置：生成代码之后、闸门之前（最便宜的检查最靠前）。

确定性规则（纯 AST/正则，零 LLM 成本）:
1. `setObjective` 的 `sense` 关键字必须是 `"minimize"`/`"maximize"` 字面量；
2. `setObjective` 第一个参数不得为 list 字面量/ListComp（应包 `quicksum`);
3. 禁止对 `addVar` 返回值/Expr 使用 `==` 比较（AST: Compare 节点左/右为
   Expr 且 op 为 Eq);
4. `quicksum` 必须从 pyscipopt 导入后作为函数调用，禁止 `m.quicksum`;
5. `setRealParam`/`setIntParam`/`setParam` 的参数名白名单校验。

检出 → 生成针对性修复提示（"sense 应为 minimize")→ LLM 重写（不求解）。
与闸门共用反馈通道，单独记 `guard_checks` 字段。

## 4. 度量计划

- 离线：对 380 个 round-1 gen.py 跑 guard，报告检出率/误报率（对照 witness
  ground truth);
- 在线：B' 臂（闸门+guard）vs B 臂，主指标 crash 残余、真成功率、求解调用；
- 假说检验：若 B 臂 crash 膨胀确由闸门反馈重写引入，B' 应回落至 ≤A 臂水平。

## 5. 实现与离线对照结果（2026-11-02)

实现：`scripts/guard_check.py`(G0–G5 六条确定性规则，AST 级）;
集成：`scripts/m1_presolve_loop.py` 在闸门之前插入 guard 环（`--guard-turns`,
默认 1 次重写预算，预算耗尽或检出失败均放行；记录 `guard_checks/guard_turns`
字段）。冒烟测试通过（guard 无命中时走原路径，gate→solve→witness 正常）。

离线对照（380 个 round-1 gen.py,witness ground truth):

| 类别 | 检出率 | 说明 |
|---|---|---|
| crash(263) | **73.8%**(194) | G1 sense 误用 173 + G0 语法 20 + G4 quicksum 14 |
| phantom(104) | 1.9%(2) | 低干扰 |
| win(13) | **0%(0)** | 零误报 |

未覆盖的 69 个 crash：运行时数据键/维度错误（KeyError 数据字段等），静态规则
不可检出，属于下一轮（数据契约检查）的射程。

设计迭代记录：G3(Expr 比较）初版误报 100%（把 `addCons` 里的合法 `==` 全拦）,
收窄为"仅非 addCons 上下文或链式比较"后 win 误报归零。

在线 B' 臂（5 分片）已启动，完成后补主表。

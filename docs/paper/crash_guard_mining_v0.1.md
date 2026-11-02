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

实现：`scripts/guard_check.py`(AST 级确定性规则）;集成：
`scripts/m1_presolve_loop.py` 在闸门之前插入 guard 环（`--guard-turns`,
默认 1 次重写预算，预算耗尽或检出失败均放行；记录 `guard_checks/guard_turns`
字段）。冒烟测试通过（guard 无命中时走原路径，gate→solve→witness 正常）。

规则由蒸馏挖掘（`scripts/distill_conventions.py`，见
`docs/paper/conventions_draft_v0.1.md`）驱动迭代，每步均离线对照验证：

| 版本 | 变化 | crash 检出 | phantom 误报 | win 误报 |
|---|---|---|---|---|
| v0.1 | G0–G5 初版 | 73.8% (194/263) | 1.9% | 0% |
| v0.2 | G2 数据流（变量间接传 list) | 91.6% (241/263) | 1.9% | 0% |
| +G6 | `data=None` 遮蔽（32 次 NoneType 崩溃全归因于此） | 93.9% (247/263) | 1.9% | 0% |
| v0.3 | G7 `m.infinity` 未调用（20 次）+G8 幻觉文件名+G4 驼峰+G6 三元形态 | **97.0% (255/263)** | 1.9% | **0%** |

迭代中发现并修复的两类缺口：

1. **G2 只查字面量**:155 次 `AssertionError ...list` 崩溃中 G2 初版命中 0——
   实际代码多是 `obj=[...]; setObjective(obj)` 间接传递。补简单数据流
   (Name=List 赋值跟踪，被 quicksum 重赋值则解除）。
2. **G6 泛化过度再收窄**:"禁止一切 data 重赋"会把 20 个 phantom cell 误伤
   (21.2% 误报）；收窄为"None 产生式"（直接 `=None` 或 `... if C else None`)
   后误报回落 1.9% 且检出不变。

残余 8 个未检出 crash:NotImplementedError 的 G3 难形态（变量级表达式比较，
静态判定误报风险高）与语义性 KeyError（幻觉数据键，需数据契约检查）——
静态规则性价比低，留给运行时防线。

在线 B' 臂（5 分片，v0.1 guard）运行中，完成后补主表；v0.2/v0.3 留给后续臂。

## 6. B' 早期信号：错误级联与 guard 覆盖率分层（2026-11-02，部分数据）

B' 前 ~70 条记录中 22 次 crash，用 guard v0.3 对其 sandbox 代码重放：

- **18/22 可被 v0.3 在检查时刻捕获**——这些正是 v0.1 覆盖不到的类别
  (G2 数据流 list、G6 三元 None、G7 infinity 未调用、G8 幻觉文件名）。
  残余 4 例：NotImplementedError ×3(G3 难形态）+ 语义 KeyError ×1。
- **错误级联**：8 例 guard v0.1 已触发（7×G1、1×G5)、LLM 重写一次后仍
  crash——重写修好了 sense，但同一份代码下一层的 `AssertionError list`
  (5 例）/NotImplementedError(2 例）/KeyError(1 例）立刻暴露，而
  guard 预算（1 次/轮）已耗尽只能放行。
- **设计结论**：错误在代码里是"千层饼"式分层，guard 的价值与其首轮报告的
  **完备性**强相关——v0.3 首轮即报告全部层级，一次重写拿到完整清单，
  级联基本消除；v0.1 + 1 次预算 = 打地鼠。这为"先用最全覆盖的 guard,
  预算集中在一次高质量重写"的设计提供了实证。

（待 B' 全量完成后在主表验证以上早期信号。）

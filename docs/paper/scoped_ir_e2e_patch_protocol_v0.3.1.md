# Scoped IR 端到端开发补丁协议 v0.3.1

日期：2026-11-12 · 状态：v0.3 失败分析后的开发迭代；不是独立验证。

## 1. 原始负结果

v0.3 的 8 题三臂均已完成：

- `prob_104`：scoped IR 与生成器共同把并行时间写成加法，漏检真实目标语义错误；
- `prob_021`：连续两轮重复 `sense="max"`，未改成 PySCIPOpt 的 `"maximize"`；
- 原始真实语义修复成功为 0。

本补丁只验证能否修复这两个已定位的工程/表达缺口，不能删除原始失败或宣称泛化。

## 2. 两个开发改动

1. 在 DVSA 表达式与 scoped IR 中增加 `max`/`min`，并允许题面为并行任务、makespan 时显式选择它们，而不是强制求和。
2. 在执行反馈中，对已知 `unrecognized optimization sense: max/min` 明确给出 PySCIPOpt 的 `"maximize"`/`"minimize"` 写法。该规则来自既有工程经验，不使用答案或专家公式。

## 3. 运行范围与口径

- 仅运行 `prob_104` 与 `prob_021` 的 scoped IR；
- 复用 v0.3 完全相同的初始代码和解、参考 schema 和独立评分器；
- 使用新目录 `work/scoped_ir_e2e_patch_v0_3_1`，保留 v0.3 原始制品不变；
- 输出独立标记为 post-hoc development patch，不纳入 v0.3 的主对照统计；
- 真正 recovery 必须同时满足：初始审计违规、后续检查通过、独立业务评分正确且初始业务不正确；代码崩溃恢复另记为 execution recovery；
- 若补丁失败，不继续调 prompt 或扩大数据集。

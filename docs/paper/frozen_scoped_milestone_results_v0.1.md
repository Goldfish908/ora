# 新初始冻结评估结果 v0.1

状态：六题生成与对照全部完成；不是整个系统的首次 frozen，不是 SOTA 或自进化证明。

## 1. 协议与边界

协议：`docs/paper/frozen_scoped_milestone_protocol_v0.1.md`。

六题为 BWOR-002/003/005/006/010/012。初始候选由固定 Qwen3.8-27B snapshot 离线生成，每题一次，不重试、不改 prompt、不补题。生成器只看到真实题面和共享变量声明，未看到独立参考约束、目标表达式或公开答案。

这些题曾用于旧 DVSA 终验。本轮结论是**新初始候选与本版 scoped/controller 的首次评估**，不是整个系统首次 frozen，也不与旧生成器结果作因果比较。参考模型是盲建并经公开目标校验的参考，不是专家金标。

## 2. 初始生成结果

| ID | 初始状态 | 独立业务评分/失败原因 |
|---|---|---|
| BWOR-002 | invalid_candidate | variables 未按对象映射表达，违反 schema |
| BWOR-003 | initial_scored | 正确 |
| BWOR-005 | invalid_candidate | 4096 tokens 截断，JSON 不完整，回退解析得到缺少 ID 的子对象 |
| BWOR-006 | initial_scored | 正确 |
| BWOR-010 | initial_solve_failed | `missing path: supply_1`，无有效解 |
| BWOR-012 | invalid_candidate | variables schema 不符合对象映射要求 |

初始业务正确为 **2/6**。没有替换、重写或剔除任何无效候选。

## 3. 三臂冻结对照

| 指标 | no_repair | fixed | progress |
|---|---:|---:|---:|
| 初始独立正确 | 2/6 | 2/6 | 2/6 |
| 最终独立正确 | 2/6 | 2/6 | 2/6 |
| 独立恢复 | 0 | 0 | 0 |
| 第 0 轮保持正确 | 2 | 2 | 2 |
| 回退初始 | 4 | 4 | 4 |
| gate rejected | 4 | 4 | 4 |
| harmed_win | 0 | 0 | 0 |
| accepted_but_reference_incorrect | 0 | 0 | 0 |
| 确定性修复次数 | 0 | 0 | 0 |
| 新增求解次数 | 0 | 0 | 0 |
| 修复 LLM 调用/token | 0 / 0 | 0 / 0 | 0 / 0 |

三个策略在 `BWOR-003`、`BWOR-006` 上均第 0 轮接受，其他四题均回退初始，未接受错误候选。

每题只有一个初始候选，因此没有开展在线排序，未用 offline pairwise 数字代替在线结果。

## 4. 成本

初始生成：

- 模型加载：15.220s；
- 输入 tokens：6,301；
- 输出 tokens：16,161；
- 总 tokens：22,462；
- 六题生成总耗时：3,824.493s；
- 外部 API 调用：0；训练：无。

修复阶段没有新增 LLM 调用、token、确定性变换或求解调用，因为四个失败案例未能通过独立 checker，两个正确案例已在第 0 轮停止。

## 5. 判定与解释

**按预注册规则，当前配置应停止扩展。** 没有独立评分确认的改善。

但这不是“scoped 修复机制无效”的证据：

- 两题初始已正确，无需修复；
- 四题初始结果无效，无法形成可信修复机会；
- 因而不存在能证明 controller 修复效果的有效对照。

真正的工程结论是：

1. **输出契约和初始生成是新流程的前置瓶颈**。变量结构、JSON 截断和缺失 data path 会让后续语义修复无法开始。
2. **fail-closed 是有效的安全机制**。所有无效候选均被拒绝并回退，没有误接受，也没有把正确题修坏。
3. **不能因为以前局部恢复成功，就宣称新域自动泛化或自进化。** 新初始分布下，先生成可靠、可审计的候选仍是前提。

下一阶段应先在已有有效候选和独立业务审计的 RetailOpt、IndustryOR 上验证并积累真实修复轨迹，而不是继续扩大新域、增加训练轮数或引入 OR-Agent 树宽。

## 6. 制品

- 汇总：`work/frozen_scoped_milestone_v0.1/analysis.json`
- 生成成本：`work/frozen_scoped_milestone_v0.1/generation_manifest.json`
- 负结果：`work/frozen_scoped_milestone_v0.1/negative_results.json`
- 本地预检：`work/frozen_scoped_milestone_v0.1/local_validation.json`
- 逐题模型、解、执行、资产、gate、动作与独立评分：同目录各问题子目录。

最终回归：312 项测试通过，`m2gen/run_regression.py` 输出 `REGRESSION OK`。

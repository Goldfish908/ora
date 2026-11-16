# DVSA / BWOR validation 结果 v0.1

日期：2026-11-12。状态：冻结配置上的迁移检查完成；未触 frozen；不启动 SOTA。

## 1. 冻结与参考覆盖

冻结协议：`docs/paper/dvsa_validation_protocol_v0.1.md`。实现与展示层修订依次登记在 `registry_v0.6 / v0.6.1 / v0.6.2 / v0.6.3`。这些修订只开放分析入口、动态化 split/分母和修正驱动参数，未改变资产、prompt、求解预算或方法。

- 全部 16 个 validation 问题均生成参考，12 个满足冻结条件，覆盖率 **75%**。
- 未纳入：020（目标误差 700）、077（目标误差 23）、053（30 处来源不合格）、080（规格无效）。
- 没有人工语义修订、没有公开答案进入参考 prompt、没有根据结果修改模板。
- 各臂共享参考变量声明，但不提供参考约束、目标表达式或公开答案。结论是 schema-conditioned，不是自主变量发现。

参考覆盖：`work/dvsa/bwor_reference/validation/summary.json`。

## 2. 固定制品：检出并未优于文本

12 个参考合格问题共 91 个唯一解制品，其中 79 个受控错误、12 个干净参考解。

| 臂 | 错误检出 | 干净解误报 | UNKNOWN |
|---|---:|---:|---:|
| A0 no-memory | 87.3%（69/79） | 0%（0/12） | 0 |
| A1 文本 memory | **91.1%（72/79）** | 0%（0/12） | 0 |
| A2 DVSA | 83.5%（66/79） | 0%（0/12） | 4 |
| A3 直接旧 witness | 0%（0/79） | 0%（0/12） | 91 |

A2 对 A1 的独有检出为 3:9，精确 McNemar `p=0.146`；对 A0 为 6:9、`p=0.607`。干净误报没有配对差异。A3 全部 UNKNOWN 只说明 RetailOpt schema 不能直接迁移。

成本：A0/A1/A2 均每题一次生成调用；A2 为 67,196 tokens / 457.981s，A1 为 89,946 tokens / 540.5s，A0 为 83,336 tokens / 508.465s。A2 是 binding authoring + 零 LLM 确定性执行，A0/A1 是文本盲评，任务形式不同，不宣称等质量成本优势。

结果：`work/dvsa/bwor_fixed_arms_validation/analysis.json`。
图：`/home/hewj13/paper_icml2027/figures/dvsa_bwor_validation_fixed_arms.png`。

## 3. binding 泛化差异与约定冲突

12 题中 8 题保持完整行为覆盖，但以下 4 题暴露了不同失败层级：

- **009**：参考交付为 `=`，binding 为 `>=`。容量和目标形式完全匹配；交付语义在当前最优解上一致，但对超额交付的判定不同。这是规约约定冲突，不能直接称为漏约束。主指标保留，歧义单列。
- **029**：6 个排班 binding 的 source 箭头/标点不在题面原文中被拒绝，只剩目标 binding，行为覆盖 14.3%。这是 binding authoring 的证据失败。
- **036**：目标 source 不合格，剩余 binding 行为覆盖 60%。
- **056**：目标 source 不合格，`math_min_two` 在所有制品上 UNKNOWN；UNKNOWN 没有被算作检出或误报。

审查记录：`work/dvsa/bwor_binding_eval/validation/convention_review_v0.1.json`。

这些结果否定“dev 上独立 binding 全部有效，因此跨题已普遍可靠”的推断。模板可执行性、证据绑定、自然语言规约歧义和参考构造必须分开评价。

## 4. 自然修复：同等质量，显著减少调用

共享初始为 **9/12 业务正确**，所有方法改善 2 题且 `harmed_win=0`。

| 臂 | 业务正确 | 改善 | 修坏 win | 独立运行修复调用 | 修复 tokens | 修复延迟(s) |
|---|---:|---:|---:|---:|---:|---:|
| A0 no-memory | 11/12 | 2 | 0 | 12 | 93,550 | 505.169 |
| A1 text-memory | 11/12 | 2 | 0 | 12 | 96,391 | 539.515 |
| A2 DVSA | 11/12 | 2 | 0 | **3** | **27,372** | **152.745** |
| A3 direct-legacy | 11/12 | 2 | 0 | 12（复用 A1，实际新增 0） | 96,391（等价） | 539.515（等价） |

A2 对 A0/A1/A3 的逐题 McNemar 均为 0:0、`p=1.0`，没有质量差异。

逐题归因：

- **BWOR-058**：唯一 `dvsa_violation` 自然修复案例。初始目标 36.4，独立目标重算为 28.0；DVSA 给出 20% 租金规则的确定性证据后修复成功。文本和 no-memory 也修好了同一题，因此不是 DVSA 独有收益。
- **BWOR-078**：执行反馈恢复成功，各臂均成功。
- **BWOR-023**：执行失败，三种方法均未修成，按冻结协议不追加预算。
- A2 有 9 次 `no_call`、1 次语义触发、2 次执行反馈触发；只有 1 次算真正语义修复。

结果：`work/dvsa/bwor_repair_validation_analysis/analysis.json`。
图：`/home/hewj13/paper_icml2027/figures/dvsa_bwor_validation_repair.png`。

## 5. 全 16 题覆盖与保守下限

在 12 个参考合格问题上，A0/A1/A2/A3 的业务正确均为 11。将 4 个参考失败问题保守记为未通过，则全 16 题下限均为 **11/16 = 68.75%**。

这只是防止隐藏参考失败的保守视图，不是可与公开排行榜直接比较的 SOTA 分数，也不改变参考合格子集上的机制配对。

覆盖：`work/dvsa/bwor_validation_coverage/analysis.json`。
图：`/home/hewj13/paper_icml2027/figures/dvsa_bwor_validation_coverage.png`。

## 6. 结论与后续纪律

1. **质量主张未成立**：A2 对 A1 的自然业务正确率没有差异，固定制品检出反而较低且未达显著性。
2. **效率与 win-safe 有信号**：A2 仅 3 次修复调用，9 次跳过，所有初始 win 保留；这是保守 gate 的证据，不是普遍自进化证明。
3. **真实语义修复存在，但不独占**：BWOR-058 的 20% 租金目标错误被确定性反馈修复，文本自评也成功。
4. **跨题可靠性受 binding 限制**：证据拒绝、UNKNOWN 和规约歧义是主要失败层级；完整模板代码复用并不自动保证新实例绑定正确。
5. **不启动 SOTA**：按原协议进入 frozen 终验，不改变模板、阈值、参考规则或预算。frozen 结果不得回写资产。

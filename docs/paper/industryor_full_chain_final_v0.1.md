# IndustryOR 全链路、混合选择与独立复现最终结果 v0.1

## 范围与结论纪律

全部 100 题均计入分母，公开指标为 `abs(objective-reference)<=0.1`。实现是 COOPA-inspired，不是官方 COOPA runner；COOPA=76 只作不同模型与配置下的公开参考。数据与冻结候选均为开发采样，不是 held-out。复现覆盖选择阶段，不等于完整生成管线的新采样复现，也不据此宣称 SOTA。

## 完整结构化管线

| 配置 | 最终匹配 | 相对 structured 新增/丢失 | 独立业务正确（8题） | 误接受 |
|---|---:|---:|---:|---:|
| structured | 63 | 0/0 | 4 | 0 |
| +完整 DAG repair | 73 | 10/0 | 7 | 0 |
| +trigger memory | 73 | 10/0 | 6 | 0 |
| +full memory | 74 | 11/0 | 7 | 0 |

每题真实执行 M1→低置信反馈→M2/M3，代码只生成 M1 和 max-min 选中 formulation。DAG 使用原 `ProgressController`，共 3 个候选轮次（首轮+最多两次修复）；Pre-solve/变量绑定、SCIP、独立 Witness、逐轮执行和最终输出节点均有制品。full memory 相对纯 DAG 新增 ID 98、无 win 损失；trigger 新增 ID 98但损失 ID 25。其余 92 题始终保持 `business_unverified`。

## 混合选择与独立复验

混合臂只比较两个实际选择输出：structured full-memory 与 raw k=3 selected；raw oracle 不参与部署。选择顺序为独立业务接受优先、同目标保留 full、执行完整性裁决，其余调用 LLM max-min。三票集成要求至少两票 raw 才选 raw，否则选 full；聚合不读取目标值。

协议冻结后另外执行的三次独立选择结果：

| 复验 | 匹配 | 相对 full 新增 | 相对 full 丢失 | 独立业务正确（8题） | 误接受 |
|---|---:|---|---|---:|---:|
| 选择 run 1 | 77 | [59, 76, 88] | [] | 7 | 0 |
| 选择 run 2 | 78 | [59, 76, 88, 97] | [] | 7 | 0 |
| 选择 run 3 | 78 | [59, 76, 88, 97] | [] | 7 | 0 |
| **三票集成实际输出** | **78** | **[59, 76, 88, 97]** | **[]** | **7** | **0** |

三票集成超过 COOPA 公开参考线 2 题，并保留 full 的全部 74 个 win。每个选择复验有 18 次新调用，三票合计 54 次、252052 completion tokens、372529 total tokens、2855.716s 已记录 LLM 延迟；聚合本身新增调用为 0。输入生成成本分别保留在原 full/raw 报告中，不把缓存复用冒充新请求。

最终 22 个未匹配 ID 为 `[1, 5, 6, 7, 11, 15, 17, 23, 27, 29, 31, 32, 35, 40, 41, 45, 48, 49, 57, 69, 71, 91]`，未从分母删除。

## 验证与制品

- 完整结构化结果：400 条臂结果，100 题，0 runner error。
- 三票复验：100 个逐题投票与最终输出，所有选择 prompt 均未包含 `en_answer`；最终目标匹配已逐题重算。
- 独立业务评分、选中 DAG 节点、轮次和预算均已校验；最终集成实现与协议 SHA256 已核对。
- 完整回归：462 项 pytest 通过；m2gen regression 通过。

主要路径：

- 结构化报告：`docs/paper/industryor_structured_results_v0.1.md`
- 结构化全量数据：`work/industryor_structured_full_v0.4/analysis.json`
- 单选择报告：`docs/paper/industryor_hybrid_results_v0.1.md`
- 首轮三次选择复现：`docs/paper/industryor_hybrid_replication_results_v0.1.md`
- 独立三票集成报告：`docs/paper/industryor_hybrid_ensemble_validation_v0.1.md`
- 独立三票集成数据：`work/industryor_hybrid_ensemble_validation_v0.1/analysis.json`
- 独立三票集成图：`docs/paper/figures/industryor_hybrid_ensemble_validation_v0.1.png`

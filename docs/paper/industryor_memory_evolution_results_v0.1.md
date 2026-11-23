# IndustryOR 工程 Memory 在线进化与冻结测试 v0.1

**范围：回溯开发划分，不是 sealed test；冻结初始代码的 repair-only 对照，不是完整生成复现或 SOTA。**
本报告只统计当前实验目录；任何早期中止的 pilot 都不进入指标。

资产状态：`{'rejected': 1, 'promoted': 1}`。dev=7 个目标任务，gapcheck=6 个目标任务；每个任务三个显式种子。

## 资产生命周期与来源

| asset | 形式 | parent | dev | gapcheck | 最终状态 |
|---|---|---|---|---|---|
| prompt_pyscipopt_addvar_v_001 | prompt | None | 拒绝 | 未进入 | rejected |

**prompt_pyscipopt_addvar_v_001 原文：** When calling pyscipopt's Model.addVar() with both a variable name and a vtype already specified, the name must be passed via the 'name' keyword argument, not 'v'; using 'v' as a keyword triggers a TypeError because the API does not recognize it. If vtype is present and the value assigned to 'v' is a string label (not a domain type), replace 'v=' with 'name=' to correctly register the variable's identifier.

来源：Qwen3.8-27B；split=dev；trace_sha256=`da6e99fcb8c465cf7983966699e61dda6ebbf7061c5cc3b1d976fa8126ee8da6`。
dev 拒绝原因：`['neither_quality_nor_cost_path_passed']`。
| guard_pyscipopt_addvar_v_002 | guard | prompt_pyscipopt_addvar_v_001 | 通过 | 通过 | promoted |

**guard_pyscipopt_addvar_v_002 原文：** When calling pyscipopt's Model.addVar() with both a variable name and a vtype already specified, the name must be passed via the 'name' keyword argument, not 'v'; using 'v' as a keyword triggers a TypeError because the API does not recognize it. If vtype is present and the value assigned to 'v' is a string label (not a domain type), replace 'v=' with 'name=' to correctly register the variable's identifier.

来源：Qwen3.8-27B；split=dev；trace_sha256=`da6e99fcb8c465cf7983966699e61dda6ebbf7061c5cc3b1d976fa8126ee8da6`。

## dev / gapcheck 配对指标

| tier | asset | 执行增益 | 执行误伤 | runner errors | 逻辑LLM调用下降 | 新调用 control→asset |
|---|---|---:|---:|---:|---:|---:|
| dev | prompt_pyscipopt_addvar_v_001 | +0.0% | 0 | 0 | 0.0% | 21→21 |
| dev | guard_pyscipopt_addvar_v_002 | +0.0% | 0 | 0 | 100.0% | 21→0 |
| gapcheck | guard_pyscipopt_addvar_v_002 | +0.0% | 0 | 0 | 100.0% | 18→0 |

## 冻结 test：targeted

任务数=5；每个任务三个种子，因此每组最多 15 个输出。
执行成功：control=15，evolved=15；宏增益=+0.0%，paired execution harm=0。
公开目标匹配：control=6，evolved=6；宏增益=+0.0%，paired objective harm=0。
改善 IDs=[]；损害 IDs=[]。
runner errors=0；独立业务误接受=0。
逻辑修复 LLM 调用：15→0；新增调用：15→0；completion tokens：20485→0。

## 解释边界

只有 promoted 资产进入冻结测试；业务语义未经独立 Witness 的题仍未验证。
执行恢复不等于业务正确，目标匹配只在测试结束后计算，不参与候选、晋升或节点选择。
单机制结果不能外推为通用自进化有效；负结果不通过移动晋升阈值挽救。

机器制品：`/home/hewj13/wm/ora/work/industryor_memory_evolution_v0.2`；协议：`docs/paper/industryor_memory_evolution_protocol_v0.1.md`。

## 2026-11-23 当前工作树复核

- registry 与协议 SHA256 均匹配冻结清单，15 个实现文件中 14 个匹配。
- 当前 `ora_agent/llm.py` 的 SHA256 为 `ced54d7b87414e73e0ed7c572cba9f1118c9f850b67516d5b1f9834c9555a1d9`，与冻结值 `eb2b6f6ebc36813149d52ea1a109addd51cb02419c53f7427de7c7a712d7aa18` 不同。冻结版本可在历史提交 `d0f2944` 中取得；当前文件由后续提交 `58d02d0` 修改。
- 因此上述数字是历史冻结实验结果，**不是当前工作树的重新运行结果**。当前完整 pytest 通过不能替代该冻结实现的复跑。后续全链评价必须建立新的实现快照和冻结清单。
- `test_raw_selected` 未形成完整 `analysis.json`，不纳入本报告指标。上表只有 `targeted` 的 5 题、3 个种子；guard 将修复 LLM 调用从 15 降为 0，但执行成功数和公开目标匹配数均与 control 持平，不能解释为业务正确率提升。

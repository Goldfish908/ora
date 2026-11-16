# BWOR 已保存响应的输出契约重放协议 v0.1

状态：执行前登记。这是历史开发重放，不是新的 frozen 测试，不生成新候选，不声称新的自然泛化。

## 输入与边界

完整使用 `frozen_scoped_milestone_protocol_v0.1.md` 已登记的六题：BWOR-002、003、005、006、010、012。它们及旧结果均已暴露，不能改名 heldout。

输入是 `work/frozen_scoped_milestone_v0.1/` 中已保存的 Qwen 响应。不得重新生成、修改 prompt、选择响应、补全截断 JSON 或将内部子对象提升为完整模型。公开答案仅用于最终评分；参考表达式只能用于已声明的 reference-bound 修复。

## 处理

对全部六题使用同一个当前入口语义：`extract_json → normalize_candidate → problem_id → validate_model → validate_candidate_paths → shared schema → SCIP`。

只有每项恰好含 `name/domain/lb/ub` 且名称合法唯一的变量列表才可转为对象。缺 data path 在求解前拒绝，UNKNOWN 不当通过。原始响应和旧结果不覆盖；保存其路径和 SHA256。

- 无新 LLM 调用；同一固定求解时限 60 秒；
- 归一化形成的有效模型是**契约恢复**，不称新自然模型生成或语义修复；
- 三臂 no-repair、fixed、progress 复用现有 scoped 资产与相同修复器，最多两次修复；
- 每题保存初始、候选、逐轮模型/解、gate、动作、独立参考评分和成本；
- 分开报告 `contract_recovered`、初始业务正确、独立恢复、误接受和 harmed-win。

## 判定与禁止事项

任何 `accepted_but_reference_incorrect>0` 都是停止扩展信号。契约恢复但业务错误不得算成功。fixed/progress 相同不得归因控制器增量。

本重放只回答“当前输出契约能否让既有原始响应进入可靠求解/审计”。下一批新自然候选必须另行预注册，不能借本重放结果宣称 frozen 改善。

```bash
/home/hewj13/planbb/miniforge3/envs/rl/bin/python3.9 scripts/bwor_saved_contract_replay.py
```

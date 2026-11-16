# Witness / 修复框架本轮验证协议 v0.1

## 范围与结论口径

本协议针对已有 NL → PySCIPOpt → Witness → 修复 → 独立评分框架，不另建替代管线。验证重复修复、修 A 引入 B、误/漏触发、UNKNOWN、输出契约、约束数量和差异化预算，以及可回滚的资产复用。

本轮是 **historical development / controlled regression**，不是 frozen/sealed 测试，不声称通用自进化、自然冷启动迁移或 SOTA。本轮不调用新 LLM，不修改 sealed/frozen 数据，不用公开答案作为修复输入。

## 队列与评分边界

- RetailOpt：既有 dev20 的共享初始和已保存四臂轨迹，使用 `scripts/dvsa_win_safe_replay.py` 重放。业务评分沿用旧 Witness 与参考目标；它是源评分口径，不是完全独立的业务语义金标。
- IndustryOR：注册七题 19、20、21、25、4、8、9，共享 `work/industryor_next_stage_v0.1/` 初始。`score_solution` 独立检查变量域、业务约束、目标重算和独立最优性。20 的整数语义来自 ORThought `prob_019/model.txt`，指示关系来自对应 `code.py`，均保存精确片段和 SHA256。
- BWOR：八个预注册候选，按既有规则保留六题六族，排除 schema 不匹配的 BWOR-001 和缺参考制品的 BWOR-042。最终评分使用独立参考模型和解；恢复称 reference-bound development recovery。
- MAMO-ComplexLP：既有 mix8 八题；只有公开目标值评分，不能单独证明业务语义正确。没有显式题面或独立参考支持的整数域不得启用，公开目标值改善不提升为业务恢复。

各数据集只与自身共享初始比较，不把不同评分口径混成总体准确率。

## 修复与接受规则

每题运行 no-repair、fixed、progress 三臂，共享初始和确定性修复器，最多两个修复机会。`fixed` 与 `progress` 同效时只能归因于资产和修复器，不能声称控制器增益。

- 只有 checker gate accepted、当前记录 `status=ok`、未触发违规，且 UNKNOWN/rejected/error 等阻断证据为空时，才可接受候选。
- 无已接受候选时回退初始解；分别保留初始、末候选和最终独立评分。
- 精确重复“失败签名 + 代码 hash + 动作”不得再次执行。
- 违规幅度严格不增且至少一项下降，属于证据进展；修复后出现新错误切换新候选，再生候选继续引入新错误则停止。
- 局部语义错误默认预算 2，复杂语义错误 3，约束数量达到 8 时只允许一次换候选；UNKNOWN 转向补证据，已知 PySCIPOpt API 错误优先专用修复。所有预算来自 `BudgetPolicy`，不由评分结果倒推。
- JSON 必须对应完整授权模型；拒绝截断子对象、错误 problem_id、非法/重复变量和未定义数据路径，状态区分 `contract_invalid`、`invalid_shared_schema`、`solve_failed`。

## 独立标签与资产生命周期

`work/witness_scenario_validation_v0.1/scenarios.jsonl` 分别记录 Witness 作用域标签与业务正确性标签。可行的次优解可以不触发局部 Witness，但业务评分仍不通过。MAMO 缺独立业务标签时保留 null，不擅自补标签。

控制器和契约反例由预先指定的测试 oracle 判定，不能从新控制器轨迹反推标签。自然初始与受控变异分开标记；历史 validation 不更名为新 frozen test。

资产记录保存来源、反例、gate、重放路径、LLM/求解成本、负结果及回滚。MAMO 的拒绝记录不能改写为成功晋升；BWOR 的模板复用只证明开发场景下零 LLM authoring 的有效性，不等于自动进化。

## 验收

1. RetailOpt、IndustryOR 各至少一个共享初始下的可复核改善，且 `harmed_win=0`、`accepted_but_business_incorrect=0`。
2. 至少 20 个独立标注场景，覆盖重复代码、连环错误、误/漏触发、UNKNOWN、ID/JSON/schema、约束数量和预算差异。
3. 至少两个额外数据集/问题族；至少一个冻结机制零 LLM authoring 的有效复用，或明确负结果。
4. 保存 manifest、逐题轨迹、协议、结果和生命周期记录；完整 pytest 与 `m2gen/run_regression.py` 通过。

## 复现命令

```bash
/home/hewj13/planbb/miniforge3/envs/rl/bin/python3.9 scripts/industryor_scoped_loop.py \
  --out work/industryor_scoped_loop_v0.6
/home/hewj13/planbb/miniforge3/envs/rl/bin/python3.9 scripts/bwor_scoped_loop.py \
  --out work/bwor_scoped_loop_v0.2
/home/hewj13/planbb/miniforge3/envs/rl/bin/python3.9 scripts/scoped_ir_mamo_reuse.py
/home/hewj13/planbb/miniforge3/envs/rl/bin/python3.9 scripts/scoped_ir_mamo_scope.py \
  --out work/scoped_ir_mamo_scope_v0.2
python3 scripts/dvsa_win_safe_replay.py
/home/hewj13/planbb/miniforge3/envs/rl/bin/python3.9 scripts/witness_scenario_validate.py
/home/hewj13/planbb/miniforge3/envs/rl/bin/python3.9 -m pytest -q tests --ignore=tests/test_m2gen.py
python3 m2gen/run_regression.py
```

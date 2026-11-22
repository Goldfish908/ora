# Clean-room verified specification evolution protocol v0.1

状态：预注册协议；不包含实验结果。

## 目标

在没有历史规范、memory、修复卡片和调参资产的条件下，验证共享规范提议、局部DAG修复、独立Witness、证据memory、信任管理层和冻结评价能否形成可追溯的真实语义增益。

## 数据与隔离

主数据为ORAgentBench未用于既有实验的单步任务。目标正式切片为四个机制域、每域dev/audit/transfer/final分层；先以 `additive_microfactory_order_planning` 和 `community_battery_peak_shaving` 做dev侧接口冒烟，这两题不进入最终heldout。

- 生成器仅可读取公开题面、公开数据、允许使用的规范版本和dev执行反馈。
- GEPA反思文本不得包含官方评价器实现、参考解、参考目标数值或最终测试错误详情。开发侧代理分可按冻结公式使用dev/transfer参考目标值：最小化要求候选目标不高于参考值+0.1%绝对值，最大化要求不低于参考值-0.1%绝对值；无目标输出为不通过。该数值不进入反思文本。
- dev/audit参考解只供独立Witness初始化和可信审计，不进入生成提示。
- 最终评价只调用官方任务评价器，测试期间规范和memory只读。
- 任务选择不得根据Qwen试跑成绩；只允许依据公开域、历史排除、oracle/verifier健康和资源约束。
- 官方公共skills必须对所有比较臂一致；不把它们计作系统memory。

## 资产与权限

- GEPA候选从 `candidate` 开始，不自动进入正式memory。
- 检查从 `hint_only` 开始，需题面出处、至少3个clean和3个wrong、clean误报0、precision≥1、detection≥0.6、UNKNOWN=0，才可获得局部 `veto_enabled`。
- verdict包括 `pass/fail/unknown/not_applicable`。不适用不等于通过，UNKNOWN不等于安全。
- 规范和检查均记录代码哈希、父版本、适用范围、审计和退休历史。
- 跨题族、跨数据集只继承模板；否决权必须重新审计。
- 测试注册表冻结后，任何写入都报错。

## 评价与对照

- B0：空规范直接生成。
- B1：GEPA共享规范直接生成，衡量首轮规范收益。
- B2：B1加残余DAG，衡量局部修复增量和win-safe。
- B3：B2加经审计的memory，必须在后续任务上与无memory比较。
- 同时报告直接生成和DAG后结果，禁止将两者混为规范收益。

最终主指标为官方 `feasible && quality > 0.4`。GEPA开发侧代理分与最终独立指标分开保存。不得将执行成功、目标值改善或开发侧代理通过直接称为业务正确。

## 修复接受

- 原本正确的输出不进入无目标修复。每题最多3次目标修复；重复代码哈希、连续无目标改善或预算耗尽时停止或换分支，不得无限重试。API错误优先使用容器内确定性签名探测，而非让LLM猜测。
- 非目标高层 `pass→fail` 拒绝。
- 显式目标高层 `fail→pass` 允许进入审核，但必须有题面出处和独立证据。
- 非目标检查默认保持逐项不变；UNKNOWN拒绝。若非目标检查也发生 `fail→pass`，只有在目标已改善且最终所有授权检查均通过时才接受，防止把部分失败或检查洗白当成修复。
- 修复边接受与最终全部门禁分开，避免原始R2将合理修复和洗白一并拒绝。

## 成本与证据链

每个节点保存规范版本、代码哈希、求解状态、目标值、逐层verdict、修复目标、LLM/token/求解成本和接受原因。主曲线绑定数据、模型、规范、Witness、参考目标和评价器版本。

制品生成采用两段协议：先提交精炼 `model.md`，再提交完整 `solve.py` 与日志。`finish_reason=length/max_tokens` 明确记为生成截断失败，不得当作缺失代码、空输出或业务错误。确定性API guard仅使用真实容器已验证的兼容规则，并在完整性检查之前执行，保存原始与修复后代码哈希及全部替换。求解代码还须通过完整性检查：包含求解调用、决策文件输出，且不得含占位符或空函数体；异常处理中的合法 `pass` 不误杀。不满足记为 `incomplete_artifact`，不得进入SCIP或GEPA评分。单阶段与两阶段结果不得混入同一比较曲线。内网Qwen通过 `chat_template_kwargs.enable_thinking=false` 控制长生成时，须在所有比较臂一致记录和使用。

## 负结果

GEPA无提升、memory零晋升、DAG无增益、Witness覆盖不足或跨族失败均如实报告。不得为获得正结果而移动分母、降低授权门槛、改写UNKNOWN或根据最终测试调参。


## v0.6 实施修订（仅适用于后续新实验）

以下修订不回溯改写成 v0.5 的预注册内容。旧运行保留 `implementation.json` 和 `source_snapshot/`；新运行使用新的实现哈希。

### 重放、晋升与冻结

- `scripts/cleanroom_replay.py` 显式选择候选编号和规范哈希，在同一后续批次执行 B0/B1，不产生 GEPA 反思或反馈写回。默认拒绝把 GEPA train/val 任务标为后续独立批次；显式选择集重放必须标为 `selection_set_replay`。
- `scripts/cleanroom_memory.py` 需要 `--independent-replay` 与同批 `--independent-baseline`。候选规范、GEPA 来源文件、实现哈希、任务集合、官方逐题结果必须匹配；空规范到候选规范不得丢失真实 win、增加幻影或产生评价 UNKNOWN。没有这些证据时，memory 拒绝晋升。
- 出处审计同时读取公开题面和真实容器 API 探测。后者来自 `inspect.signature`，不包含参考答案或隐藏评价逻辑；与探测矛盾的 API 规则不得晋升。
- 晋升规范绑定实际开发域并冻结。新域只继承初始化模板，不自动继承检查否决权。若 B3 与 B1 使用相同规范且没有新增的已验证修复资产，二者是同一生成条件，不能把相同结果称为 memory 的增量收益。
- 测试批次不得写回 registry。当前 `repair_bounded` 只允许 dev/audit/transfer；final 不允许把官方错误反馈给修复模型。要在 final 测量 B2，必须先实现由公开题面初始化、与官方评价器实现独立的检查，不能依靠当前 `<domain>_official_task_pass` 冒充独立 Witness。

### 有界修复与成本

- `repair_bounded` 对每题最多进行三次目标修复，使用同一个 RepairDAG 保存父子边。原本正确的输出不修复；重复代码、无证据变化或无授权检查会停止；只有最终门禁通过才替换直接基线，否则回退。
- 每次尝试保存原始制品、guard 后代码、公开 stdout/stderr、官方结果、前后 verdict、目标检查、接受原因与代码哈希。失败生成也按 generation 日志计入 LLM 成本；求解与官方评价分别记录实际 wall time。
- 新诊断将 `UNKNOWN` 限定为官方评价无法给出确定结果。制品不完整、执行错误、业务不可行、质量不足、幻影和评价 UNKNOWN 分开统计。旧记录中的广义 `unknown=not feasible and not phantom` 不能与新 UNKNOWN 直接比较。

### Guard 的工程边界

- 通用 API guard 与题面输出契约修复分离。后者只在指定任务和公开字段出处同时匹配时执行，不能作为跨域 API 能力。
- API 转换必须保持原始源码文本，只局部替换已验证的调用。初版 AST 整体重写曾在 Python 3.11 中引入 f-string 语法错误；该失败保留在 `work/cleanroom_guard_only_replay_v0.6`，修复后的复验在 `work/cleanroom_guard_only_replay_v0.6.1`。
- guard-only 复验不调用 LLM、不反馈给 GEPA。它只衡量 guard 对既有制品的增量，不能归功于 GEPA。

### 运行中工程观察（历史记录，最终结果见下节）

- v0.5 空规范 seed 的 4 题中，1 题业务可行但质量不足、2 题执行错误、1 题制品不完整，真正确为 0；首个 GEPA 候选已被拒绝。完整候选曲线在运行结束后再报告。
- guard-only 的两道 dev 复验中，碳调度题从执行错误变为 `feasible=true`，但质量仍不足；增材题求得 profit=11688.043683670838，却因生成代码未接受真实求解状态 `gaplimit` 而输出空解。因此两题真正确仍为 0。这是执行可评估性改善，不是语义正确率提升。
- 当前 4 题共用 `manufacturing` 标签只是早期技术冒烟分组，包含调度和医疗路由，不能作为同族或跨域证据。后续正式配置必须按公开场景重新标域，并重新初始化适用范围。
- 相关新增测试已覆盖候选哈希、数据隔离、独立晋升、API 转换、源码兼容、反馈隔离、成本统计、win-safe、重复停止与已有正确解保护；全量回归仍需在最终交付前重新执行。


## v0.5 最终结果与后续健康筛选

`work/cleanroom_gepa_guarded_smoke_v0.5/analysis.json` 已完成：50 次 metric calls，wall time 4372.952 秒，2 个接受候选（含 seed）。下表的 dev 和 transfer 都参与了 GEPA 训练或验证，**不是最终 held-out**。

| 候选 | Dev proxy | Dev 真正确 | Transfer proxy | Transfer 真正确 | Transfer 幻影 | Transfer 制品生成失败 |
|---|---:|---:|---:|---:|---:|---:|
| B0/seed | 0/3 | 0/3 | 0/1 | 0/1 | 0/1 | 1/1 |
| C1（接受） | 1/3 | 1/3 | 0/1 | 0/1 | 0/1 | 1/1 |

- C1 在增材 dev 题上为 `feasible=true、quality=1.9999999999996887、profit=11688.090885370839`，seed 同题为 `profit=9942.24908924532、quality=0`。候选规范包含显式 `setMaximize()`、正确 PySCIPOpt 导入和输出检查；在没有单项消融时，不把这些组件分别称为已证明的因果贡献。
- 接受候选没有解决工业供应、碳调度或医疗路由；医疗路由仍因不含 `optimize()` 被制品门禁拒绝。dev 单题增益不能称为迁移增益。
- seed/C1 在两个选择集上的生成成本分别为 323,613 和 337,355 tokens，未记录的旧求解 wall time 不补零。图件为 `work/cleanroom_gepa_guarded_smoke_v0.5_report_v3/gepa_candidates.png`，逐题证据为同目录 `candidate_analysis.json`。
- `work/cleanroom_gepa_guarded_smoke_v0.5_memory_review` 按平局规则选择 C1，但因没有独立重放而拒绝晋升。生成器随后升级到 v0.6，因此不能用不同实现的重放补写 v0.5 的 memory 晋升。
- 真实有界 B0 修复冒烟 `work/cleanroom_bounded_b0_additive_v0.6.1` 在一次无证据改善后停止并回退：真正确不增不减，win-safe=true；含基线生成共 4 次 LLM 调用、38,971 tokens。这是停止/回退证据，不是修复有效率证据。

### 新任务健康检查

候选来源仅为公开工业场景、机制覆盖、包大小与 oracle/评价器健康，不使用 Qwen 成绩筛题。当前结果：

- `second_life_battery_pack_assembly`：官方 `feasible=true、quality=2.0`，可作为 dev/audit。
- `industrial_water_reuse_blending`：官方 `feasible=true、quality=2.0`，可作为独立重放任务。
- `recycled_paper_furnish_planning_lp`：oracle 未产生解，排除。
- `recycling_mrf_stochastic_sorting_plan`：oracle 可行但 `quality=0`，不作为 clean/参考健康任务。
- `maritime_fueleu_bunker_blending_lp`：公开包 697,629 字符，超过 180,000 字符上限，明确排除而不截断。
- `steel_scc_ladle_energy_reschedule`：oracle `feasible=false、quality=0`，排除，不进入独立批次。
- 后续健康检查中，`aerospace_composite_autoclave_scheduling` oracle 未通过而排除；`mass_timber_panel_cutting_plan` 和 `ev_battery_recycling_network` 均为 `feasible=true、quality=2.0`，分别进入独立审计与后续迁移。`semiconductor_ion_implant_scheduling` oracle 同样未通过，未纳入。最终迁移 pilot 为 `configs/cleanroom_transfer_v0.6.json` 中的电池回收网络一题，明确不作泛化准确率声明。

冻结的 v0.6 开发配置为 `configs/cleanroom_formal_dev_v0.6.json`：增材、工业供应、电池装配为 manufacturing/dev，碳调度为 compute_scheduling/transfer。新运行使用真实 stdout/stderr 反思、容器 API 证据、源码保留式 guard 和统一 UNKNOWN/成本口径。运行期间不修改核心实现。


## 两批次 suite 执行入口

`scripts/cleanroom_suite.py` 将独立重放、晋升、残余修复和报告串联起来。第一批只使用未参与 GEPA train/validation 的 audit 任务：

```bash
PYTHONPATH="$PWD" /home/hewj13/wm/ext/py312/bin/python scripts/cleanroom_suite.py \
  --gepa-run work/<completed_gepa_run> \
  --dev-tasks configs/cleanroom_formal_dev_v0.6.json \
  --audit-tasks configs/cleanroom_independent_audit_v0.6.json \
  --witness-source work/cleanroom_dag_repair_smoke_v0.3/witness \
  --out work/cleanroom_audit_suite_v0.6 \
  --workers 1 --max-attempts 3 --llm-timeout 600
```

该批次依次执行 B0、B1、独立 memory 审查和 B2；只有真实晋升时才执行同批 B3，且不得把同批结果称为后续迁移。随后在未参与晋升的 transfer 批次上只读使用 memory：

```bash
PYTHONPATH="$PWD" /home/hewj13/wm/ext/py312/bin/python scripts/cleanroom_suite.py \
  --gepa-run work/<completed_gepa_run> \
  --dev-tasks configs/cleanroom_formal_dev_v0.6.json \
  --audit-tasks configs/cleanroom_transfer_v0.6.json \
  --memory-source work/cleanroom_audit_suite_v0.6/memory_review/memory_promoted.json \
  --witness-source work/cleanroom_dag_repair_smoke_v0.3/witness \
  --out work/cleanroom_transfer_suite_v0.6 \
  --workers 1 --max-attempts 3 --llm-timeout 600
```

第二批重新测量 B0/B1/B2，再与 B3 对照，不重新执行晋升。`verified_promotion` 要求独立重放、出处审计和实际 promoted 资产同时存在。`--resume` 只复用已完成且输入哈希一致的阶段；部分修复不会自动重试。`test_cleanroom_suite.py` 覆盖规范传递、registry 冻结、外部 memory 校验和 B2/B3 编排，真实执行结果仍以最终官方评价为准。


## v0.6 GEPA 最终结果

`work/cleanroom_gepa_guarded_assist_v0.6/analysis.json` 已完成：50 次 metric calls，wall time 4354.188 秒，2 个接受候选（含 seed），7 个被拒绝提议。选择候选 `61c8e9c32aa28d042547f571f6c0b8e771c8bec7c4f071da02e5a9cbdb636d45`，平局规则为 transfer 代理优先、dev 代理次之、候选序号稳定排序。

| 候选 | Dev proxy | Dev 真正确 | Transfer proxy | Transfer 真正确 | Transfer 幻影 | 两选择集 tokens |
|---|---:|---:|---:|---:|---:|---:|
| seed | 0/3 | 0/3 | 0/1 | 0/1 | 0/1 | 122,981 |
| C1（接受） | 1/3 | 1/3 | 0/1 | 0/1 | 0/1 | 146,383 |

- C1 在增材 dev 题达到 `proxy=true、true=true、quality=1.9919`，相比 seed 的 0/3 是实际 dev 增益；工业供应和电池装配仍失败，碳调度 transfer 也未通过。
- 这一结果支持“共享规范可在部分 dev 任务上产生可归因增益”，但不支持“GEPA 已迁移”或“memory 已晋升”。独立审计和后续迁移由两批次 suite 决定。
- 图件：`work/cleanroom_gepa_guarded_assist_v0.6_report/gepa_candidates.png`；逐提议历史与失败类型：同目录 `candidate_analysis.json` 和 `report.md`。
- 独立 suite 的 `candidate_selection.json` 已确认选择 C1，dev 代理均值为 0.3333333333333333。B0/B1、memory 审查、B2/B3 结果在运行完成后另报，不以设计或中间状态代替结果。


## 独立审计 B0/B1 与 memory 审查结果

独立批次为 `industrial_water_reuse_blending` 和 `mass_timber_panel_cutting_plan`，未参与 GEPA train/validation。B0/B1 使用与 GEPA 相同的生成、执行与 guard 实现，`implementation_matches=true`。

| 任务 | B0 直接结果 | B1 直接结果 | 归因 |
|---|---|---|---|
| 水回用 | 执行错误：`gaprel` 参数不存在 | `proxy=true、true=false`，12 个需求平衡错误，objective=1203.866818796961 | 执行失败变为新的代理幻影 |
| 木板材切割 | `proxy=true、true=false`，48 个构件需求未满足，total_cost=0 | `proxy=true、true=true、quality=2.0`，objective=343541.32913979195 | 幻影变为真实正确解 |

汇总：B0 `proxy=1/2、true=0/2、phantom=1/2、UNKNOWN=0/2`；B1 `proxy=2/2、true=1/2、phantom=1/2、UNKNOWN=0/2`。配对结果为新增真实正确 1、丢失真实正确 0、新增幻影 1、移除幻影 1，`win_safe=true`。

memory 审查没有只看汇总增益：因为水回用出现**新增幻影**，独立晋升条件失败，`specification_status=rejected`。这证明实现和任务覆盖一致，但不满足“不得新增幻影”的授权门槛；B3 在该批次不运行。证据为：

- `work/cleanroom_audit_suite_v0.6/B0/replay_result.json`
- `work/cleanroom_audit_suite_v0.6/B1/replay_result.json`
- `work/cleanroom_audit_suite_v0.6/memory_review/independent_replay_evidence.json`
- `work/cleanroom_audit_suite_v0.6/memory_review/promotion_summary.json`

B2 随后只针对失败/幻影任务进行有界修复，原本正确的木板材解必须保留。其增量与 GEPA 直接生成收益分开报告。


## 独立审计 B2 最终结果

| Arm | 覆盖 | 直接真正确 | 直接幻影 | 修复后真正确 | 修复后幻影 | UNKNOWN | 新增/丢失真实 win | Tokens |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| B0 空规范 | 2/2 | 0 | 1 | 0 | 1 | 0 | +0/−0 | 177,378 |
| B1 GEPA | 2/2 | 1 | 1 | 1 | 1 | 0 | +0/−0 | 186,191 |
| B2 GEPA+残余 DAG | 2/2 | 1 | 1 | 2 | 0 | 0 | +1/−0 | 213,885 |
| B3 验证 memory | not_run | — | — | — | — | — | — | — |

- 水回用第一次修复被接受：`feasible=true、quality=2.0、true=true、objective=6011.5448483809205`，幻影消失；木板材 `preserved_win`，没有额外 LLM 修复调用。
- B2 总计 6 次 LLM 调用、213,885 tokens、204.996 秒 LLM 延迟；求解与官方评价 wall time 分别为 62.662 和 63.706 秒。增量修复只新增水回用的 2 次生成调用和 27,694 tokens，其他是 B1 直接生成成本。
- memory 拒绝发生在 B2 之前，原因是 B1 新增水回用幻影。B2 消除该幻影不 retroactively 改写这次拒绝，也不自动构成 memory 晋升或跨任务记忆收益。
- 报告：`work/cleanroom_audit_suite_v0.6/report/report.md` 和 `batch_summary.json`。报告 CLI 参数名与 Witness 重复初始化问题已修复，恢复过程没有重复 LLM 生成或求解。
- 后续 transfer 使用 `--skip-memory-review` 保留该拒绝决定，不在另一批任务上反复尝试直到晋升。此选项仅记录 `review_skipped_by_protocol`，B3 仍为 not_run；B0/B1/B2 的真实结果另行报告。


## 后续 transfer 最终结果与失败归因

后续批次只有 `ev_battery_recycling_network` 一题，未参与 GEPA train/validation，也未参与前一批 memory 晋升审查。该批次是机制检查 pilot，不支持泛化准确率声明。

| Arm | 覆盖 | 直接真正确 | 修复后真正确 | 修复后幻影 | UNKNOWN | 修复尝试 | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0 空规范 | 1/1 | 0 | 0 | 0 | 0 | 0 | 39,107 |
| B1 GEPA | 1/1 | 0 | 0 | 0 | 0 | 0 | 32,127 |
| B2 GEPA+残余 DAG | 1/1 | 0 | 0 | 0 | 0 | 3 | 204,644 |
| B3 验证 memory | not_run | — | — | — | — | — | — |

- B0：`solver finish_reason=length`，达到 16,384 completion tokens，制品不完整，未进入 SCIP。当前协议没有中途扩大 token 预算。
- B1：可执行但业务不可行，包含 `M10/nmc/C01` hub 流量不平衡，以及 NMC hydromet share 低于公开下限。
- 第一次修复：引入 `KeyError('M01', 'M01')`，执行 `pass→fail`，业务仍为 fail，拒绝该边。
- 第二次修复：执行恢复为 pass，但业务仍 fail，仅为 `partial_progress`，不能作为最终输出。
- 第三次修复：仍有 `M07/nmc/C01`、`M10/nmc/C01` hub 流量不平衡和 NMC hydromet share 错误。最终为 `bounded_failure`，回退到 B1 直接结果，没有将部分进展计入真正确率。
- B2 共 8 次 LLM 调用、204,644 tokens、505.375 秒 LLM 延迟；求解和评价 wall time 分别为 112.025 和 55.108 秒。相对 B1 直接生成增加 172,517 tokens，但没有真实正确率增益。
- B3 仍因前一批 B1 新增幻影而未获授权，`--skip-memory-review` 保留拒绝决定，没有重复晋升。没有现有真实 win 被修坏，最终回退满足 win-safe。

汇总报告：`work/cleanroom_transfer_suite_v0.6/report/report.md` 和 `batch_summary.json`。审计与 transfer 的统一结果图为 `work/cleanroom_b0_b3_results.png`，区分直接真正确、修复后真正确、幻影和 UNKNOWN。


## v0.7 扩展与窄 API guard 复验

继续以成功率和泛化为目标，而不是把小样本负结果当作终点。新增任务只按公开场景、输入大小、历史排除和 oracle/官方健康筛选，不按 Qwen 成绩挑题。

新增的窄 guard 规则均有真实执行依据：`setRealParam("gaprel")` 参数别名、`setMinimize(False)` 的方向修正，以及将实际求解状态 `gaplimit` 加入允许导出的状态列表。转换保持原始源码，不整体重写 AST。

无 LLM 的旧制品复验 `work/cleanroom_guard_v0.7_replay`：

| 任务 | 原失败 | 复验结果 | 归因 |
|---|---|---|---|
| 增材 | `model.quicksum` 错误，修复后又因 `gaplimit` 被排除而写出空解 | `feasible=true、quality=1.991923112086961、profit=11688.043683670841` | 接受有效 gap-limit 解 |
| 水回用 | `gaprel` 参数不存在 | `feasible=true、quality=2.0、objective=6011.5448483809205` | 正确参数名 |
| 电池装配 | `setMinimize(False)` 参数错误 | 仍为执行失败：`KeyError('O01', ('O01', 'A01'))` | 方向错误后还有数据键映射问题 |

复验为 2/3 真正确、0 幻影、0 UNKNOWN，所有 LLM 调用为 0。它证明的是确定性 guard 的局部工程收益，不是 GEPA 或 memory 的增益，也不说明所有数据/业务错误已经解决。

后续扩展配置为 `configs/cleanroom_expand_energy_v0.7.json`、`cleanroom_expand_logistics_v0.7.json`、`cleanroom_expand_services_v0.7.json`。正式 dev/audit/transfer 划分将在健康检查完成后冻结。


## v0.7 扩展冻结配置与 B0 实测

冻结角色配置为 `configs/cleanroom_frozen_roles_v0.7.json`，包含 12 个唯一健康任务。任务角色如下；后续 transfer 不参与 GEPA train/validation，也不参与 memory 晋升审查。

| 角色 | 任务 |
|---|---|
| GEPA dev | additive_microfactory_order_planning、industrial_supply_planning、second_life_battery_pack_assembly |
| 独立审计 | smart_building_demand_response_dispatch、robust_microgrid_islanding_dispatch、fuel_tanker_compartment_routing、hybrid_telehealth_appointment_scheduling |
| 后续 transfer | industrial_water_reuse_blending、mass_timber_panel_cutting_plan、ev_battery_recycling_network、real_world_3d_bin_packing |
| GEPA validation | carbon_aware_compute_scheduling |

另外四个通过健康检查的任务为 cold_chain_locker_capacity_planning、cycling_network_design、green_hydrogen_hub_resilience_planning 和 nurse_rostering，可用于同域 Witness 校准；健康池合计 16 题。electric_bus_depot_charging、bike_share_rebalancing、green_port_berth_planning、german_or_scheduling 和 sterile_processing_robust_schedule 因参考求解没有可行解或没有 incumbent 而排除。医疗域目前只有两个健康任务，未满足三题初始化要求，不得伪造授权。

统一生成预算为 24,576 max tokens，关闭 thinking，模型阶段 4,096 tokens；B0 与后续 B1 使用相同 guard 和实现。空规范 B0 的真实结果如下。

| 批次 | 任务 | 真正确 | 幻影 | UNKNOWN | 失败族 | LLM tokens |
|---|---|---|---|---|---|---:|
| 独立审计 | smart_building_demand_response_dispatch | 是 | 否 | 否 | true_correct | 18,727 |
| 独立审计 | robust_microgrid_islanding_dispatch | 否 | 否 | 否 | incomplete_artifact | 42,162 |
| 独立审计 | fuel_tanker_compartment_routing | 否 | 否 | 否 | execution_error: unhashable dict | 31,031 |
| 独立审计 | hybrid_telehealth_appointment_scheduling | 是 | 否 | 否 | true_correct | 22,262 |
| 后续 transfer | industrial_water_reuse_blending | 否 | 是 | 否 | phantom_proxy | 13,436 |
| 后续 transfer | mass_timber_panel_cutting_plan | 否 | 否 | 否 | execution_error: 不存在的 Scip 导入 | 165,694 |
| 后续 transfer | ev_battery_recycling_network | 否 | 否 | 否 | execution_error: 不存在的 SCIP 导入 | 29,519 |
| 后续 transfer | real_world_3d_bin_packing | 否 | 否 | 否 | incomplete_artifact | 21,727 |

审计批汇总为 2/4 真正确、0 幻影、0 UNKNOWN、114,182 tokens；后续 transfer 为 0/4 真正确、1/4 幻影、0 UNKNOWN、230,376 tokens。证据分别为 `work/cleanroom_expanded_audit_suite_v0.7/B0/replay_result.json` 和 `work/cleanroom_expanded_transfer_suite_v0.7/B0/replay_result.json`。这些结果只作为同实现基线，不能用来筛选 GEPA 候选。

Witness 按域初始化，不能跨域继承否决权。能源域使用 smart building、robust microgrid 和 green hydrogen；物流域使用 cold chain、fuel tanker 和 cycling network。两域各自完成 3 个 clean、9 个 wrong 的真实审计，precision=1.0、detection=1.0、UNKNOWN=0。`scripts/cleanroom_witness_cache.py` 只适配批量 oracle 的只读缓存布局，不改写原工作区。官方 Witness 与官方评价器同源，仍不是完全独立的业务真值。

B3 新增作用域裁剪：即使制造域 memory 晋升，packing_logistics 的 real_world_3d_bin_packing 也保持 not_run，不能套用制造域生成规范。医疗校准失败同样保持未授权。木板材和 EV 的 `Scip/SCIP` 导入暴露出现行 guard 的覆盖缺口；本轮保持实现不变，后续窄 guard 修复必须另起实现版本和同口径对照，不能回溯归因给本轮 GEPA。


### v0.7.1 dev 反馈信号修订

盲反馈运行 `work/cleanroom_gepa_expanded_v0.7` 保留为诊断对照，不补写为完整实验。两个提议的 dev 代理都只有增材一题通过，未超过 seed。第二个提议已将工业供应从 tuple 解包崩溃恢复为可执行，但仍有 `material_purchase` 输出字段违规；此时反馈只有 `return_code=0、proxy=false`，没有向反思器提供任何业务坐标。因此停止该盲搜索，目录与 `run_cancelled.json` 均保留，不将其包装为充分负结果。

新增显式 `--dev-official-feedback`：只对 `split=dev` 的训练任务返回至多 20 条官方违规坐标，不包含官方评价器实现、参考解或参考目标值。validation、audit 和后续 transfer 即使也开启同一适配器，仍不得返回这些坐标。默认关闭以保持旧行为，测试同时覆盖 dev 可用和 transfer 不泄漏。

新运行 `work/cleanroom_gepa_dev_feedback_v0.7.1` 必须绑定新的实现哈希。前一轮 B0 数字保留为工程观察，但不能与不同实现哈希的 GEPA 结果组合用于 memory 晋升；正式对照需要重新执行同口径 B0/B1。

v0.7.1 的两组 B0 已真实完成，源代码版本为 `576f6b7`，生成与评价文件哈希见各自 `implementation.json`。审计批为 2/4 真正确、0 幻影、0 UNKNOWN、106,398 tokens：smart building 和 hybrid telehealth 保持真实 win，robust microgrid 为 incomplete artifact，fuel tanker 为 `addCons()` 重复 `name` 参数。后续 transfer 为 1/4 真正确、0 幻影、0 UNKNOWN、232,124 tokens：水回用直接达到 `quality=2.0、objective=6011.5448483809205`，木板材、EV 和 real-world 3D packing 均为执行错误。

本轮证据为 `work/cleanroom_expanded_audit_suite_v0.7.1/B0/` 与 `work/cleanroom_expanded_transfer_suite_v0.7.1/B0/` 下的 `run.json`、`replay_result.json`、`driver.log` 和逐题 `record.json`，提交为 `085c96f`。水回用从前一轮的幻影变为本轮真实 win，而实现中的直接生成逻辑没有变化，说明单次 LLM 采样有波动；不得把跨轮差异计作 GEPA 增益。后续 B1/B2 只与本轮 B0 配对，水回用及其他已有 win 必须保持 win-safe。


## v0.7.1 最终实验结果

### GEPA 候选与 dev 语义增益

`work/cleanroom_gepa_dev_feedback_v0.7.1` 已完成，实际为 51 次 metric calls（最后一批越过预设的 48，按真实计数报告）、5,825.857 秒、3 个接受候选和 6 个拒绝提议。候选均从空规范进化，dev-only 官方违规坐标可进入训练反思，validation 和后续 transfer 不接收这些坐标。

| 候选 | Dev 真正确 | Dev 幻影 | Validation 真正确 | Dev+validation tokens |
|---|---:|---:|---:|---:|
| seed | 0/3 | 0/3 | 0/1 | 121,852 |
| C1 | 1/3 | 0/3 | 0/1 | 135,442 |
| C2 | 2/3 | 0/3 | 0/1 | 144,033 |

C1 首先恢复增材真正确；C2 同时实现增材 `quality=1.7319` 和电池装配 `quality=1.6699` 的真正确，没有新增幻影。C2 哈希为 `08f95083f60719b0681fcca6cfad453b3faf28577335b466265903e2a11fe190`，按 transfer 代理优先、dev 代理次之、候选序号稳定排序的规则被选择。第八轮也有增材和电池两项真实 win，但 dev 总分只是持平，因此没有替代 C2。结果支持共享规范在 dev 上产生真实语义增益，不支持 validation 迁移结论。

候选报告为 `work/cleanroom_gepa_dev_feedback_v0.7.1_report_v1/report.md`，图件为同目录 `gepa_candidates.png`，逐提议接受和拒绝历史、成本及实现哈希均已保存。

### 独立审计与 memory 拒绝

B0/B1 在同一四题独立审计批上的真正确均为 2/4，UNKNOWN 均为 0；B1 没有新增或丢失真实 win，但新增 robust microgrid 幻影。由于独立重放没有真正确增益且新增幻影，`memory_review/specification_status=rejected`，没有执行出处审计 LLM 调用，也没有晋升 memory。

| Arm | 覆盖 | 直接真正确 | 修复后真正确 | 幻影 | UNKNOWN | 修复尝试 | Tokens |
|---|---|---:|---:|---:|---:|---:|---:|
| B0 | 4/4 | 2 | 2 | 0 | 0 | 0 | 106,398 |
| B1 | 4/4 | 2 | 2 | 1 | 0 | 0 | 127,706 |
| B2（分域 Witness） | 3/4 | 2 | 1 | 1 | 0 | 3 | 317,446 |
| B3 | not_run | — | — | — | — | — | — |

smart building 为 `preserved_win`；robust microgrid 第二次生成重复代码，以 `duplicate_repair` 停止，幻影未消除；fuel tanker 第一次仍为同一执行错误，以 `no_verified_progress` 停止。医疗域没有三个健康同域任务，hybrid telehealth 的 B2 明确 not_run。B2 的 3/4 覆盖不能写成全覆盖，也不能把缺少 hybrid 解释为修坏；B0→B2 的完整 win-safe 因覆盖缺口和新增幻影为 false。报告为 `work/cleanroom_expanded_audit_suite_v0.7.1/report/report.md` 和 `batch_summary.json`。

### 四题后续 transfer 的 B0/B1/B2

| Arm | 覆盖 | 直接真正确 | 修复后真正确 | 修复后幻影 | UNKNOWN | 修复尝试 | Tokens |
|---|---|---:|---:|---:|---:|---:|---:|
| B0 | 4/4 | 1 | 1 | 0 | 0 | 0 | 232,124 |
| B1 | 4/4 | 1 | 1 | 1 | 0 | 0 | 249,413 |
| B2 | 4/4 | 1 | 1 | 1 | 0 | 6 | 562,189 |
| B3 | not_run | — | — | — | — | — | — |

| 任务 | B0 | B1 | B2 最终与停止原因 | B2 tokens |
|---|---|---|---|---:|
| 水回用 | 真正确，quality=2.0 | 幻影 | 幻影；第一次需求平衡错误不变，`no_verified_progress` | 42,158 |
| 木板材 | 执行错误 | 真正确，quality=2.0 | 真正确；`preserved_win`，0 次修复 | 170,344 |
| EV 回收网络 | 执行错误 | 业务不可行 | 业务不可行；第三次重复，`duplicate_repair` | 223,208 |
| real-world 3D packing | 执行错误 | 制品不完整 | 制品不完整；第二次重复，`duplicate_repair` | 126,479 |

B0→B1 和 B0→B2 都是新增木板材真实 win、丢失水回用真实 win、增加水回用幻影，端到端 `win_safe=false`。B1→B2 局部比较没有新增或丢失真实 win、没有新增幻影，`win_safe=true`。两种口径都保留，不能用局部回退保护掩盖相对 B0 的水回用损失。

EV 第一次修复消除了三个 outlet 容量错误，只剩 hydromet share 下限；第二次引入市场供需和测试比例错误并被拒绝；第三次重复第二次代码后停止。real-world 只有通用执行检查，没有本域业务 Witness，其执行层修复同样未形成真正确。详细逐题记录、成本和失败坐标见 `work/cleanroom_expanded_transfer_suite_v0.7.1/report/`。

### 结论、边界与图件

本轮至少获得一个可复核的 dev 语义增益，但 B2 后续 transfer 的真正确率没有超过 B0 或 B1，故这是**完整负迁移结果**，不是 SOTA 或 memory 泛化成功。停止规则能够防止重复代码、部分进展和幻影被接受，却仍不能可靠生成不同且语义正确的修复。memory 的拒绝发生在 B2 之前，后续修复没有 retroactively 改写拒绝决定。

统一结果图为 `work/cleanroom_expanded_b0_b3_results_v0.7.1.png`，显示直接/修复后真正确、幻影、UNKNOWN、最终覆盖和端到端 win-safe。官方 Witness 与官方评价器同源的限制仍然存在；它提供任务内一致性检查，不等同于完全独立的业务真值。12 个冻结角色的健康证据见 `work/cleanroom_frozen_health_v0.7/health_summary.json`。

### 最终验证

最终交付版本执行 `PYTHONPATH="$PWD" /home/hewj13/planbb/miniforge3/envs/rl/bin/python -m pytest -q tests --ignore=tests/test_m2gen.py`，结果为 **558 passed、3 skipped**；`python3 m2gen/run_regression.py` 返回 `REGRESSION OK`。日志为 `work/cleanroom_final_validation_v0.7.1/pytest.log` 和 `m2gen.log`，SHA-256 及关键结果哈希见同目录 `summary.json`。


## v0.8 性能优先迭代：best-parent 首轮证据

`6b9d433` 将中间修复搜索改为证据驱动的 best-parent 策略：执行恢复、业务可行、幻影/UNKNOWN减少、错误数减少或质量提升才算进展；任何对应退化都不再沿该子节点继续，而是保留最佳父节点并尝试后续种子。接受分支也记录 `evidence_transition`。最终仍只接受通过门禁的解，未通过时回退到直接基线。

真实 EV 工程 replay `work/swarm_repair_ev_best_parent_v0.8` 重现第一次仅剩 hydromet 错误、第二次重新出现市场供需错误的序列。第三次的 `parent_id` 为 `root/repair:1`，而非第二次的 `root/repair:1/repair:2`，证明退化后确实回到最佳父节点。三次转换为 `progress → regression → regression`，最终 `true_correct=false、win_safe=true、attempts=3`，成本为 8 次 LLM 调用、227,071 tokens。全量回归为 **560 passed、3 skipped**。

这次 replay 是旧 transfer 上的工程验证，不是独立性能证据。它证明控制器结构修复有效，但没有解决语义生成错误；最终性能仍须在全新 transfer 上评价。


## v0.8.2 第二组独立 transfer 负结果与局部补丁工作版

第二组四题为 evtol、robotic fulfillment、wastewater sentinel 和 naloxone drone，开始实验前均未参与规范学习、工程调参或 memory 晋升。固定 C2 规范哈希为 `08f95083f60719b0681fcca6cfad453b3faf28577335b466265903e2a11fe190`，B0/B1/B2 使用相同直接生成预算与最多三次修复。

| Arm | 覆盖 | 真正确 | 幻影 | UNKNOWN | 修复尝试 | Tokens |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 4/4 | 0 | 0 | 0 | 0 | 312,061 |
| B1 | 4/4 | 0 | 0 | 0 | 0 | 333,372 |
| B2 | 4/4 | 0 | 0 | 0 | 11 | 1,402,251 |
| B3 | not_run | — | — | — | — | — |

B0→B2 没有 missing、lost true 或新增幻影，但也没有 gained true，严格性能验收**未通过**。失败包括制品不完整、运行/API 错误、过大模型或不可行模型和业务语义错误。中间出现的可执行或错误减少节点均未被当作真正确。逐题报告、尝试记录、成本和日志见 `work/swarm_transfer_logistics_v0.8.2/`，未达标判定为 `evaluation_outcome.json`。这些题随后只能作为工程数据。

并行物流 GEPA `work/swarm_gepa_logistics_v0.8` 共记录 37 次 metric calls（含 seed 重评），6 个提议全部拒绝，没有非 seed 接受候选。一个拒绝提议让 autonomous-lab 真正确，却同时保留 shared-drone 幻影，不能据此晋升。候选曲线和提议历史见 `work/swarm_gepa_logistics_v0.8_report/`。因此 memory 没有独立晋升，B3 仍为 `not_run`，不反复重试直到获得晋升。

### 分类型修复与精确局部补丁

`a02f25f` 区分运行失败和语义失败：运行失败保留当前求解器做增量修复，语义失败才在无进展时换分支重建。可信最终节点与工作分支分离；新的运行诊断可以沿未通过最终门禁的工作分支继续，但最终结果始终回退到通过门禁的解或原基线。该机制的相关测试通过，但旧题真实复验因外层运行时限只保存了部分尝试，不能据此声称有效。

`3ceb9fd` 进一步将具有真实 stderr 的运行错误路由到 `submit_runtime_patch`。模型仅返回 1–16 个精确代码替换；每个 `old_string` 必须唯一匹配，其他源码保持不变，截断、歧义或不完整补丁拒绝。补丁之后仍执行 API guard、语法/完整性、沙箱执行和官方检查。直接生成协议不变，每题仍最多三次修复提议；成本统计新增 `runtime_patch_generation.json`。没有真实 stderr 的不完整制品及超时仍走完整制品生成，不冒充运行补丁。

工程题 naloxone 的局部补丁复验 `work/engineering_runtime_patch_naloxone_v0.8.4` 已完成三次尝试，没有真正确，最终回退且 win-safe=true；含直接生成共 5 次 LLM 调用、98,747 tokens。三次运行错误依次为 `NameError: fixed_cost`、键缺失、`getNCons` API 错误。第二个补丁试图删除一个实际上不再被引用的 `cost_obj` 赋值来绕过 `NameError`，因此后续版本增加绑定保留检查，禁止删除仍被引用的绑定或目标/成本绑定。

`529ef64` 的通用 guard 加入经容器签名核对的 `getNCons()→getNConss()`。对同一已保存第三次补丁做零 LLM 复验 `work/engineering_runtime_patch_naloxone_v0.8.5_guard_replay`，代码已能执行，得到 objective=29,703,555.805052724，但官方仍为业务不可行：开放基地数越界、优先级覆盖不足和地面兜底容量/比例违反等。这是**执行恢复而非真正确**，也不能声称带新绑定门禁的完整控制器必然生成同一候选。新控制器还会把上一次生成拒绝原因传入下一次尝试。

该工作版全量 pytest 为 **567 passed、3 skipped**，m2gen 为 `REGRESSION OK`，日志为 `work/verification_runtime_patch_v0.8.4/`；后续小改仍需最终重跑。第三组独立任务健康检查随后完成，正式结果如下。

## v0.9 第三组全新 transfer：严格达标及其边界

第三组使用 electric medical waste、container gate、portable battery 和 offshore wind 四题。它们未参与规范学习、Qwen 工程调参或 memory 晋升；角色和参考健康在运行前冻结于 `configs/cleanroom_swarm_frozen_logistics_v0.9.json` 与 `work/swarm_transfer_pool/health_summary_v0.9.json`。核心实现提交为 `94005e63040142a04703479e3d6cc294b696f35e`，B0/B1/B2 共用 24,576 solver tokens、4,096 model tokens、关闭 thinking、API guard 与每题最多三次修复。C2 规范哈希与上一批相同。

| Arm | 覆盖 | 最终真正确 | 幻影 | UNKNOWN | 修复尝试 | Tokens |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 4/4 | 0 | 1 | 0 | 0 | 344,756 |
| B1 | 4/4 | 1 | 0 | 0 | 0 | 367,228 |
| B2 | 4/4 | 1 | 0 | 0 | 9 | 1,393,162 |
| B3 | not_run | — | — | — | — | — |

| 任务 | B0 | B1 | B2 最终 | 尝试 | B2 tokens |
|---|---|---|---|---:|---:|
| electric_medical_waste_lrp | 幻影 | 制品不完整 | 制品不完整；三次均缺少 `optimize()` | 3 | 990,252 |
| container_gate_dro_appointment_planning | 执行错误 | 执行错误 | 三个局部补丁后仍执行错误 | 3 | 218,938 |
| portable_battery_swap_rebalancing | 质量不足 | 真正确，quality=2.0 | `preserved_win`，真正确，quality=2.0 | 0 | 29,085 |
| offshore_wind_maintenance | 制品不完整 | 业务不可行 | 业务不可行；回归后回退 | 3 | 154,887 |

B0→B2 为新增 portable 一个真正确、移除 electric 一个幻影，没有 lost true、missing task、新增幻影或 UNKNOWN，满足本轮严格性能条件。可是 B1→B2 没有新增或丢失真正确，也没有新增幻影：**净语义增益来自共享规范，不是 DAG 多修出了一题**。B2 相比 B1 多花 1,025,934 tokens，九次修复没有增加真正确，不能写成高效修复或 SOTA。

container 的补丁依次暴露字符串与整数比较、元组解包和 `KeyError: 8`，最终都未通过业务门禁。offshore 第一次遗漏 mandatory tasks；第二次减少为工作时长容量错误，记为 `progress` 但仍非真正确；第三次再次遗漏 mandatory tasks，记为 `regression` 并回退。这证明证据转换和回退在工作，不证明语义生成问题已解决。electric 连续三次同类制品失败则说明仅反馈拒绝原因仍不足以防止重复生成。

Witness 校准为 3 clean、9 wrong，precision=1.0、detection=1.0、UNKNOWN=0；但它和最终评价器同源，只提供任务内一致性检查，不是完全独立业务真值。没有真实独立 memory 晋升，B3 没有运行，不能声称 memory 在线写入、进化或增量收益。四题一题净增益也不足以宣称跨域泛化。

证据入口：`work/swarm_transfer_logistics_v0.9/report/report.md`、`batch_summary.json`、`b0_b2_comparison.png`、`evaluation_outcome.json`、`implementation_snapshot.json` 和 `driver.log`。B1→B2 的独立配对检查保存在 `evaluation_outcome.json`，不与 B0→B2 的总增益混用。官方 Witness 与最终评价器同源，仍只支持任务内一致性检查，不等同于完全独立业务真值。

最终交付版本执行 `PYTHONPATH="$PWD" /home/hewj13/planbb/miniforge3/envs/rl/bin/python -m pytest -q tests --ignore=tests/test_m2gen.py`，结果为 **571 passed、3 skipped**；`python3 m2gen/run_regression.py` 返回 `REGRESSION OK`。绘图函数修正了零值轴裁剪和标签遮挡，并有回归测试覆盖。最终日志与哈希见 `work/verification_v0.9_final/`。


## v0.10 修复增量协议（结果产生前冻结）

v0.9 达到 B2 相对 B0 的净增益，但 B1→B2 没有新增真正确，且九次修复成本过高。下一阶段不再使用 v0.9 题目调参，而使用此前已冻结的 v0.10 四题：home healthcare、airport gate、circular packaging 和 coastal aquaculture。它们的角色、公开单步契约和参考健康证据见 `configs/cleanroom_swarm_frozen_logistics_v0.10.json` 与 `work/swarm_transfer_pool/health_summary_v0.10.json`，均在 v0.9 结果揭晓前确定。

核心实现提交为 `8aeea8619007476ebd75470c39330b3b207104ef`。相较 v0.9 的变化限于：

- 不完整制品的首次修复仍失败时，后续尝试从公开题面和失败证据重建，不再携带旧坏代码。
- 用 Python 标准库 `symtable` 检查未定义全局变量；星号导入和动态名字环境保守跳过，避免把静态不可判定当成正确。
- 对实际出现的 `pyscipopt.SCIP` 无效导入做 AST 窄修复，只移除该导入并替换对应构造调用，不修改其他合法 API 或同名用户类。

B0/B1/B2 使用相同的直接生成预算、API guard 和最多三次修复；B3 仍因无真实独立 memory 晋升而 `not_run`。主要性能问题改为 **B2 是否严格超过 B1 的官方真正确任务数**。同时要求 B1→B2 无 lost true、无 missing、无新增幻影、UNKNOWN 不计安全；另报 B0→B2，防止相对 B0 已存在的净增益掩盖修复无效。

次要指标为每题修复 token、求解和评价 wall time、重复制品失败次数、预检拦截次数及工作分支回退次数。预检拦截只算工程可评估性，不算真正确；执行成功、局部错误减少、生成补丁或回退均不能替代官方真正确。v0.9 的旧制品仅用于工程复验，不并入 v0.10 的独立任务分母。

冻结实现的全量回归为 **576 passed、3 skipped**，m2gen 为 `REGRESSION OK`。换分支契约、API 探测和旧 container 的零 LLM guard 复验见 `work/verification_v0.10_final/` 与 `work/engineering_scip_guard_container_v0.10/`。container 复验在导入错误后仍暴露 `KeyError: '12'`，因此不预先声称本版能解决数据键或业务语义问题。


## v0.10 实际结果与下一轮归因

v0.10 未达到修复增量目标，完整结果已保存在 `work/swarm_transfer_logistics_v0.10/`。

| Arm | 覆盖 | 真正确 | 幻影 | UNKNOWN | 修复尝试 | Tokens |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 4/4 | 0 | 0 | 0 | 0 | 94,386 |
| B1 | 4/4 | 0 | 2 | 0 | 0 | 118,869 |
| B2 | 4/4 | 0 | 2 | 0 | 10 | 477,242 |
| B3 | not_run | — | — | — | — | — |

B0→B2 新增 circular packaging 和 coastal aquaculture 两个幻影，严格安全条件不成立；B1→B2 没有新增或丢失真正确、没有新增幻影，但原有幻影一个也没有消除。B2 的修复增量为 358,373 tokens，低于 v0.9 的 1,025,934，但任务规模和实现均不同，不能把差值解释为单独的机制降本效果。

主要失败归因如下：

- home 第一次从执行错误变成四个明确的未服务患者错误，旧控制器因错误数从 1 增加到 4 而误判为回归，随后沿旧代码产生 `duplicate_repair`。执行恢复和获得更具体业务证据不应被当成语义退化；真正确、可行性、幻影和 UNKNOWN 的安全门禁仍需单独保持。
- airport 已可行且没有业务错误，但目标值为 69,370，质量为 0。原证据只有空错误列表，没有明确要求在保留可行性的同时优化目标，因此模型缺少有效搜索方向。后续反馈只包含实际目标值和质量状态，不把参考目标或最优界泄露给修复模型。
- circular 的最后一次修复把 `(coefficient, variable)` 对直接传入 quicksum，产生确定的类型错误；home 的 `addCons(constraint if condition else 1)` 在条件为假时把整数 1 当作约束；另一个 home 输入使用了不存在的 `Scip` 导入。这些都适合窄 AST 转换，不需要让模型猜 API。
- coastal 两次均有 77 个相同业务错误，说明语义重建仍可能近乎重复。API 类型修复不等于业务正确，不能把有目标值或错误坐标减少直接写成真正确。

下一版相应加入执行恢复的证据转换、质量不足指导、quicksum 二元对乘法、`addCons` 条件约束转换以及 `SCIP/Scip` 窄导入修复。相关 580 项 pytest 和 m2gen 已通过。零 LLM 结构复验表明这些转换能消除对应 API 错误，但 circular 仍有库存语义错误，home 仍有未服务患者，故只能称为可评价性改善。

v0.11 新独立角色已在任何 Qwen 运行前冻结：cell tower、private 5G、edge cache 和 carbon removal，四题参考健康均为 `true_correct=true、quality=2.0`，见 `configs/cleanroom_swarm_frozen_logistics_v0.11.json` 和 `work/swarm_transfer_pool/health_summary_v0.11.json`。home/airport 的旧题只用于机制复验，不会进入新独立分母。


## v0.11 规范分支与质量一致性（独立运行前）

home 和 airport 的旧工程复验均未产生真正确，因此不把执行恢复和 API guard 的局部改善当作业务成功。v0.11 在相同三次修复预算内增加规范来源分支：第一次仍使用选定的 C2；第二次若需要从证据进行语义重建，则改用空共享规范；第三次回到原 C2。运行错误的精确局部补丁不切换规范。每次生成记录实际规范哈希，空规范结果不得归因给 C2，也不增加额外生成次数。

质量不足反馈增加 `objective_sense` 和 `quality_status` 元数据，并要求检查求解器内部目标与按输出决策重算目标是否一致。只提供当前解实际产生的目标值，不把参考目标、最优界或参考解内容提供给修复模型。即使得到更低目标值，也仍须通过官方可行性和质量门禁，不能以代理改善替代真正确。

主要验收仍为 B2 相对 B1 的真正确严格增加，同时无 lost true、missing、新增幻影或 UNKNOWN；B0→B2 的幻影变化另列。后续任何正结果都必须能追溯到具体分支和官方逐题记录，不能仅根据 prompt 设计推断机制有效。


## v0.11 实际结果与受限 best-effort 回退

v0.11 的完整独立结果如下，原始证据保存在 `work/swarm_transfer_logistics_v0.11/`。

| Arm | 覆盖 | 真正确 | 幻影 | UNKNOWN | 修复尝试 | Tokens |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 4/4 | 0 | 0 | 0 | 0 | 128,294 |
| B1 | 4/4 | 2 | 1 | 0 | 0 | 156,031 |
| B2 | 4/4 | 2 | 1 | 0 | 5 | 523,316 |
| B3 | not_run | — | — | — | — | — |

C2 相对 B0 新增 carbon removal 和 private 5G 两个真正确，同时新增 cell tower 幻影。B2 没超过 B1，也没消除该幻影；B0→B2 的严格无新增幻影条件因此不成立。空规范分支未产生真正确，edge cache 的两次结果都保持 quality=0。图件为 `report/b0_b2_comparison.png`，验收为 `evaluation_outcome.json`。

cell 的第一次 C2 修复其实已从原幻影变为 `feasible=true、phantom=false、quality=0、objective=197311.6018755999`，即得到官方可行解，但仍不满足质量门槛。旧控制器只接受真正确，因此最后回退到原始幻影，丢失了严格更好的非正确候选。

为此新增受限 best-effort 回退，只有同时满足以下条件才允许替换基线：

- 基线是幻影，候选和基线都不是真正确；
- 候选官方 `feasible=true`、`phantom=false`、执行返回码为 0；
- 没有 UNKNOWN，且 quality 不低于基线。

该状态记为 `best_effort_fallback`，`final_accept=false`，不能称为 accepted 或真正确。业务不可行候选、UNKNOWN、执行失败、质量退化和新幻影均不得进入此回退；真正确仍只能走原有全部门禁的 `accepted`。offline 检查 `work/engineering_best_effort_cell_v0.12.json` 证明旧 cell 第一次候选符合这些条件，但只用于工程验证，不回写 v0.11 的独立结果。

后续独立验收分别报告真正确变化和幻影消除，不能把 best-effort 当作 B2 相对 B1 的真正确增益。这一规则是对前述“仅最终门禁通过才替换基线”的受限补充：只有原幻影变成官方可行且非幻影时才保留较好的非正确候选，其余失败仍回退原基线。新候选池 `configs/cleanroom_oracle_logistics_v0.12.json` 在任何 Qwen 运行前准备，仍只按公开契约与 oracle/官方健康筛选。


## v0.12 首个独立 B2-over-B1 真实修复增益

v0.12 使用 surgery、platelet、retail media 和 vertical farm 四个未参与规范学习、工程调参或 memory 晋升的新任务。角色与健康证据在运行前冻结于 `configs/cleanroom_swarm_frozen_logistics_v0.12.json` 和 `work/swarm_transfer_pool/health_summary_v0.12.json`。实现为受限 best-effort 版本，B0/B1/B2 的直接生成预算和每题最多三次修复保持一致，B3 仍因无独立 memory 晋升而 `not_run`。

| Arm | 覆盖 | 真正确 | 幻影 | UNKNOWN | 修复尝试 | Tokens |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 4/4 | 2 | 0 | 0 | 0 | 102,766 |
| B1 | 4/4 | 1 | 0 | 0 | 0 | 125,938 |
| B2 | 4/4 | 2 | 0 | 0 | 8 | 324,772 |
| B3 | not_run | — | — | — | — | — |

B1→B2 新增 `retail_media_campaign_allocation` 一个真正确，没有 lost true、missing、新增幻影或 UNKNOWN，达到本阶段修复增量目标。retail 在第二次 **C2 targeted repair** 中被接受，`feasible=true、quality=1.9999999999997138、objective=12708.705645440003`，不是空规范分支的结果。vertical farm 为 `preserved_win`，已有正确解没有被修坏。

但 B0 和 B2 都是 2/4 真正确，且 retail 在 B0 本来就正确、B1 生成失败后被恢复。因此这是**修复恢复一个正确解**，不是 B2 超过 B0，也不是 SOTA 或泛化结论。`evaluation_outcome.json` 分别保存 `strict_goal_met=true`（B2>B1 的修复目标）和 `original_b0_strict_goal_met=false`（未超过 B0）。

其他失败不能被正结果掩盖：platelet 第三次产生幻影并被拒绝回退；surgery 第一次得到官方可行但 quality=0 的候选，第二次空规范产生被拒绝的占位制品，第三次又出现 `NameError: assign`，最终仍未通过。best-effort 回退本批没有触发，因此其独立效果尚未验证，不能把 retail 的 accepted 归因给 best-effort。

全部八次修复的增量为 198,834 tokens。retail 的两次成功路径增量为 31,735 tokens；platelet 三次失败为 35,649，surgery 三次失败为 131,450，vertical 不额外修复。成功一例不说明统一三轮预算已最优，也不说明所有失败族均已解决。

证据入口：`work/swarm_transfer_logistics_v0.12/report/report.md`、`batch_summary.json`、`b0_b2_comparison.png`、`repair_cost_analysis.json`、`evaluation_outcome.json`、`implementation_snapshot.json` 和 `driver.log`。全量回归为 **583 passed、3 skipped**，m2gen 为 `REGRESSION OK`，日志见 `work/verification_v0.12/`。Witness 与官方评价器同源，仍不是独立业务真值；memory 进化也没有得到证明。


## 决策空间修复协议（工程验证阶段）

此前的修复主要改写模型代码，容易在修一个 API 或约束时引入新的模型错误。为对齐“运行错误修代码、业务错误修决策、模型错误才重建”，新增 `ora_agent/decision_repair.py` 和 `submit_decision_repair` 工具协议。

### 触发与边界

仅当以下条件同时成立时，首次修复优先进入决策空间：

- 原求解器执行返回码为 0；
- 存在模型自己产生的 `solution.csv` 或 `solution.json`；
- 官方评价仍为非可行，并给出业务错误。

没有解文件的执行错误仍走代码修复；已可行但质量不足仍走目标与输出一致性修复。首次决策修复若取得可验证进展但未通过，第二次可依据官方业务错误同时修正决策与校验器，并提供上一版 `repair_solution.py`；若执行失败则走函数级局部补丁，错误增多或连续无进展则回到可信父节点和空规范/C2 的模型重建，不对同一旧解无限重复。

### 输入、输出与安全

- 原解决策只读保存为 `solution_original.csv/json`，同时记录原解哈希。
- 修复脚本只能读取公开数据和该旧解，不能读取参考解、隐藏评价器或外部文件。
- 只允许 Python 标准库，禁止动态执行、占位实现和未定义全局变量。
- 输出必须保持题面规定的 schema，并重新计算公开约束与目标，不能通过删除必需服务、改 ID 或伪造验证日志来隐藏错误。
- 求解器代码在该分支保持不变；DAG 另外记录 `repair_solution.py` 和新解哈希，因此不会把决策变化误判为重复修复。
- 最终仍由官方评价决定 `accepted`、受限 `best_effort_fallback` 或回退，不因生成了决策修复脚本就视为成功。

每次 `decision_repair_generation.json` 都记录 prompt、响应、协议和 token；`repair_solution.py`、旧解、新解、执行日志和官方结果共同组成证据链。当前先用已评估过的 coastal 幻影题做工程验证，不把该题结果重新计入独立成绩。只有真实安全性和增益得到验证后，才冻结新的独立 pipeline 对照。


### 决策脚本运行补丁

若 `repair_solution.py` 自身执行失败，后续路由为 `decision_runtime_patch`，而不是立即重写整个模型。它复用唯一匹配的局部替换和绑定保护，但以决策脚本的完整性检查代替 `optimize()` 检查，且不得改变原 `solve.py`。工作目录即使只保留了 `solution_original.csv/json`，也能继续修复。

标准库检查通过 `importlib.util.find_spec` 的来源判断，不依赖环境可能缺失的 `sys.stdlib_module_names`。求解器、网络、外部执行和动态代码模块仍被禁止；合法的 `fractions` 等标准库和沙箱根路径 `/app` 不得被误拒。补丁生成、执行和官方结果均落盘，脚本类型错误不能直接视为业务不可行。


### 工程复验结论：best-effort 生效，但直接业务修复仍未证明有效

coastal 的决策脚本在多次函数级补丁后修复了矩阵索引错误，却仍因氧气与鱼粉约束失败而没有有效解，不能称为成功。cell 的第一次决策修复也将服务从 45 行降至 12 行，产生 11 项人口、企业设备与关键区域覆盖错误，超过原来的 3 项容量错误，因此被回退。

后续空规范分支执行失败，第三次 C2 分支得到 `feasible=true、phantom=false、quality=0、objective=197311.6018755999`。最终状态为 `best_effort_fallback`、`final_accept=false`，`pair_win_safe.removed_phantom=["cell_tower_coverage_expansion"]`，没有 lost true 或新增幻影。它证明受限回退确实能保留“官方可行但非真正确”的更好候选，而不是把原始幻影带回来；**并不证明直接决策生成已经正确，也不构成独立泛化证据**。

cell 复验共三次修复、含直接生成共 7 次 LLM 调用、186,075 tokens。证据位于 `work/engineering_decision_repair_cell_v0.13.1/` 与 `work/engineering_decision_repair_outcome_v0.13.json`。全量回归为 **593 passed、3 skipped**，m2gen 为 `REGRESSION OK`。

下一阶段使用已冻结的 federated learning、cold-chain locker、cycling network 和 nurse rostering 四个新任务，评价完整 B0/B1/B2 的真实正确率、幻影变化、直接修复贡献与成本。没有接受此结果前，不把这些新任务称为已经验证的迁移成功。


## v0.13 对齐 pipeline 的独立验证

本批使用 federated learning、cold-chain locker、cycling network 和 nurse rostering 四个未参与规范学习、工程调参或 memory 晋升的新任务。角色与参考健康证据在运行前冻结于 `configs/cleanroom_swarm_frozen_logistics_v0.13.json` 和 `work/swarm_transfer_pool/health_summary_v0.13.json`。实现绑定为 `18fafa40c57fd7819db974eec3f944cb001841a8`，完整结果位于 `work/swarm_transfer_logistics_v0.13/`。

| Arm | 覆盖 | 真正确 | 幻影 | UNKNOWN | 修复尝试 | Tokens |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 4/4 | 0 | 0 | 0 | 0 | 382,999 |
| B1 | 4/4 | 1 | 0 | 0 | 0 | 411,209 |
| B2 | 4/4 | 2 | 0 | 0 | 7 | 755,497 |
| B3 | not_run | — | — | — | — | — |

本批同时满足两个严格条件：

- B0→B2 新增 cycling network 和 federated learning 两个真正确，没有 lost true、missing、新增幻影或 UNKNOWN；
- B1→B2 新增 cycling network 一个真正确，同样没有 lost true、missing、新增幻影或 UNKNOWN。

`cycling_network_design` 在第一次 **C2 两阶段模型/代码修复** 中被接受，`feasible=true、quality=2.0、objective=216495021.89352`，不是空规范、决策空间修复或 memory 的结果。`federated_learning_cohort_selection` 的已有正确解被 `preserved_win` 保留，没有额外修复调用。

失败路径不能省略：cold-chain 的决策空间修复产生 75 项业务错误，空规范分支执行失败，第三次 C2 又产生 staff-hours 幻影并回退；nurse 第二次局部补丁恢复到 `feasible=true、quality=0`，第三次又因 quicksum 接收 list 而回归。best-effort 本批未触发，memory 没有晋升，B3 没有运行。因而不能把全部增益归功于新决策层，也不能声称 memory 自进化、跨域泛化或 SOTA。

全部七次修复的增量为 344,288 tokens：cycling 82,344，cold-chain 111,348，nurse 150,596，federated 为 0。成本仍高，且不同错误所需预算明显不同，统一三轮仍只是上限而非最优策略。

证据入口：`report/report.md`、`batch_summary.json`、`b0_b2_comparison.png`、`repair_cost_analysis.json`、`evaluation_outcome.json`、`implementation_snapshot.json` 和 `driver.log`。全量回归为 **593 passed、3 skipped**，m2gen 为 `REGRESSION OK`，日志见 `work/verification_decision_repair_v0.13/`。Witness 与官方评价器同源，仍不是独立业务真值。

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

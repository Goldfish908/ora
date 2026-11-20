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

制品生成采用两段协议：先提交精炼 `model.md`，再提交完整 `solve.py` 与日志。`finish_reason=length/max_tokens` 明确记为生成截断失败，不得当作缺失代码、空输出或业务错误。单阶段与两阶段结果不得混入同一比较曲线。内网Qwen通过 `chat_template_kwargs.enable_thinking=false` 控制长生成时，须在所有比较臂一致记录和使用。

## 负结果

GEPA无提升、memory零晋升、DAG无增益、Witness覆盖不足或跨族失败均如实报告。不得为获得正结果而移动分母、降低授权门槛、改写UNKNOWN或根据最终测试调参。

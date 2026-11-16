# 可迁移语义绑定验证协议 v0.1

## 目标与边界

把“绑定如何提出”与“绑定是否可信”分离。人工、LLM 或冻结库都可提出机制与变量/数据绑定，但只有独立反例门和业务评分能决定是否激活。

本协议不声称自动跨族、自动自进化或 SOTA。迁移的是提议、验证、拒绝和回滚过程；具体变量含义与业务假设不能无条件跨域。

## 输入

每个 `BindingProposal` 包含：

- `mechanism_id`：现有 scoped 资产注册表中的机制；
- `origin`：`reference_assisted`、`cold_start_proposal` 或 `frozen_reuse`；
- `source_span`：必须是题面原文；
- `payload`：声明式变量、数据、系数和独立来源证据，不接受任意可执行代码。

每个验证 cell 必须显式提供 `label_source`，同时有 clean 和 wrong；缺少标签来源时不能通过。checker 产生的标签不能独自充当独立真值。可选业务 scorer 在 reference-clean 上再做独立评价，防止 checker 与生成器共享错误。

## 统一处理

`validate_proposal` 只负责：协议校验 → 现有资产编译 → scoped 反例门 → 可选独立业务评分。它不在内部生成新规则或修复代码，也不因 caller 声明 `independent_validation=True` 而绕过证据。

结果区分：

- `validated`：协议、反例门及已提供的独立业务评分均通过；只证明当前绑定在已验证作用域内可用，不证明模型等价或普遍正确；
- `rejected`：明确违反协议、反例或业务评分；
- `unknown`：缺来源、字段、证据或存在冲突，不能激活。

多个提议中只有一个是有效绑定时可以采用。多个都通过 gate 但结论冲突时必须返回 `unknown`，不得选择较有利答案。未通过者保留来源和拒绝原因，不自动晋升资产。

## 开发验证

同一代码至少处理两个问题族，覆盖：正确绑定、错误变量/索引绑定、缺证据、严格/非严格边界和冲突提议。比较相同协议下的接受、拒绝、UNKNOWN 和业务评分，不修改数据集专属分支来制造成功。

LLM 重新提议称为 cold-start binding，不能称为 frozen reuse；reference-assisted 要披露规格来源。保存所有输入、绑定、标签来源、结果、成本和回滚信息，最后执行完整 pytest 与 `m2gen` 回归。

# 内网 Qwen cold-start 绑定验证协议 v0.1

## 来源与冻结配置

使用内网 `Qwen3_8-27B`，endpoint 与 API key 仅从进程环境读取，不进入代码、prompt、原始响应制品或报告。`/v1/models` 已确认模型 ID。该内部证书链仅在本次调试连接中关闭校验，不修改全局 TLS。

- 每个机制一次生成，不重试、不改 prompt、不挑响应；
- `temperature=0`、`max_tokens=2048`、`reasoning_effort=low`；
- 模型只看题面、变量声明和允许的原文 span，不看独立参考约束、目标表达式、参考解或公开答案；
- 输出限定为声明式绑定 JSON，不生成求解代码或目标答案。

这是 schema/source-span assisted 的 cold-start 绑定验证，不是完全自主变量发现或 frozen 泛化。

## 两个任务

1. IndustryOR-20 `objective_recompute`：从四类玩具的单位利润绑定 x1..x4 的系数，业务最优解由独立评分确认。
2. BWOR-002 `resource_bound`：从食物蛋白含量与 700g 要求绑定资源下界，独立参考模型与解用于最终评分。

LLM 提议与 reference-assisted 基线使用同一个 `BindingProposal` 验证入口。所有响应均保存，不因失败修改 prompt。

## 独立验证与成本

每组保存 prompt、原始响应、解析结果、绑定哈希、clean/wrong 标签来源、独立业务评分、接受/拒绝/UNKNOWN、冲突和成本。额外反例包括错误系数/上限、缺原文与冲突；不接受较有利但证据不足的提议。

分别记录真实 LLM 调用数、prompt/completion tokens、延迟、实际 SCIP 次数和 reference-assisted 成本。模型生成不是正确性的证据，协议复用也不等于跨族泛化、进化或 SOTA。

最后执行完整 pytest 与 `m2gen` 回归。

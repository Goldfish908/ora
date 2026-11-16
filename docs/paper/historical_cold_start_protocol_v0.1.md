# 历史 Qwen 候选的 cold-start 绑定验证协议 v0.1

## 来源与边界

当前仅有默认 Aliyun 配置，未配置用户指定内网 Qwen 服务，因此本轮不发起新 LLM 调用。改用 `work/frozen_scoped_milestone_v0.1/BWOR-002/initial/` 中已保存的 Qwen3.8-27B 原始响应和精确 revision，保留其生成配置、响应哈希和原始 token 成本。

这不是本轮新 LLM 生成，也不是未见过数据的 frozen 评估。验证的是：**历史 LLM 候选经过严格契约归一化后，能否形成可被独立业务验证的绑定。**

## 输入处理与隔离

原始响应只用于 candidate-derived 提议。先执行既有变量列表、`data.path` 和列表索引归一化，再验证共享变量 schema 并运行 SCIP。

`objective_recompute` 和 `resource_bound` 的 candidate-derived 提议只能来自该候选的表达式、约束和题面来源，不读取独立参考约束、目标表达式或答案。reference-assisted 对照可以使用独立参考规格，并明确标记。公开答案只用于已有的参考评分口径。

## 验证

同一 `BindingProposal` 验证入口分别处理 candidate-derived 与 reference-assisted 提议。每组包含：

- 有效候选提议；
- 不正确上限/目标或缺原文的反例；
- 缺标签来源与冲突时的 UNKNOWN；
- 独立 BWOR 参考模型与解的业务评分。

蛋白 lower-bound 必须核对数值系数和 700 下限，不仅比较最终目标值。初始候选经过归一化后才可求解；错误契约、路径或 schema 不得到达业务验证。

记录新 LLM=0、实际 SCIP 次数、历史生成调用与 token（只代表原候选生成，不等同于本轮新提议生成成本）、绑定哈希、来源、接受、UNKNOWN 和拒绝。不能由“历史 LLM 曾生成”推断绑定正确，也不能将协议复用称为通用跨族、进化或 SOTA。

## 验收

两类提议分别验证有效/错误/缺证据/冲突，错误接受为 0。保存协议、原始响应引用、归一化模型、绑定、反例、独立评分、成本、回滚与结果图，完整 pytest 与 `m2gen` 回归通过。

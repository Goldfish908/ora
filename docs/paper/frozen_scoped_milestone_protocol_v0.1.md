# Scoped / Controller 新初始冻结评估协议 v0.1

状态：在初始生成前登记。评估对象为本版 scoped 资产与 ProgressController 在新初始候选上的表现；不是整个系统或全部数据集的首次 frozen，也不是 SOTA。

## 数据与既有暴露

按 `work/dvsa/bwor_reference/frozen/summary.json` 的 eligible IDs 排序，预先选择前六题：

```text
BWOR-002, BWOR-003, BWOR-005, BWOR-006, BWOR-010, BWOR-012
```

这些题曾用于旧 DVSA 终验，不能称“整个系统首次 frozen”。本轮使用**新的 Qwen3.8-27B 初始候选和本版 scoped 资产/controller 的首次评估**，不与旧生成器结果作因果比较。

独立参考来自既有盲建、参考公开目标校验的模型和解，不是人工专家金标。生成器只获得真实题面与参考变量声明；约束、目标表达式、参考解和公开答案不进入 prompt。这是 schema-conditioned 评估，不是自主变量发现。

## 一次性初始生成

- 模型：`Qwen/Qwen3.8-27B`，revision `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`。
- 从本地固定 snapshot 加载，BF16，`device_map=balanced`；不调用外部 API，不训练。
- prompt：复用 `scripts/dvsa_candidate.py` 的自然语言+共享变量 schema 格式。
- chat template：`enable_thinking=False`。
- `do_sample=False`、seed 42、`max_new_tokens=4096`。
- 每题只生成一次。JSON 解析失败、schema 错误、求解失败均原样保留，**不重试、不改 prompt、不补题、不挑候选**。

## 冻结后的对照

候选生成完成后冻结输入、prompt、资产、controller、预算、修复器、评分器和分母。

- `no_repair`：保留初始结果；
- `fixed`：最多两次确定性局部修复；
- `progress`：最多两次，使用同一确定性修复器和 ProgressController。

资产只使用登记时已有机制。BWOR 的 reference-bound 目标表达式修复只替换 objective.expression，保持变量、约束、data 和 sense；修复后真实运行 SCIP。该路径不是 NL 自主建模或自动 memory 进化。

每题建立独立 clean/wrong 反例门，UNKNOWN、部分 rejected、NOT_APPLICABLE 均不得接受。无接受候选回退初始候选。独立业务评分在修复环外完成。

每题只有一个初始候选，因此本里程碑**不开展在线候选排序**，不引用 pairwise offline 准确率替代在线结果。

## 记录与判定

保存 prompt、原始响应、初始/修复模型、SCIP 输出、资产、逐轮代码或模型哈希、动作、初末业务评分、UNKNOWN、恢复、误接受、harmed_win、token、求解次数、延迟和负结果。

预注册判定：

- **可继续**：至少一个独立评分确认的改善，且 `harmed_win=0`、`accepted_but_business_incorrect=0`；
- **应停止扩展**：没有独立改善，或出现 harmed win，或 checker 接受但独立评分错误；
- 无论是正向还是负向结果，均不追加 prompt、模型、资产或预算调整来制造 milestone。

最后运行完整测试和 `m2gen/run_regression.py`，归档协议、manifest、逐题轨迹和报告。

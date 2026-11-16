# DVSA / BWOR frozen 终验协议 v0.1

状态：在任何 frozen 题面、参考、候选或结果生成之前执行。validation 已完成，未用于修改方法。

## 1. 冻结对象与仅允许的实现变更

- frozen 为既有 41 个 ID，清单见 `data/dvsa/splits_manifest.json` 与 `data/dvsa/bwor/frozen.txt`。
- 模板、文本、参考与 binding prompt、共享初始 prompt、修复 prompt、Qwen3.8-27B、temperature=0、medium reasoning、32K 输出、SCIP 60s 全部沿用 validation 配置。
- 唯一实现变更是 CLI/授权白名单允许 `--split frozen`，以及相应的输出路径和分析驱动。不得改变算法、prompt、模板、参考选择规则、预算或指标。
- `select_reference` 在 frozen 只接受 initial/syntax_r1；不接受 dev 的人工 `structural_r1`。
- 禁止闭源模型、参数训练、validation/frozen 结果回写资产。

## 2. 信息顺序

1. 冻结实现和本协议并登记哈希。
2. 参考作者只在 frozen ID 上工作，不看候选、文本 memory、binding、witness 或公开答案；公开答案仅在求解后核对。
3. 参考不可行、目标冲突、来源失败或规格无效均保留为覆盖失败；仅允许一次不看答案的 syntax-only 修复。
4. 在参考状态固定后，确定参考合格子集。后续各臂共享变量声明，但不共享参考约束、目标表达式或答案。
5. 生成独立 binding、共享初始候选、四臂修复与盲评。任何 frozen 输出都不得用于提议、选择、调参、资产更新或新 prompt。
6. 全部完成后只做一次性统计与失败归因，不为改善分数重跑不同配置。

## 3. 四臂与指标

- A0 no-memory、A1 text-memory、A2 DVSA、A3 direct-legacy，沿用 validation 的共享初始和最多一次修复规则。
- 固定制品报告错误检出、干净解误报、UNKNOWN、唯一解分母和成本。
- 自然修复报告当前解业务正确（独立参考审计 + 公开目标绝对误差≤0.1）、语义可行、目标合格、改善、`harmed_win`、逐题 McNemar 和成本。
- 全 41 题报告参考覆盖与保守下限；主要机制配对只使用候选产生前已确定的参考合格子集，不能按方法结果挑选题目。
- 直接旧 witness 在 BWOR 只记 `unknown_schema`，不能将其 fail-open 视为正确通过。

## 4. 最终有效线与结题规则

只有同时满足以下条件才启动同口径 SOTA 对照：

1. A2 相对 A1 的 frozen 逐题业务正确 McNemar `p<0.05`；
2. 独立干净制品误报率≤10%；
3. `harmed_win=0`；
4. 至少一个真实的 frozen-template 复用路径，而非全部逐题临时编写 checker。

未达到任一项，则交付负结果、失败层级和机制边界并结题，不启动 SOTA、不扩大数据集、不购买模型、不移动球门。即使达到，SOTA 对照也必须使用相同数据子队列、参考口径、初始生成器和预算；COOPA 全 BWOR 或其他分母的公开数字只能作背景参照。

## 5. 可复现记录

- 最终注册表：`assets/dvsa/registry_v0.7.json`。
- 分片执行与汇总脚本只读取参考合格 ID，失败停住并保留日志，不静默跳过。
- 最终图集中到 `/home/hewj13/paper_icml2027/figures/`，原始输出在 `work/dvsa/*/frozen/`。
- validation 的结论保留：自然质量无差异、binding 存在覆盖失败、DVSA 有调用节省。不得根据 frozen 结果回改这些历史记录。

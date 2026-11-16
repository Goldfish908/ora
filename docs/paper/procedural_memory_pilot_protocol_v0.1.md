# 程序性 Memory 跨域先导协议 v0.1

日期：2026-11-12 · 状态：真实 LLM 调用前冻结；仅开发集机制探索，不是 sealed/frozen 终验。

## 1. 研究问题与近邻约束

研究的不是“程序性 memory”这一概念是否新颖。OptiSkill、OptSkills、AWM、Memp 已覆盖技能/工作流蒸馏与复用；OptiSkill 还覆盖 solver-verified admission、修复与回归检查。

本先导检验一个更窄的问题：

> 对未见优化问题构造解级语义检查时，迁移通用的诊断—检查—验证程序，是否比仅提供声明式文本经验更少误报和 UNKNOWN，并保持独立错误检出？

首轮只测检查器 authoring，不测完整求解或端到端修复，不证明通用业务正确率提升。

## 2. 制品与信息隔离

- 数据：`work/memory_witness/nlp4lp_artifacts_v2/dev`。
- 26 个问题、121 个制品：95 个独立受控错误、26 个独立干净解。
- 允许使用全部 dev ID；不读取 validation 或 sealed 的题面、制品、标签或结果。
- 不将 RetailOpt witness 或 NLP4LP dev 上已有 checker 作为输入，避免作者与评委同源。
- 每题所有臂共享题面、solution schema 和制品；独立参考标签仅用于事后评分。

## 3. 四臂

所有臂共享相同的 Python 输出契约、模型、温度、推理设置和最大 token。

1. `zero`：无审计经验，仅题面与输出契约。
2. `text`：声明式文本经验，如重算目标、检查资源边界/守恒/变量域、不要发明要求。
3. `procedure`：通用诊断程序。依次枚举变量与量化作用域、建立需求清单、选择数值重算、检查目标与变量域、构造 must-pass/must-fire 思路、无法判定时输出 UNKNOWN。
4. `combined`：同时提供 `text` 与 `procedure`。

每题每臂一次 authoring 调用，`max_repairs=0`。不在问题之间传递新生成的 checker，不进行在线 memory 写回。

另设开发内辅助臂 `procedure_cegis`：从 `procedure` 初始检查开始，最多使用一次 dev 独立反例修复。它测“程序 + 标签验证流程”的开发内拟合上界，不与零修复臂作迁移结论，也不作为主晋升依据。

## 4. 主指标与比较

固定制品指标：

- 错误检出率；
- 干净解误报率；
- UNKNOWN 率；
- 每题过门率（检出≥60%、干净误报=0、UNKNOWN=0）；
- fail-open 接受解中的干净比例（accepted precision），用于观察“无法判断被放行”的风险；
- 逐制品配对 McNemar 精确检验，但小样本只作探索性参考；
- LLM 调用、输入/输出 token、延迟。

主比较：`procedure vs text`；辅助：`combined vs text`、`procedure vs zero`。

已知限制：现有执行评分把具体违规输出记为检出，但没有严格证明每个命中都对应变异的目标机制。首轮后必须抽查命中规则，不能将任意报错都解释成正确语义归因。脚本故障和明确 UNKNOWN 不得计为检出。

## 5. 扩量与停止规则

- 若 `procedure` 或 `combined` 相对 `text` 提高每题过门率，同时干净误报和 UNKNOWN 不增加，则值得在第二个独立开发域扩大机制验证。
- 若只提高检出但增加误报，不视为有效。
- 若只降低 UNKNOWN 但检出显著下降，不视为有效。
- 若差异主要出现在一两题或伴随明显的目标机制错配，只作案例，不扩量。
- 未达到上述方向，不启动新数据集、第二模型、参数训练或 SOTA 对照；先分析提示、检查覆盖和输出契约。

## 6. 可复现记录

实现：`scripts/procedural_memory_pilot.py`；分析：`scripts/procedural_memory_analyze.py`。

运行前记录制品、脚本和协议 SHA256；每题保存完整提示、原始响应、生成脚本、逐制品执行结果、usage 与延迟。API 凭据只走环境变量，不写入提示、日志或结果。

# DVSA / BWOR validation 冻结协议 v0.1

状态：在任何 validation 题面、参考、候选或结果生成之前冻结。sealed/frozen 仍封闭。

## 1. 数据与资产

- BWOR release：SHA256 `8e1806c9b23f71136e6e174c03a51cab53b3d145d21846f8160d1900ed7d1a15`。
- 73 个 LP/IP/MIP 的既有 ID 划分：dev 16 / validation 16 / frozen 41；清单 SHA256 `361498953b0a87ebb933bbddb6f837dc4098289a21a1ca05650154135e1cf7a6`。
- 六个 BWOR 模板及其文本来自 `assets/dvsa/bwor_primitives_v0.1.json`，以注册表中的文件哈希为准。
- 只冻结 BWOR 通用模板；RetailOpt 的 `C-INIT/C-DEMAND` 不注入新域。direct-legacy 仅作为 RetailOpt schema 不兼容的负对照。
- 不使用闭源模型生成参考、binding、候选、反馈或资产。

## 2. 参考与共享 schema

- 参考作者只看题面和格式规范，不看公开答案、候选、文本 memory、binding 或 witness。
- validation 仅允许一次 **syntax-only** 修复：输入为原参考模型和执行错误，不输入公开答案；禁止人工结构修订、目标导向改约束或根据 validation 结果改 prompt。
- `select_reference` 在 validation 不接受 `structural_r1`，只接受 initial/syntax_r1 中满足以下条件的参考：
  - 所有约束来源通过题面原文校验；
  - SCIP `optimal` 且自审计 `VALID`；
  - 与公开答案绝对误差≤0.1。
- 参考不可行、目标冲突、来源不合格、规格失败均保留为覆盖失败。不得为了扩大分母人工修好参考。
- 各臂共享参考变量声明，但不见参考约束、目标表达式或公开答案。这是 **schema-conditioned** 实验，不是自主变量发现或无辅助全 pipeline SOTA。
- 缺失 `data` 字段默认为空对象；任何缺失 `data.path` 仍然失败，不把参数默认为零。

## 3. 固定运行配置

- 模型：内网 `Qwen3_8-27B`，temperature=0，`reasoning_effort=medium`；代码/JSON 生成 `max_tokens=32768`。
- 每题参考 1 次调用，最多 1 次 syntax-only 修复；binding 1 次；共享初始候选 1 次。
- 文本固定制品评审每题每臂 1 次，沿用 dev 的 opaque/shuffled artifacts 和数值证据纪律。
- 自然修复每臂最多一次反馈/自评；A3 复用 A1 并记录旧 witness `unknown_schema`，同时报告实际与独立运行等价成本。
- A2 satisfied 时零修复调用；数值违规时一次修复；无初始解时一次执行反馈恢复，标为 `execution_failure_unknown_semantics`，不算语义修复。
- 本轮 BWOR 不追加第二次执行恢复；修复后仍无解记为失败并保留，不根据结果增加预算。
- SCIP 每模型 60s；禁止 Gurobi。
- 受控变量变异后同步重算目标；目标误报单独构造；相同解只计一次。

## 4. 分母与结局

- **参考覆盖**：全部 16 题都报告参考状态、缺失原因和覆盖率，不能只展示成功参考。
- **固定制品**：在参考合格问题中使用独立参考解和受控错误，报告错误检出、干净解误报、UNKNOWN、逐制品配对与成本；唯一解去重。
- **端到端业务正确**：当前解通过独立参考审计且公开目标绝对误差≤0.1；分开报告语义可行、目标合格和共同成立。
- 主要配对比较在候选输出产生前已经确定的参考合格子集上进行；参考失败不参与方法胜负，但必须披露。另报全 16 题的公开目标准确率和保守 UNKNOWN 口径。
- `harmed_win`：初始业务正确被修坏，目标为 0；初始代码哈希必须四臂一致。
- 成本包括共享初始、参考/binding（单列）、修复调用、token、LLM 延迟、求解调用；A3 同时报告复用与独立运行等价成本。

## 5. 使用纪律

- validation 结果不得用于修改模板、文本、binding prompt、参考 prompt、初始 prompt、预算或统计口径。若发现工程 bug，必须保留旧版本、修复后重新跑完整 validation，并登记新版本。
- 本轮只做迁移检查，不启动 SOTA。最终有效线仍在 frozen：A2 对 A1 的逐题业务正确 McNemar `p<0.05`、干净误报≤10%、`harmed_win=0`，且有真实冻结模板复用。
- frozen 不因 validation 好坏而改变规则。完成后才允许一次性生成 frozen 的盲参考与候选；frozen 结果不得回写任何资产。

## 6. 可复现记录

资产、实现、prompt 文件、划分与协议哈希登记在 `assets/dvsa/registry_v0.6.json`。运行输出分别放在 `work/dvsa/*/validation/`，不得覆盖 dev 结果。

# 先验注入 pilot v0.1(memory 级自进化第 1 代)

日期:2026-11-02。目的:验证"把蒸馏出的约定作为先验注入 prompt"能否在
**生成时刻**预防错误,而不是等错误发生后靠反馈环修复。这是 memory 自进化
主线的第一次在线实验(G0–G8 从反馈轨迹蒸馏 → 冻结 → 注入 → 零样本重跑)。

## 1. 方法

- 先验文件:`configs/conventions_priors_v0.1.txt`(G0–G8 的自然语言版,
  纯 PySCIPOpt API/harness 工具知识,不含题目语义与答案,符合防泄题协议);
- 运行:零样本 schema_sol pilot 重跑(与基线 pilot 同变体、同模型
  Qwen3_8-27B、同 thinking on),`scripts/m1_pilot.py --conventions-file`;
- 输出隔离:`runs/m1_pilot_priors/`(不污染 `runs/m1_pilot` 的 glob);
- 事故记录:首跑因 `--out-dir` 相对路径导致执行子进程找不到 gen.py
  (190/190 假 crash);LLM 生成已完整落盘,用 `scripts/recover_priors_exec.py`
  以绝对路径重放执行+witness,零 LLM 重跑成本恢复。`m1_pilot.py` 已修
  (`.resolve()`)。

## 2. 结果(190 细胞,on 模式,pass@1 口径 = witness 可行 + 目标值 match/better)

| 指标 | 基线 pilot | 先验注入 | 变化 |
|---|---|---|---|
| **pass@1(真成功)** | 13/190 (6.8%) | 16/190 (8.4%) | +1.6pp |
| **crash** | 121 (64%) | **13 (7%)** | **-57pp** |
| **幻影(出解但 witness infeasible)** | 56 (29%) | 159 (84%) | +55pp |
| 可执行 | 69 (36%) | 177 (93%) | +57pp |

**先验遵守度验证**:对 190 份生成代码重放 guard AST 规则,仅 4 例 G0
(语法)命中,G1–G8 **零命中**——先验文本几乎被完全遵守,模型第一次就
写对了 `sense="minimize"`、`quicksum`、不遮蔽 `data`、不读幻觉文件名。

**残余 13 个 crash 归因**:7× NotImplementedError(G3 难形态:变量级
表达式比较,挖掘报告已预言静态规则性价比低)、3× IndentationError、
1× addCons 传 bool、1× 语义 KeyError(幻觉数据键)。与
`crash_guard_mining_v0.1.md` §5 的"留给运行时防线"清单完全一致。

## 3. 结论

1. **知识层(memory 先验)对工程层错误是决定性的**:crash 64%→7%,
   且是**零样本、生成时刻**预防——不需要任何反馈轮次,每题省掉整段
   crash-修复循环的 LLM 调用与求解浪费。
2. **瓶颈迁移被再次实证**:消失的不是错误而是 crash;省下来的题几乎全部
   转化为幻影(56→159,出解题中 90% 幻影)。pass@1 只 +1.6pp——
   **工程层知识无法替代语义层校验**,这正是闸门+witness 存在的理由,
   也是"分层校验"框架的核心预言(错误分层、各层需各层的机制)。
3. **对自进化路线的设计含义**:第 1 代 memory(工具知识)已打满其价值;
   第 2 代必须进入语义层——族级约定先验(如"初始库存默认为零"类)或
   checker-authoring agent 自动产出的规则,才可能移动幻影率。
4. 与 ReLoop 对照联读:ReLoop L1 环在弱模型上把 crash 33→14(在线修复),
   我们把 121→13(生成时预防)——**预防优于修复**,且我们的幻影层有
   witness 兜底而 ReLoop 没有。

数据:`runs/m1_pilot_priors/m1_pilot_schema_sol_priors_v{0..4}.jsonl`
(原始假 crash 记录备份为 `.badexec.bak`)。

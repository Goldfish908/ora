# External Baselines v0.1 — 外部参照系（超越目标）

日期：2026-11-02。用途：钉死自建/开源边界与对照目标，供论文与汇报统一引用。

## 1. 数据集权属（必须讲清）

- **RetailOpt-190 不是自建**：ReLoop 团队公开（NeurIPS 2026,arXiv:2602.15983;
  GitHub junbolian/ReLoop、junbolian/RetailOpt-190;HuggingFace)。38 原型 × 5 数值
  变体，单一零售 MILP，12 种机制由数据激活，附 Gurobi 参考求解器与参考目标值。
- **我们自建的**:PySCIPOpt/SCIP 参考求解器（正对照，逐族校准到参考目标值）、
  泛化 witness(m1_witness/retailopt.py,38 亚族参照解全过）、schema_sol 执行契约、
  M2 受控组合集、f1 语义缺陷 mutants、预求解闸门。
- 选型理由（motivation_study_v0.1 §M1)：带参考解可程序验证；机制可控可分解；
  38×5 多实例压偶然正确；IndustryOR/MAMO-ComplexLP 列为补充证据。
- 已知坑：原生依赖 Gurobi 学术许可（我们没有）→ SCIP 重写 + 校准链。

## 2. ReLoop 官方成绩（RetailOpt-190,pass@1,greedy,N=3，严格 ε=1e-4)

| 模型 | Base | +ReLoop | 备注 |
|---|---|---|---|
| Claude Opus 4.6 | ~22.6% | **31.1%**（实用 ε=1e-2:35.3%;Exec 100%) | CoT +8.5pp(p≈0.002) |
| DeepSeek-V3.2 | 0.5%(Exec 91.1%) | 严格≈不变；实用 11.1% | 90pp 幻影鸿沟 |
| Qwen3-32B / OptMATH-32B / SIRL-32B | ≈0% | ≈0%(Exec 有恢复，如 OptMATH 2.6%→17.9%) | 32B 级超出推理容量 |

**已发表 SOTA(RetailOpt-190)= 31.1%(Claude Opus 4.6 + ReLoop)。**

跨 benchmark（论文 Table 7,ε=1e-6):IndustryOR DeepSeek 50→62%、Claude
66→68%;MAMO-ComplexLP OptMATH Base 56.2%(CoT 反伤 SFT 模型至 30.0%)。

## 3. 我们的位置与口径差异

| | 本工作（Qwen3_8-27B) | ReLoop 协议 |
|---|---|---|
| 零样本 pass@1 | 6.8%(F10) | Claude 22.6%;32B ≈ 0% |
| 完整系统 | 45.8%(F14,B 臂） | 31.1%（已发表最佳） |
| 协议 | 最多 3 轮 witness/闸门反馈环 | 一次性生成 + 恢复层 |
| 容差 | 相对 1e-3 + witness 规则 | 严格 1e-4（仅目标值） |

45.8% > 31.1% 但协议不同（反馈预算、容差）。对外 claim 的可选路径：
(1) 同模型实现 ReLoop 对照臂（最干净）;(2) 报告 pass@1 + 逐轮曲线对齐预算；
(3) 标注协议差异，卖点 = 27B 内网模型 + 确定性验证 > 前沿/671B 模型。

## 4. 差异化定位素材

ReLoop 残余分析（附录 J)：55 例残余失败中 42/43 为结构性幻影（分解与参考不同
但自洽，扰动测试测不出）。与我们 C-INIT 隐藏约定发现互证；我们的台账 diff
离线召回 87.5–100%(F13)，覆盖了 ReLoop 自认测不出的错误类。

## 5. 参考链接

- ReLoop 论文：https://arxiv.org/abs/2602.15983 (v4 html: /html/2602.15983v4)
- 代码与数据：https://github.com/junbolian/ReLoop 、
  https://github.com/junbolian/RetailOpt-190

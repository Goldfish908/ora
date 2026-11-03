# 自进化最小可行版:第 0-3 代结果与生死判据

日期:2026-11-03(进行中)
设计:`self_evolution_design_v0.1.md`
驱动:`scripts/evo_driver.py`;切片 `data/m1_retailopt/dev40_f1f4.jsonl` /
`gapcheck60_f1f4.jsonl`(sha256 见 slices_manifest.json)

## 判据(设计文档 §0 预先写死)

进化第 3 代冠军须:(a) 在 dev40 上显著超过手工蒸馏 P3 种子;
(b) 在 gapcheck60 上落差 ≤5pp;(c) 全量 190 题上 F5-F8 留出族不衰减。
满足 → 继续投入视野 2;不满足 → 如实报告负结果,回到手工+集成路线。

## 第 0 代(8 个基因组,全部确定性构造,零 LLM 变异成本)

| 基因组 | 算子 | 内容 |
|---|---|---|
| g0_seed | seed | P3 配置原样(v0.2 代码惯例 + 语义 v0.1) |
| g0_no_subrule | deletion | 去语义第 3 条(替代方向) |
| g0_no_dump | deletion | 去语义第 5 条(转储完整性) |
| g0_no_init | deletion | 去语义第 6 条(初始库存) |
| g0_no_scaffold | deletion | v0.2 去建模程序脚手架 |
| g0_sem_reorder | reorder | 需求等式/替代条款提前 |
| g0_sem_emph | emphasis | 附加条款 2-3 显著性提醒 |
| g0_sem_first | reorder | 语义块置于代码块之前 |

## 结果

### 基线(手工蒸馏 P3,已核实)

| 口径 | 数值 |
|---|---|
| dev40 单发 | 25.0% (10/40) |
| gapcheck60 单发 | 21.7% (13/60) |
| 全量 190 单发 | 21.6% (41/190) |
| 其中 F5-F8 留出族 | 20.0% |

"显著超过"的操作定义:dev40 成功率差 ≥ +10pp(40 题下约等于
多对 4 题,且超过逐题配对噪声带);"留出族不衰减":全量 190 中
F5-F8 成功率不低于 P3 的 20.0% - 5pp = 15.0%。

### 第 0 代 dev40 适应度

(待填:8 基因组 success/phantom/tokens 台账表)

### 逐代冠军与过拟合检查

(待填:每代冠军 gid、dev40 vs gapcheck60、落差,>5pp 触发报警)

### 第 3 代冠军全量 190 题

(待填:总成功率、按族分解、F5-F8 留出族专项、与 P3 基线对比)

### 判据裁决

(待填:继续 / 回退,附证据链)

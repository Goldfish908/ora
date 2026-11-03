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

(待各代跑完填写:dev40 适应度表、每代冠军 gapcheck60 落差、
第 3 代冠军全量 190 题与留出族分解、判据裁决)

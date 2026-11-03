# 语义层第 2 代 memory v0.1:需求/替代语义惯例 + 族留出协议

日期:2026-11-03(结果待填)
配置:`configs/semantic_priors_v0.1.txt`(独立 provenance)
`configs/conventions_priors_v0.3.txt` = v0.2 + semantic_priors_v0.1
脚本:`scripts/run_priors3_pilot_shards.sh`(pass@1)
`scripts/run_combo3_shards.sh`(全环 P3 臂)
`scripts/semantic_memory_analysis.py`(族留出分析)

## 1. 动机:残余失败的性质变了

guard v0.4 + 闸门之后,crash 类失败已被压到 5-10%;B''/combo 两链的
残余主体是 **witness 判 infeasible 且目标值优于参照** 的"幻影":
模型求出了一个更便宜但物理上不可行的解。

对 B'' 臂 113 个幻影细胞(on 模式,全部轮次)按 witness 首条违例签名分类:

| 签名 | 占比 | 根因(逐案核查 gen.py 后确认) |
|---|---|---|
| balance < 0 | 56/113 (50%) | 替代方向/符号错:模型按"供应视角"建模 sub,与 dump 契约(pf 的需求由 pt 满足)相反,或把 sub_in 的符号放错边 |
| balance == 0 | 31/113 (27%) | 转储不完整:sales/lost 只写了部分 (p,l,t) 或漏字段,缺失键被读作 0 |
| 0 < balance < demand | 14/113 (12%) | 部分满足:少记 lost 或漏记替代流入 |
| balance > demand | 6/113 (5%) | 需求写成 >= 覆盖约束,优化器超卖(卖给出价不存在的顾客)收割幻影收入 |
| balance = 1e20 | 1/113 | big-M 不紧致,幻影流泄漏 |
| C-INIT / C-AGING 等 | 5/113 | 自造初始库存、库龄守恒错误 |

典型实例(retail_f4_demand_surge_v0):模型写
`own_sales + sub_out + lost >= demand` 且 `sales >= sub_in`,
同一批 SKU_Basic 库存**同时**满足自己的需求和 SKU_Premium 的替代需求
——一份货卖两遍,目标值自然优于参照。witness 的 C-DEMAND 等式检查
当场抓住(balance=-37.75 != 37.75)。

**关键事实:dump 契约里已写明 `sub: "pf|pt|l|t" demand of pf served by
pt`。模型不是没看到,而是在长上下文+多机制叠加下回退到了自己默认的
"供应视角"惯例。** 这正是"连接/接口语义"错误的代表:约束都写了,
但变量含义接错。

## 2. 方法:语义惯例作为第 2 代 memory

第 1 代 memory(conventions v0.1/v0.2)蒸馏的是**工具知识**
(PySCIPOpt API 陷阱),解决 crash;第 2 代蒸馏的是**领域语义**
(需求平衡、替代方向、转储完整性),解决幻影。

`semantic_priors_v0.1.txt` 共 7 条:需求恒等式、需求平衡等式化、
替代方向+库存扣减(禁双计)、lost 语义、转储完整性、初始库存默认为零、
big-M 紧致性。全部不含任何实例数值/族名/答案,是数据集级语义陈述。

## 3. 防泄题:族留出协议

这类知识的蒸馏过程看过了失败案例(经 witness/参照值),存在间接泄题
风险。协议:

- **dev 族 F1-F4 / held-out 族 F5-F8**;
- 逐族报告幻影率与成功率;若收益只出现在 dev 族,说明过拟合,
  held-out 数字是唯一可信的外推证据;
- 局限声明:本批次 taxonomy 统计覆盖全部 8 族,但 7 条惯例中
  6 条的直接证据来自 F1-F4 案例;big-M 条款的动机案例见于 held-out 族
  (属通用建模卫生,不针对实例)。

## 4. 实验设计

- **P3 臂 = P2 生成端 + 语义惯例**(conventions v0.3),其余与 combo 臂
  完全相同(guard v0.4 + 闸门 + witness 环,最多 3 轮,thinking-on);
- 对照:P2(combo 臂)——只差 7 条语义惯例,隔离单变量;
- 指标:pass@1 幻影率(预防效果)、pass@1 成功率、全环最终成功率,
  均按 dev/held-out 分别报告。

## 5. 结果

(待 pilot + 全环跑完后填写)

## 6. 与既有文档的关系

- 第 1 代 memory:`priors_pilot_v0.1.md` / `priors2_pilot_v0.1.md`
- 单链结果:`crash_guard_online_v0.1.md`(B'')、`combo_arm_v0.1.md`(combo)
- 仲裁:`ensemble_dualchain_v0.1.md`

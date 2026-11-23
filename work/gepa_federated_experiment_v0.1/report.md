# 三场景五臂 GEPA 联邦修复判别实验

五臂均使用同一 root Candidate、公开文件和评价器。搜索臂最多 6 次 child evaluation，direct-full 恰好 1 次；population 为 k=3、depth=2，随机种子 20261123。merge 替换槽位 mutation，不占额外槽位或求解预算。所有臂在本次运行中真实执行；旧 baseline 仅做哈希交叉核验。

多目标 score 为 feasibility、归一化 public objective、归一化负成本。`native_per_key_winners`、GEPA 剪枝后的 native elites 与完整 `non_dominated_archive` 分别报告。完整审计保留未舍入数值和逐条成本 ledger。

所有 final elite-best 先冻结并核验 SHA256，再进行官方复评；官方结果不进入选父、接受或扩展决策。总成本 = 独立搜索 ledger + 最终官方 runner wall time，solver 时间已含在 evaluation 中，不重复相加。

| Scenario | Arm | Official true | Official quality | Official objective | Search s | Official s | Total s | Child eval | Solver calls | Native winners | Native elites | Full non-dominated |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| duplicate_client | direct-full | True | 1.9999999999981872 | 6020.689909999998 | 1.909812 | 42.609065 | 44.518877 | 1 | 1 | 2 | 2 | 2 |
| duplicate_client | single | True | 2.0 | 6021.2476195 | 4.256615 | 23.907108 | 28.163723 | 4 | 3 | 3 | 2 | 2 |
| duplicate_client | old-population | True | 2.0 | 6021.247619499997 | 6.539342 | 29.133475 | 35.672817 | 6 | 4 | 3 | 2 | 2 |
| duplicate_client | pareto-only | True | 2.0 | 6021.247619500001 | 6.356053 | 21.739458 | 28.095511 | 5 | 4 | 3 | 2 | 2 |
| duplicate_client | pareto+compatible+merge | True | 2.0 | 6021.247619499997 | 6.335940 | 48.048672 | 54.384612 | 5 | 4 | 3 | 2 | 2 |
| stream_minimums | direct-full | True | 1.9999999999984894 | 6020.689909999999 | 1.881705 | 53.217478 | 55.099183 | 1 | 1 | 2 | 2 | 2 |
| stream_minimums | single | True | 2.0 | 6021.590728499996 | 6.481440 | 32.609377 | 39.090817 | 5 | 4 | 2 | 2 | 2 |
| stream_minimums | old-population | True | 2.0 | 6021.590728499999 | 6.846578 | 16.100353 | 22.946931 | 6 | 4 | 3 | 2 | 2 |
| stream_minimums | pareto-only | True | 2.0 | 6021.5907284999985 | 6.705229 | 14.491304 | 21.196533 | 5 | 4 | 2 | 2 | 2 |
| stream_minimums | pareto+compatible+merge | True | 2.0 | 6021.590728499993 | 6.888125 | 10.594760 | 17.482885 | 5 | 4 | 2 | 2 | 2 |
| all_budgets | direct-full | True | 1.9999999999987914 | 6020.68991 | 2.197905 | 23.651048 | 25.848953 | 1 | 1 | 2 | 2 | 2 |
| all_budgets | single | True | 2.0 | 6021.247619499992 | 6.649543 | 26.215394 | 32.864937 | 5 | 4 | 3 | 2 | 2 |
| all_budgets | old-population | True | 2.0 | 6020.7034476000035 | 6.419330 | 23.779092 | 30.198422 | 6 | 4 | 3 | 2 | 2 |
| all_budgets | pareto-only | True | 2.0 | 6021.247619499998 | 7.415299 | 10.074209 | 17.489508 | 5 | 4 | 3 | 2 | 2 |
| all_budgets | pareto+compatible+merge | True | 2.0 | 6021.247619499996 | 8.052026 | 18.625355 | 26.677381 | 5 | 4 | 3 | 2 | 2 |

## 关键路径与 merge 判别

direct 路径成功只表示同一 direct-full exploration 完成生成、以 exploration 接受、选为 feasible-parent-objective 父代并真实执行求解，不表示目标值提升。merge 只有真实兼容、非重复且完整公开检查 PASS 才计 tested；其余全部计 not_tested，不计 invalid。

| Scenario | Arm | Direct generated | Accepted | Selected | Executed | Path success | Merge attempted | Compatible | Novel | Valid | Tested | Accepted | Not tested | Stop |
|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| duplicate_client | direct-full | 1 | 0 | 0 | 0 | False | 0 | 0 | 0 | 0 | 0 | 0 | 0 | budget_exhausted |
| duplicate_client | single | 1 | 1 | 1 | 1 | True | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no_new_evaluations |
| duplicate_client | old-population | 2 | 2 | 0 | 0 | False | 0 | 0 | 0 | 0 | 0 | 0 | 0 | budget_exhausted |
| duplicate_client | pareto-only | 2 | 2 | 1 | 1 | True | 0 | 0 | 0 | 0 | 0 | 0 | 0 | depth_exhausted |
| duplicate_client | pareto+compatible+merge | 2 | 2 | 1 | 1 | True | 5 | 0 | 0 | 0 | 0 | 0 | 5 | depth_exhausted |
| stream_minimums | direct-full | 1 | 0 | 0 | 0 | False | 0 | 0 | 0 | 0 | 0 | 0 | 0 | budget_exhausted |
| stream_minimums | single | 2 | 2 | 1 | 1 | True | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no_new_evaluations |
| stream_minimums | old-population | 2 | 2 | 0 | 0 | False | 0 | 0 | 0 | 0 | 0 | 0 | 0 | budget_exhausted |
| stream_minimums | pareto-only | 2 | 2 | 1 | 1 | True | 0 | 0 | 0 | 0 | 0 | 0 | 0 | depth_exhausted |
| stream_minimums | pareto+compatible+merge | 2 | 2 | 1 | 1 | True | 5 | 0 | 0 | 0 | 0 | 0 | 5 | depth_exhausted |
| all_budgets | direct-full | 1 | 0 | 0 | 0 | False | 0 | 0 | 0 | 0 | 0 | 0 | 0 | budget_exhausted |
| all_budgets | single | 2 | 2 | 1 | 1 | True | 0 | 0 | 0 | 0 | 0 | 0 | 0 | no_new_evaluations |
| all_budgets | old-population | 2 | 2 | 0 | 0 | False | 0 | 0 | 0 | 0 | 0 | 0 | 0 | budget_exhausted |
| all_budgets | pareto-only | 2 | 2 | 1 | 1 | True | 0 | 0 | 0 | 0 | 0 | 0 | 0 | depth_exhausted |
| all_budgets | pareto+compatible+merge | 2 | 2 | 1 | 1 | True | 5 | 0 | 0 | 0 | 0 | 0 | 5 | depth_exhausted |

## 官方目标差分（最大化，正数表示前者更好）

| Scenario | Pareto-only − old-population | Merge − Pareto-only | Merge − old-population |
|---|---:|---:|---:|
| duplicate_client | 0.000000 | -0.000000 | 0.000000 |
| stream_minimums | -0.000000 | -0.000000 | -0.000000 |
| all_budgets | 0.544172 | -0.000000 | 0.544172 |

## Clean control

| Arm | Not worse than root | Public status | Public objective | Official true | Official quality | Official objective |
|---|---|---|---:|---|---:|---:|
| direct-full | True | FEASIBLE | 6020.689910 | True | 1.9999999999960725 | 6020.689909999992 |
| single | True | FEASIBLE | 6021.247619 | True | 2.0 | 6021.247619499999 |
| old-population | True | FEASIBLE | 6021.247619 | True | 2.0 | 6021.247619499996 |
| pareto-only | True | FEASIBLE | 6021.247619 | True | 2.0 | 6021.247619500001 |
| pareto+compatible+merge | True | FEASIBLE | 6021.247619 | True | 2.0 | 6021.247619499998 |

## 扩展停止与 baseline 核验

Predeclared stop at two generations or six child evaluations, whichever comes first; also stop on a generation with no new evaluation. Direct-full stops after one. No extra solve is allowed to force direct or merge coverage, and no official result triggers expansion.

本轮已按预声明规则停止，未因官方正负结果追加实验。旧 audit SHA256：`330dcd56f55790b7ed0a522eef9b4b57f943f1e7850e7d1970134733d42b3923`；root/final/public-file hash checks=`True/True/True`。baseline 的搜索结果未复用，因此不存在旧运行时或旧官方评价混入新搜索。

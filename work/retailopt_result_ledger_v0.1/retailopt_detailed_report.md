# RetailOpt 累积结果台账（v0.1）

## 当前判断

`57/60=95.0%` 是本次已核实报告中 RetailOpt gapcheck60 的单候选最高真正确率。此前同一60题的最好汇总结果为17/60=28.3%。这不是完整190题、严格 heldout、跨数据集或 SOTA 结论。

不同切分、单/多候选、oracle 合并和评分口径不合并成一个总准确率。缺失的历史字段留空，不补零。

## 同一 gapcheck60：单候选

| 方法/运行 | N | 真正确 | 真正确率 | 代理通过 | 幻影代理成功 | 证据 |
|---|---:|---:|---:|---:|---:|---|
| Manual P3 conventions; single generation / `p3_g0_seed_gapcheck60` | 60 | 12 | 20.0% | — | — | documented_aggregate |
| Genome evolution gen1 champion; single generation / `gen1_champion_gapcheck60` | 60 | 8 | 13.3% | — | — | documented_aggregate |
| Genome evolution gen2 champion; single generation / `gen2_champion_gapcheck60` | 60 | 17 | 28.3% | — | — | documented_aggregate |
| Genome evolution gen3 champion; single generation / `gen3_champion_gapcheck60` | 60 | 15 | 25.0% | — | — | documented_aggregate |
| Official GEPA prompt evolution; one generation per task / `retailopt_gepa_stream_a0_v0.3/candidate_0` | 60 | 3 | 5.0% | 20 | 17 | raw_rollouts |
| Official GEPA prompt evolution; one generation per task / `retailopt_gepa_stream_a0_v0.3/candidate_1` | 60 | 57 | 95.0% | 57 | 0 | raw_rollouts |

## 历史完整190题：不能与60题直接排名

| 方法/运行 | N | 真正确 | 真正确率 | 候选数 | 内环修复上限 | 口径 |
|---|---:|---:|---:|---:|---:|---|
| Zero-shot single generation / `zero_shot_full190` | 190 | 13 | 6.8% | 1 | 0 | retailopt_full190_single_candidate |
| Manual P3 conventions; single generation / `p3_full190` | 190 | 41 | 21.6% | 1 | 0 | retailopt_full190_single_candidate |
| Presolve gate + crash guard + Witness repair / `b_doubleprime_full190` | 190 | 103 | 54.2% | 1 | 3 | retailopt_full190_single_candidate |
| Manual P3 + three-chain ensemble / `manual_p3_three_chain_full190` | 190 | 110 | 57.9% | 3 | 3 | retailopt_full190_multi_chain |
| Two-chain Witness-feasible minimum-objective arbitration / `e3_two_chain_arbitration_full190` | 190 | 130 | 68.4% | 2 | 3 | retailopt_full190_multi_chain |
| Two-chain oracle union of Witness+grade successes / `e1_two_chain_union_full190` | 190 | 132 | 69.5% | 2 | 3 | retailopt_full190_oracle_union |

完整190题中的130/190和132/190分别来自双链仲裁与oracle并集，不与当前单候选57/60作直接优劣比较。

## 当前候选按题族分解

| 题族 | N | seed真正确 | 接受候选真正确 | seed幻影 | 接受候选幻影 | 接受候选UNKNOWN |
|---|---:|---:|---:|---:|---:|---:|
| F1 | 12 | 2 | 12 | 5 | 0 | 0 |
| F2 | 18 | 1 | 18 | 5 | 0 | 0 |
| F3 | 12 | 0 | 9 | 4 | 0 | 3 |
| F4 | 18 | 0 | 18 | 3 | 0 | 0 |

## 接受候选未获真正确的3题

| 题目 | 结果 | 执行 | 求解状态 | 目标等级 | Witness规则 |
|---|---|---|---|---|---|
| `retail_f3_supply_bottleneck_v2` | unknown | crash | None | no_output | — |
| `retail_f3_supply_bottleneck_v3` | unknown | crash | None | no_output | — |
| `retail_f3_unbalanced_network_v1` | unknown | ok | None | no_output | — |

## 其他切分与排除项

DVSA 的18/20=90.0%属于 dev20 saved-candidate replay，单列为 `retailopt_dev20`，不与gapcheck60排名。
N2报告中的57/60是规则撰写成功数，不是模型解题正确数；EvalPlus的57/60属于代码数据集；IndustryOR的74%属于不同数据和业务评分，均未混入本表。

## 数据文件与限制

- `retailopt_runs.jsonl` / `.csv`：运行级汇总，含历史证据等级和比较分组。
- `retailopt_gapcheck60_tasks.jsonl` / `.csv`：当前seed与接受候选共120条逐题记录。
- 当前Witness、数据切片、候选和代码均记录SHA256；历史汇总暂缺统一的逐题哈希，不能声称已重算。
- 当前token字段不含GEPA reflection成本；完整成本需另表汇总。
- 57个真正确是本次Witness+参考目标定义下的 operational true correct，不是完整业务语义证明。

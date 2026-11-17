# 共识陷阱实验（Card A / Card B 的 Minimal next action 1）

问题：运筹建模里，以候选间目标值共识为奖励（StarOR 式无标签信号）是否会选中系统性静默错误？
背景与假设见 `docs/ideation/research_question_cards_v0.1.md`。

## 文件

- `select.py`：按大族（F1–F8）与亚族分层抽场景，避免 `--limit` 的名字序偏置；默认 `--n 48`，优先 `v0`，并对 F3/F7 略加权（F10 幻影更密）。
- `sample.py`：RetailOpt 每题独立采样 K 个零样本候选（与 `scripts/m1_pilot.py --prompt-mode schema_sol` 同一生成、执行、
  witness 路径；thinking on，temperature 0.6，无先验、无修复）。需要内网 Qwen API 和 `m1_pilot.py` 里的执行环境。
- `analyze.py`：按目标值聚类计算共识，对照标签输出多数投票正确率、多数簇标签构成、幻影富集度、共识份额 AUC、
  随 K 变化的曲线、bootstrap 置信区间。不调用 LLM。

门槛实验默认 **48 题 × K=8**，不必先跑满 190。

## 标签

| 标签 | RetailOpt | IndustryOR k3 |
|---|---|---|
| correct | grade 为 match 或 better 且 witness feasible | 目标值与参考差 ≤ 0.1 |
| phantom | grade 为 match 或 better 但 witness infeasible | 不可见 |
| unverified | grade 为 match 或 better 但无 solution.json / 解析失败 | — |
| wrong | 有目标值但不匹配 | 有目标值但不匹配 |
| fail | 无目标值 | 无目标值 |

## 判定规则（跑之前定下）

主指标先在分层切片（默认 48 题 × K=8）上计算；结论清楚则不必补全量：

- **H1 成立（共识陷阱存在）**：`phantom_enrichment_in_majority` 的 95% CI 下界 > 1，
  或强多数簇（≥ K/2）中 phantom+wrong 占比 ≥ 25%。
- **H1 不成立**：富集度 CI 上界 < 1 且 `auc_share_correct_vs_phantom` ≥ 0.7（共识能有效区分正确与幻影）。
- 介于两者之间：报告为不确定，按家族拆分再看。

## 本地已有结果（IndustryOR k3，Qwen3.8-27B，只有目标值标签）

`python3 research/consensus_trap/analyze.py --k3 work/industryor_k3_dev_v0.1/analysis.json`

- 单样本 57.7%，多数投票 67%，pass@3 70%；
- 73 个强多数（≥2/3）中 15 个是一致的错误目标值（约 21%），说明系统性错误在 IndustryOR 上也存在，
  但这里看不到幻影，K=3 也太小。

## 内网运行

见 `RUN_PROMPT.md`。

# 内网机器运行说明（可直接作为 agent prompt）

```text
在 ora 仓库（内网机器，通常为 /home/hewj13/wm/ora）运行共识陷阱实验。只运行下面的命令，不修改 research/ 以外的任何文件，
不改动已有 runs/ 下的结果。

1. 同步代码：
   git fetch origin && git checkout research/consensus-trap && git pull
   确认 data/m1_retailopt/retailopt_190.jsonl 存在，且 scripts/m1_pilot.py 中 EXEC_PYTHON 指向的 python 可用
   （python -c "import pyscipopt"）。

2. 加载 API 环境：source ~/.leagent_env

3. 零成本预检（不调 API）：用已有的三条链第一轮候选跑一遍分析，确认脚本在内网数据上能读：
   python3 research/consensus_trap/analyze.py \
     --samples "runs/m1_pilot*/m1_pilot_schema_sol*.jsonl" --min-k 2 \
     --out runs/consensus_trap/precheck_pilots.json
   注意这些候选来自不同提示（无先验/代码惯例/语义惯例），不是独立同分布采样，只作预检，不作结论。

4. 冒烟：6 个场景 × K=2：
   python3 research/consensus_trap/sample.py --k 2 --limit 6 --workers 4 --out runs/consensus_trap/smoke
   检查 runs/consensus_trap/smoke/samples.jsonl 有 12 行，且大部分行有 grade 和 witness 字段；
   若 llm_error 占多数，停止并报告错误信息。

5. 正式采样：190 个场景 × K=8（约 1520 次调用）：
   nohup python3 research/consensus_trap/sample.py --k 8 --workers 16 \
     --out runs/consensus_trap/retail_k8 > runs/consensus_trap/retail_k8.log 2>&1 &
   中断后用同一命令续跑；结束后若有 llm_error，追加 --retry-errors 重跑一次。

6. 分析：
   python3 research/consensus_trap/analyze.py --samples "runs/consensus_trap/retail_k8/samples.jsonl" \
     --out runs/consensus_trap/retail_k8_analysis.json
   另跑一次聚类容差敏感性：加 --rel-tol 1e-3，输出到 retail_k8_analysis_tol1e-3.json。

7. 回传：把 run_config.json、两个 analysis json、precheck_pilots.json，以及
   samples.jsonl 中 exec_status/grade/witness 的计数汇总贴回来（不需要传 sandbox）。
   报告 llm_error 数、平均每次调用延迟和总墙钟时间。
```

## 成本估计

参考 IndustryOR k3：每次生成约 1.3 万 completion tokens、约 130 秒。RetailOpt 每次还要执行 MILP（上限 620 秒）。
1520 次调用、16 并发，预计 4–8 小时。时间紧可先跑 `--k 8 --limit 60`（按场景名排序取前 60，覆盖前几个家族），
或用 `--families` 选家族。

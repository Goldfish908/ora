# E0 工程事实表与冻结基线（5195 任务书 §6 E0）

日期：2026-10-29。核验方式：源码/配置/日志直接读取，不转述旧报告。

## 1. 版本与基线

| 项 | 值 | 核验 |
|---|---|---|
| 工程仓库 | `/home/hewj13/wm/ora`,git 分支 `round2` | HEAD `e9972e8`（含 coworker research/cex-supervision 合并） |
| v1 基线 | 分支 `master`,commit `aaf8bdd` | 保留可复跑 |
| Round 2 交付 | `a4bcd85`(B0/B2+报告+图）、`818b66d`(2.7 分叉+任务书） | 已推 GitHub Goldfish908/ora |
| ORAgentBench pin | `c9eb952435a4352f33daa2a35efe0f8c76d31b28` | 嵌套 repo，未入库（.gitignore) |
| 基础镜像 | `oragentbench-base:py311-scip`(567MB,sha 前缀 c4c7c02483c9) | docker images 实测 |
| Harbor | 0.24.0(`~/.local/bin/harbor`) | 自定义 agent 需 `PYTHONPATH=$PWD` |
| 单测 | 51/51 通过（`python3 -m unittest discover -s tests`) | 本日重跑 OK |

## 2. 模型与端点

| 项 | 值 |
|---|---|
| actor/predictor/worker 模型 | `qwen3.8-27b`(Aliyun MaaS,`DISTILL_BASE_URL` 环境注入，凭据零落盘） |
| thinking | actor/predictor 默认开（端点默认）;worker 关（`worker_llm_extra.enable_thinking=false`,b2_round2.yaml:76) |
| 实测延迟 | thinking 开：单次 1–8 min(audit 实测 508s);thinking 关：2–15 s |
| 已知故障 | 偶发 read stall,600s×3 重试全超时 → llm_error(B2 airport 臂）；旧 ModelFactory Qwen38-27B 已下线（405) |

## 3. 冻结基线配置（E-B0 历史参照）

`configs/b0_round2.yaml`:max_steps=40,token_budget=1.2M,enable_workers 缺省关，predict off,decision_integration=false。
`configs/b2_round2.yaml`:同 B0 + enable_workers=true + worker thinking 关。
两者其余项逐字段一致（隔离有单测断言）。

## 4. 与 Round 2 报告的差异核对（§6 E0 要求逐项）

| 项 | 报告声明 | 源码核验结果 |
|---|---|---|
| decision_integration | false | 属实：loop 中显式 false + warning;active 模式只记录不反馈 |
| thinking 设置 | worker 关、actor 开 | 属实（b2 yaml:76;actor 无 extra) |
| worker 上限 | worker_calls_budget=8 | 属实，独立于步数预算 |
| 超时路径 | timeout_layer 区分 exec/solver_reported | 属实（loop.py `_timeout_layer`)；但 solver 状态解析仅限超时，未做全量分层 → **E1.1 待修** |
| confirm 流程 | 正面陈述会误升 confirmed | 属实，未修 → **E1.3 待修** |
| 进程被杀留账 | run_summary 增量原子写 | B0 airport 超时臂实测属实 |
| 管道掩盖 rc | 分叉实测确认存在 | `_classify_result` 只看裸 rc → **E1.2 待修** |
| 受控集 blind | 有注释泄露 | 属实，未重造 → **E1.4 待修** |

## 5. 硬件实况（R0 前置）

s142:48 核 CPU / 503GB RAM / **无 GPU**(`nvidia-smi` 无驱动）。路径 R 的训练必须依赖外部 GPU 资源（任务书提到的两张 A800 位置待用户确认）。本机可承担：数据生成调度、witness/编译 CPU 执行、API 推理编排、工程侧全部工作。

## 6. 当前开发任务清单（数据边界登记）

开发子集（ORAgentBench 6 题，全部已用于开发，不再自称独立外部测试）:
airport_gate_assignment、bike_share_rebalancing、carbon_aware_compute_scheduling、
cell_tower_coverage_expansion、circular_packaging_replenishment、dynamic_supply_disruption_replanning。
注：dynamic 两臂被 benchmark 自带 initial_plan 门（min_reward 0.3）中止，无有效观测，E-B1 起考虑换题或修门。

受控集：`controlled/`(3 问题 13 制品），blind 模式待重造（E1.4)。

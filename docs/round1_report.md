# ORA 第一轮交付报告（Prompt A）

日期：2026-10-25（工作始于 2026-10-24）。工作区：`/home/hewj13/wm/ora/`。

## 1. 交付清单

- **可运行代码**：`ora_agent/`（stdlib-only：llm.py / loop.py / predict.py / trajectory.py / harbor_agent.py），`scripts/`（analyze_predictions.py、fork_sample.py、freeze_predictions.py），`configs/`（dev_qwen27b.yaml、pilot5_shadow.yaml、pilot6.yaml、fork 候选 JSON）。
- **测试**：`tests/` 22 个离线自测全部通过（`cd /home/hewj13/wm/ora && python3 -m unittest discover -s tests`）。
- **文档**：`docs/fitgap.md`（组件复用决策与版本）、`docs/architecture.md`（架构图与关键决策）、本报告。
- **真实运行产物**：`runs/` 下 oracle 冒烟、6 任务 pilot、分叉采样，全部含 trajectory.jsonl / predictions / outcomes / verifier 结果。

## 2. 环境核实与关键偏差（诚实记录）

| 项 | 结果 |
|---|---|
| GPU | 本机无 GPU；不需要——LLM 走远程服务 |
| 任务书指定的 Qwen 服务 | ModelFactory `service-large-261-1778225138386`（`Qwen38-27B`）**已下线**（全部端点 405 / 门户 HTML）。同平台另两个历史端点同样失效 |
| 实际使用 | 用户现有 Aliyun MaaS（leagent 栈在用），model_id `qwen3.8-27b`，冒烟通过；凭据只走 env（`~/.leagent_env`，不落盘、不进轨迹） |
| ORAgentBench | clone 于 `wm/ora/ORAgentBench`，pinned commit `c9eb9524`（2026-06-26） |
| Harbor | 0.24.0（uv tool install），自定义 agent 走 `import_path` |
| 基础镜像 | `oragentbench-base:py311-scip` 本地构建成功（坑：docker build 内需 `--network host` + 代理 build-arg，宿主代理在 127.0.0.1:7893，桥接网络不可达） |
| 端点能力实测 | Aliyun MaaS qwen3.8-27b **支持原生 OpenAI tool-calling**（最小请求返回合法 tool_calls） |

## 3. 系统（v1）

Harbor 官方 runner + 自定义 `OrAgent`（`ora_agent.harbor_agent:OrAgent`）：qwen3.8-27b actor，单 bash 工具（带 action_kind/rationale 结构化标签），预算熔断（40 步 / 1.2M prompt tokens / 命令 360-600s），预测模块三态 off|shadow|active（active 首轮未接决策）。轨迹按任务书 A8 字段落 jsonl；预测文件 fsync 冻结后才执行动作，结果写独立 outcomes 文件，互不倒填。

修复的关键 bug：同步 LLM 调用直接跑在 asyncio 事件循环上，一次 stalled 请求冻结全部并发 trial（5 任务同时卡 20 分钟）。改为 `asyncio.to_thread` 后恢复。教训已写入代码注释。

## 4. 真实运行结果

### 4.1 oracle 冒烟（无 LLM，验证管线）

IndustryOR_12：feasibility 1.0，quality ~2.0，reward 1.0/2.0，7m11s。管线（环境构建→执行→官方 verifier）完整可用。

### 4.2 开发 pilot（6 任务 × 1 次，qwen3.8-27b，官方 verifier 分数）

| 任务 | 类型 | 模式 | 步数 | LLM tokens(p/c) | 结果 | 可行 | 质量 |
|---|---|---|---|---|---|---|---|
| airport_gate_assignment | 分配 | off | 33 | 807k/102k | finished 38m54s | 1.0 | 0.0 |
| bike_share_rebalancing | 路径 | shadow | 16 | —（超时未汇总） | **AgentTimeoutError 2700s** | 0.0 | 0.0 |
| carbon_aware_compute_scheduling | 调度 | shadow | 17 | 218k/19k | finished | 1.0 | 0.0 |
| cell_tower_coverage_expansion | 覆盖选址 | shadow | 29 | 672k/51k | finished | 1.0 | **0.233** |
| circular_packaging_replenishment | 库存 | shadow | 16 | 198k/13k | finished | 0.0 | 0.0 |
| dynamic_supply_disruption_replanning | 动态重规划(3步) | shadow | 40 | 793k/40k | max_steps 熔断 | 0.0 | 0.0 |

合计：6 任务，可行性 3/6，质量>0 仅 1/6，pass（可行且质量≥0.4）0/6。与官方论文结论一致：feasibility-quality gap 是主要瓶颈；我们 0 pass 说明首个版本还有明显工程与求解质量空间（官方最强配置全量 pass 35.5%，但那是 107 任务全量、含 32 个 easy）。

### 4.3 失败归因（按任务）

- **bike_share_rebalancing**：2700s 官方超时仅完成 16 个动作。瓶颈是 LLM 单轮延迟（MaaS qwen3.8-27b 每轮 1-3 分钟）+ recon 动作过多（12/16）。agent 还没进入有效求解就耗尽时间。
- **circular_packaging_replenishment**：agent 用 gurobipy 风格 API（`pyscipopt.Env()`）写 PySCIPOpt 代码，连续 4 次 repair 才修完 API 误用；最终 submission 被 verifier 判不可行——agent 的自检只验证了 schema 存在性，没有独立可行性检查。
- **dynamic_supply_disruption_replanning**：3 步动态任务在 40 步预算内打满熔断（repair:12、solve:10）。步数预算对多步任务太紧。
- **airport_gate / carbon_aware / cell_tower**：可行但质量低——agent 满足"首个可行解"后缺少有效的解改进循环（官方 instruction 也提示了这一点，但 agent 倾向于早 finish）。

### 4.4 旁路预测（shadow，53 对事前预测-真实结果）

- 预测器：同一 qwen3.8-27b，零样本、未训练（**事前 LLM 预测基线**，非已训练模型）。
- 采样点：solve/validate/repair 类动作；预测 JSON 在执行前 fsync 冻结（文件时间戳 + 输入 sha256），结果独立记录。
- 总体：实际成功率 90.6%，平均预测概率 73.6%，0.5 阈值命中率 92.5%。
- 校准分桶：低桶(0-0.33, n=2)预测 29% 实际 50%；中桶(0.34-0.66, n=18)预测 56.6% 实际 88.9%；高桶(0.67-1, n=33)预测 85.5% 实际 93.9%。**一致性地偏悲观**，小样本下未做校准宣称（符合任务书：LLM 自评不称已校准）。
- 分动作类型：repair(n=25) 实际 84%/命中 88%；solve(n=17) 94%/94%；validate(n=11) 100%/100%。
- 选择偏差清单：乐观但失败 2 例（repair 类 sed/补丁未命中真实根因）；悲观但成功 1 例。unknown 使用率 0%（模型从不说"证据不足"——接口支持但未被使用）。

### 4.5 分叉动作采样（同状态多动作真实结果）

见 `runs/fork_circular_s6/`。状态：circular_packaging seq≤6 真实轨迹回放重建（solve.py 已写入、尚未首次求解；6 条命令全部 rc=0，`docker commit` 快照）。3 个候选动作的事前预测在 05:02 冻结（`frozen_predictions/`，早于任何分叉执行 05:04），随后真实执行：

| 候选 | 动作 | 冻结预测 p | 真实结果 | 判定 |
|---|---|---|---|---|
| 0 | 原样跑 solve.py | 0.55 | rc=1，`AttributeError: module 'pyscipopt' has no attribute 'Env'`（与 pilot seq7 失败逐字相同，验证回放保真） | 方向正确但偏乐观 |
| 1 | 静态诊断（语法+pyscipopt API 符号检查） | 0.80 | rc=0，输出直接暴露两处错误 API 调用行 | 命中 |
| 2 | 补丁修复 Env→Model 后跑 | 0.35 | 补丁生效，但倒在**下一个** API 错误 `getNnodes→getNNodes`（预测的 failure modes 明确包含"其余 API 误用仍在"） | 命中（正确的悲观） |

同状态三动作产生三种不同结果，且预测排序（诊断 0.80 > 原样 0.55 > 补丁 0.35）与真实成败一致——第一份动作条件预测样本表明该基线预测器在此状态上确实区分动作，而非只预测平均未来。样本量=1 个状态 × 3 动作，仅作可行性证据。

## 5. 复跑命令

```bash
cd /home/hewj13/wm/ora
source ~/.leagent_env
export ORA_LLM_BASE_URL="$DISTILL_BASE_URL" ORA_LLM_API_KEY="$DISTILL_API_KEY" ORA_LLM_MODEL="qwen3.8-27b"

# 基础镜像（一次性）
cd ORAgentBench && docker build --network host \
  --build-arg HTTP_PROXY=http://127.0.0.1:7893 --build-arg HTTPS_PROXY=http://127.0.0.1:7893 \
  -f docker/base/Dockerfile -t oragentbench-base:py311-scip . && cd ..

# oracle 冒烟
harbor run -p ORAgentBench/harbor_tasks/IndustryOR_12 -a oracle -o runs --job-name oracle_smoke

# 单任务（预测关闭）
PYTHONPATH=/home/hewj13/wm/ora harbor run -c configs/dev_qwen27b.yaml --job-name <name>

# pilot（5 任务 + shadow 预测）
PYTHONPATH=/home/hewj13/wm/ora harbor run -c configs/pilot5_shadow.yaml

# 预测对照分析
python3 scripts/analyze_predictions.py runs/ora-pilot5-shadow --out runs/ora-pilot5-shadow/prediction_report.json

# 分叉采样（先冻结预测，再真实执行）
python3 scripts/freeze_predictions.py --trajectory <trial>/agent/ora/trajectory.jsonl \
  --upto-seq 6 --candidates configs/fork_circular_s6_candidates.json --workdir runs/fork_circular_s6
python3 scripts/fork_sample.py --task-dir ORAgentBench/harbor_tasks/circular_packaging_replenishment \
  --trajectory <trial>/agent/ora/trajectory.jsonl --upto-seq 6 \
  --candidates configs/fork_circular_s6_candidates.json --workdir runs/fork_circular_s6
```

## 6. 下一轮（Prompt B 方向）候选改动

按证据排序：
1. **recon 成本控制**：agent 花 8-14 步逐个 cat 数据文件。让系统提示要求先 `ls + wc + head` 批量侦察，或提供一次性数据摘要工具。直接针对 bike_share 超时。
2. **独立可行性自检工具**：给 agent 一个"写 checker 脚本"的强约束流程（circular_packaging 不可行却 finish 是直接证据）。
3. **PySCIPOpt API 误用**：/skills/or-pyscipopt 存在但 agent 读得晚；把关键 API 差异（无 Env、getNNodes 命名）前置到 system prompt 或强制首步读 skills。
4. **解质量改进循环**：可行后不停，强制至少一轮质量改进（三个 feasible-but-quality-0 任务的共性）。
5. **多步任务预算**：动态任务按步数 × 阶段分配，而非全局 40 步。
6. 预测侧：当前预测系统性偏悲观且从不用 unknown；分叉样本（§4.5）开始提供同状态多动作区分度证据。预测参与决策（active）尚未试验——接口已留，等更多校准证据。

## 7. 限制与诚实声明

- 6 任务小样本仅用于工程与可行性判断，不代表基准水平；未跑全量 107。
- 预测器是零样本 LLM 基线，不是训练后的模型；"世界模型"研究主张本轮不做。
- shadow 预测与 actor 同模型同服务，预测 token 成本计入 trial usage 但不影响 actor 行为。
- bike_share 的 token 汇总缺失（超时路径未写汇总）——记录为工具缺陷，下轮修。
- 快照分叉只复制文件系统状态，不复制求解器内存（本例无此需求）；回放命令含失败命令的真实状态。

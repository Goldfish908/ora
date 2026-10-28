# ORA v1 架构（Prompt A 首轮）

日期：2026-10-24。工作区：`/home/hewj13/wm/ora/`。

## 角色划分

- Kimi（本 agent）：开发、调试、维护工程；不作为运行时 actor。
- 运行时 OR agent：`qwen3.8-27b` @ 用户现有 Aliyun MaaS（OpenAI 兼容），单 agent，无预设多角色。
- 预测模块：同一模型的事前预测基线（未训练），shadow 模式起步。

## 结构

```
wm/ora/
  ORAgentBench/          # 官方基准，pinned c9eb9524，只读使用（不改其任务包）
  ora_agent/             # 自有包（无第三方依赖，stdlib only，供 harbor 进程 import）
    llm.py               # OpenAI 兼容 chat client（urllib；env: ORA_LLM_BASE_URL/_API_KEY/_MODEL）
    harbor_agent.py      # Harbor BaseAgent 子类 OrAgent：setup+run，bash 工具循环
    loop.py              # 消息循环、预算熔断、动作标签解析
    predict.py           # Predictor 接口 + Qwen 事前预测基线（off|shadow|active）
    trajectory.py        # jsonl 事件流（task/run/state/parent/action hash/usage/预测引用）
  configs/               # harbor job yaml
  docs/                  # fitgap.md、本文件
  runs/                  # harbor jobs 输出
```

## 关键设计决策

1. **Harbor 官方 runner + 自定义 BaseAgent 子类**，不自建 harness。`harbor run -p ORAgentBench/harbor_tasks/<task> -a ora_agent.harbor_agent:OrAgent`，PYTHONPATH 指向 wm/ora。验证走官方 verifier（tests/），agent 上下文只含 instruction + /app 公开材料 + 执行反馈。
2. **单 bash 工具**（mini-swe-agent 风格），在容器 `/app` 内执行；工具参数带 `action_kind`（recon|model|code|solve|validate|repair|other）与 `rationale` 两个结构化标签——只用于统计与预测采样，不限制算法选择。完成信号：agent 调用 `finish` 工具或连续无工具调用。
3. **可执行求解方案**为统一对象：agent 自由生成 formulation/代码/启发式/混合流程，产物落 `/app/submissions/`（task.toml 声明的 artifacts）。
4. **预测模块三态**：`off`（基线，零开销）/ `shadow`（事前预测写入独立不可变文件后再执行，结果另文件记录，互不倒填）/ `active`（首轮仅小型试验，可选）。预测输出含 `unknown` 选项；LLM 自评置信度不宣称已校准。
5. **预测采样点**：默认仅对 `solve|validate|repair` 类动作做 shadow 预测（价值密度高），其余动作旁路记录不预测。
6. **轨迹**：`runs/<job>/<trial>/ora/trajectory.jsonl` + `predictions/` + `outcomes/`。字段按任务书 A8：task_id、split、run_id、state_id、parent_state、actor/predictor 模型与请求配置、action（含 hash）、预测输入 hash/内容/时间戳、工具调用与结果、usage、失败/超时分类。成功与失败轨迹都保留。
7. **信息边界**：tests/、solution/、reference_metrics.json 不进 agent 上下文；online_observation（容器内执行/自检）与 offline_evaluation（harbor verifier 分数）分开记录；held-out 不反馈。
8. **预算**：见 fitgap.md。任务内求解时限沿用官方 300s/次。

## 旧组件处置

- 保留参考：PEARL-4B（solver-in-the-loop 训练参考）、PlanB&B（MILP 后端候选）、旧 GNN/MLP（经验参考）——均不在 v1 依赖中。
- openevolve 已装但首轮不用。
- cobench-lab 沙箱/m2_deploy 求解器契约：被 Harbor 能力覆盖，不重复建设。

## Pilot 任务（开发集，6 个，跨类型）

| 任务 | 类型 |
|---|---|
| airport_gate_assignment | 分配 |
| carbon_aware_compute_scheduling | 调度 |
| bike_share_rebalancing | 路径/再平衡 |
| cell_tower_coverage_expansion | 覆盖/选址 |
| circular_packaging_replenishment | 库存/补货 |
| dynamic_supply_disruption_replanning | 动态重规划 |

选择依据：任务名类型标签互不相同、覆盖 instruction 提到的主要类别；难度以运行时观察为准（首轮不为难度分层做额外分析）。冒烟先用前 2-3 个。

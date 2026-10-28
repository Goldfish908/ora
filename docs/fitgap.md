# Fit-Gap 检查（2026-10-24，精简版）

目的：为 Prompt A 首轮实现做复用决策。检查范围：本机资源、Qwen 服务、ORAgentBench/Harbor、历史工程组件。

## 本机资源

- 无可用 GPU（nvidia-smi 无法连接驱动）。历史上"两块 A800"线索不成立——本机不是 GPU 机器。LLM 推理全部走远程服务。
- CPU 48 核 / 内存 503GB / 磁盘余量 940GB。Docker 可用。
- 网络：经代理可访问 GitHub（ORAgentBench 已 clone 成功）；访问 ModelFactory/Aliyun 需绕过代理（trust_env=False / --noproxy '*'）。

## 模型服务（关键偏差，必须记录）

| 项 | 任务书假设 | 实测 | 决定 |
|---|---|---|---|
| Qwen 27B 服务 | ModelFactory `service-large-261-1778225138386`，model_id `Qwen38-27B`（OpenAI 兼容） | 该端点及同平台另外两个端点全部返回 nginx 405 / GET 返回门户 HTML，服务已下线 | 弃用 |
| 用户现有替代服务 | — | `~/.leagent_env` 中 Aliyun MaaS `https://llm-f1pa4nhg6cxv740w.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`（leagent docker 栈正在使用），`/models` 列出 150+ 模型，含 `qwen3.8-27b` | 运行时 actor/predictor 默认 `qwen3.8-27b`，冒烟通过（content="OK", usage 正常） |
| 凭据 | env var，不落盘 | `DISTILL_API_KEY`/`DISTILL_BASE_URL`（leagent_env，chmod 600）；ModelFactory 旧 key 在 endpoint.env，已无效 | 运行时从 env 读，代码/轨迹不记录 |

注：`qwen3.8-27b` 是 Aliyun MaaS 别名，对应公开模型 Qwen/Qwen3.8-27B；与旧 `Qwen38-27B`（ModelFactory 别名）不是同一部署，模型代次口径一致（Qwen3.8 代 27B）。该替换已按任务书"从实际配置和最小请求确认 model_id"执行。

## 组件复用

| 组件 | 现状 | 复用部分 | 缺口 | 决定 |
|---|---|---|---|---|
| ORAgentBench | 本地无；已 clone 至 `wm/ora/ORAgentBench`，commit `c9eb9524` (2026-06-26) | 107 个 harbor_tasks、instruction、skills（environment/skills 已随任务打包）、官方 verifier（tests/，隐藏） | 无 | 第一主线 |
| Harbor | `uv tool install harbor` → 0.24.0 | 任务环境构建/运行/验证；自定义 agent 走 `AgentConfig.import_path`（`harbor/agents/factory.py`），基类 `harbor/agents/base.py:BaseAgent`（`setup(environment)` + `run(instruction, environment, context)`，`environment.exec` 进容器） | 需自建 BaseAgent 子类 | 官方 runner，复用 |
| 基础镜像 | `oragentbench-base:py311-scip`（python3.11-slim + pyomo/pyscipopt/numpy/pandas/scipy/networkx） | scripts/build_base_image.sh | 构建中（后台） | 官方镜像 |
| agent 循环 | `cobench-lab/driver/miniloop.py`（OpenAI 兼容、usage 记账、jsonl 落盘、可注入 llm_fn） | 循环模式、usage 审计、落盘格式思路 | 工具集硬编码 evaluate_candidate；需通用化为 bash 工具 | 借鉴重写，不直接 import |
| LLM client | `planbb/pbcwm_l3/guidance/llm_guidance.py:HttpChatBackend`（httpx、trust_env=False、usage 返回） | 请求模式、reasoning_effort 教训（旧网关） | 新网关（Aliyun MaaS）无 reasoning_effort 强制要求，实测 max_tokens=512 正常 | 借鉴重写（stdlib urllib，免依赖） |
| 沙箱执行 | `cobench-lab/mcp_server/sandbox.py` | 设计参考 | Harbor 已提供容器隔离执行，重复建设无价值 | 不自建，用 Harbor |
| 求解器后端 | `m2_deploy/optimization_agent/solvers/`（highs/cpsat/scip 契约） | 契约思路 | Harbor 任务镜像内已有 PySCIPOpt/Pyomo；agent 在容器内直接用 | 不自建后端层 |
| 轨迹/产物 | `cobench-lab/cobench/{ledger,trace}.py`、`m2_deploy/optimization_agent/telemetry/transition_logger.py` | 字段设计（run_id/state_id/parent/hash/usage） | 需按任务书 A8 补预测字段 | 自写轻量 jsonl writer |
| 演化框架 | `planbb/openevolve`（完整 repo + oe env 已装 0.3.2） | 后续可选 | 首轮不需要 | 暂缓 |
| mini-swe-agent | 本地无 | Harbor 内置 `MiniSweAgent` 可作对照 agent | — | 不装，自定义 agent 借鉴其单 bash 工具风格 |

## 运行约束（开发默认值，明确记录）

- 每任务：Harbor agent timeout 2700s（task.toml 官方值）；max agent steps 40；累计 prompt tokens 上限 1.2M；单轮 max_tokens 8192。
- pilot：6 个任务 × 1 次尝试，顺序执行（n_concurrent=2）。
- 求解时限：容器内 ORCLAW_SOLVE_TIME_LIMIT_SECONDS=300（官方镜像默认）。

## 开发集 / held-out 划分（首轮）

- 开发 pilot（6 任务，跨类型，见 architecture.md）：仅用于工程与可行性判断。
- 研究 held-out：首轮不跑；后续从剩余 ~101 任务中按类型分层抽取，抽取结果入文档后再运行。
- 隐藏评价（tests/、solution/、reference_metrics.json）不进入 actor/predictor 上下文；官方分数由 Harbor verifier 在提交固定后给出。

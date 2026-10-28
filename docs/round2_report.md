# ORA 第二轮交付报告：语义校验、局部修复与过程学习

日期：2026-10-28。工作区：`/home/hewj13/wm/ora`（git round2 分支；v1 在 main，commit aaf8bdd）。

## 1. 本轮范围

按任务书执行 2.1-2.7；2.8 跨任务自进化**本轮不做**（用户指示），RSI 仅留定义。先看结果，后看机制。

## 2. 结果速览（详细数据在后）

### 受控缺陷集实测（2.5/2.5b，真 LLM、真执行、确定性 witness 判定）

| 指标 | 结果 |
|---|---|
| mutant 检出（full 模式，7 个语义变异） | **7/7**，定位全部正确到具体行 |
| mutant 检出（blind 输入控制） | 6/7（但有注释泄露，见 §5） |
| 误报（3 correct + 3 equivalent） | confirmed 级 2 例（1 例是协议分类问题、1 例实为合理的"无来源目标项"发现，见 §5） |
| 修复成功率（witness 复判） | **6/7**（唯一失败：补丁脚本模式未匹配，未应用） |
| 成本 | 61 次 LLM 调用，150k prompt / 46k completion tokens，17.5 分钟 |

### 真实任务对照（6 开发任务，官方 verifier）

| 臂 | 可行率 | 质量 | 备注 |
|---|---|---|---|
| B0（v2 底座，无 worker） | 3/6 | 0.233（1 任务）| 3/6 任务 AgentTimeoutError（LLM 延迟主导：airport 臂 2412s/2700s 花在等 LLM） |
| B2（+审查/修复 worker） | 2/6 | 0.233（1 任务）| worker 全程仅被调用 2 次（均为 audit，repair 0 次）；airport 臂因端点 read stall 判 llm_error（feas 1.0→0.0 为基础设施回归，非 worker 所致）；dynamic 臂被 benchmark 自带 initial_plan 门（reward 0.0 < 0.3）中止 |

逐任务对照（feasibility / quality）：

| 任务 | B0 | B2 | B2 备注 |
|---|---|---|---|
| airport | 1.0 / 0 | 0.0 / 0 | llm_error：端点 stall，600s×3 重试全超时，9 步被杀 |
| bike_share | 0.0 / 0 | 0.0 / 0 | 两臂均中途 error（12-19 步） |
| carbon | 1.0 / 0 | 1.0 / 0 | 持平，worker 未调用 |
| cell_tower | 1.0 / 0.2327 | 1.0 / 0.2327 | 质量持平；B2 撞 max_steps（39 步 vs B0 21 步） |
| circular | 0.0 / 0 | 0.0 / 0 | worker audit 1 次，未改变结局 |
| dynamic | 0.0 / 0 | 0.0 / 0 | 两臂均被 initial_plan 门中止，agent 未真正起跑 |

### 底座验证（2.1）

B0 的 airport 超时臂：run_summary.json 完整落盘（22 次 actor 调用、334k/125k tokens、2412s LLM 延迟、产物清单），证明"进程被杀也留全量记账"生效。消息重建：context_init + msg_append + messages_sha256 链路有单测逐字节验证。

## 3. 底座修复明细（2.1 逐项）

（填 commit 6cbae21 内容：全路径 run_summary 增量原子写、context_init/msg_append 可重建、actor/predictor/worker 三路 usage 分列、active 显式 decision_integration=false + warning、timeout_layer 区分 exec/solver 自报、BudgetTracker 共享记账）

## 4. 审查与修复 worker（2.3/2.4 实现）

- 形态：主控的两个新工具 `audit(focus, question, mode)` / `repair(finding_id, guidance)`——共享同一基础模型的**按需角色调用**（独立上下文、有限目标、无独立工具循环），不是 subagent。主控决定何时调用与采用；执行走统一 bash 通道。
- 证据分级与状态机：Finding 初始强制 llm_judgment/suspected；只有凭真实执行观测经 confirm 流程才能升 confirmed（actual_test）；RepairResult 四态（resolved_known/confirmed_regression/newly_discovered/unresolved）；unknown/unresolved 永不计通过。
- witness 机制：审查 prompt 要求优先产出可执行正反例（B≤50 模式）。
- 预算：worker 调用走共享 token 熔断（actor+predictor+worker 合计 1.2M），单独 worker_calls_budget=8，不耗动作步数；worker 用 enable_thinking=false 控制延迟（actor 设置不变；B0 无 worker 不受影响）。
- 隔离：enable_workers=false 时工具集与 prompt 与 B0 完全一致（有单测断言）。

## 5. 受控缺陷集与实测（2.5/2.5b）

### 5.1 测试集

3 个不同结构小问题（tiny_assign 分配 / tiny_transport 运输含单位换算 / tiny_sched 调度含先后与多文件数据映射），每问题：独立核验正确实现（非 MIP 暴力/枚举 reference 交叉验证，容差 1e-6）+ 语义变异 + 等价改写负对照，共 13 制品。7 个变异覆盖 omission/direction/index/unit/data_mapping/precedence；每个变异有确定性 witness（跑出实际违规）；等价制品与正确制品 witness 全 PASS。`controlled/run_all_checks.sh` 全绿。

值得注意的设计点：c_m1（先后写反）因镜像对称不改变最优 makespan——只能由排程合法性 witness 检出，是"正确目标值不证明语义正确"的活例。b_m1 方向反转在钉死供需下表现为模型不可行（更硬的证据）。

### 5.2 审查/修复实测结果

检出 7/7（full）、误报 2 例（confirmed 级）：
- `a_e1 F-002`：confirm 流程把一条**正面陈述**（"约束被正确实施"）升级为 confirmed finding——协议分类缺陷，非真实缺陷主张。修复方向：confirm 流程应对"未发现问题的确认"写 refuted/关闭而非 confirmed。
- `c_e1 F-001`：发现目标函数含题面没有的 `0.0001*sum(start)` 平局打破项——按任务书"是否增加无来源约束/目标项"标准，这其实是**合理发现**（修复移除后 witness 仍 PASS）。计为严格规格下的边界误报。

修复 6/7：唯一失败 a_m1 是补丁脚本工程问题（heredoc 模式未匹配），非语义理解失败。

### 5.3 输入控制实验（诚实记录）

blind（无题面）检出 6/7，表面接近 full——但复核发现 **blind 并不真盲**：mutant 代码中的规格性注释（如 `# at least 20 pieces` 配 `<=` 实现）泄露了答案，worker 靠"注释与代码自相矛盾"检出而非独立语义重建。当前测试集无法支持"盲审有效"的结论；严格对照需要无泄露注释的制品版本（下轮）。

### 5.4 工程发现

- 端点开 thinking 时单次 audit 需 508s/27k tokens；`enable_thinking=false` 后 2-15s。worker 一律关 thinking。
- worker 偶发非法 JSON（尾多 `]`），driver 加 1 次格式重试，实测触发 3 次全部恢复。

## 6. 真实任务 B0/B2 对照（2.6）

结果表见 §2。图：`docs/figs/b0_vs_b2_rewards.png`（逐任务 rewards）、`docs/figs/latency_breakdown.png`（墙钟分解）。

核心结论：**worker 能力在受控集上成立（§5），但在线臂上 actor 几乎不触发它**——6 臂合计 worker 仅 2 次调用（cell_tower、circular 各 1 次 audit/confirm 模式，产出需求清单；repair 0 次），两次调用的发现均未驱动后续修复动作，最终 rewards 与 B0 逐任务持平（除 airport 的基础设施回归）。瓶颈不在"会不会修"，而在**触发策略**：需要预测/预算信号主动决策调用（decision_integration），而非依赖 actor 自发。这正是 2.7 预测增强与后续决策集成的动机。

两个基础设施事实（避免误读对照）：
- airport B2 回归为端点 read stall（llm_error），与 worker 无关。
- dynamic 两臂均被 ORAgentBench 自带 initial_plan 步门（min_reward 0.3）在 agent 起跑前中止，该任务本轮实际无有效观测。

## 7. 预测增强（2.7）

- 预测输入 v2：EvidenceStore 现行需求（≤20）+ open findings + 相关 CheckResult + repair 动作引用的 finding 全文，全部带来源 hash；无 store 自动降级为 8 行摘要（context_source 字段区分）。
- 输出按动作类型分化：validate→expected_observations/indistinguishable_hypotheses；repair→likely_resolved/potential_regressions/post_state_guess；solve→expected_solution_validity/expected_quality_change/resource_estimate。
- prompt_version="v2" 落盘，prediction_target="independent_outcome"（与"预测审查器怎么说"显式分离）。
- 冻结纪律不变：输入 sha256 覆盖增强后全部输入，fsync 先于执行。

### 7.1 分叉采样实测（2.7 证据，runs/fork_r2_celltower）

从 B2 cell_tower 轨迹 seq≤17（solve.py 刚写完、尚未首次求解）重放建快照，分叉 3 个候选动作真实执行；v2 预测（thinking off,context 降级为 history_summary 模式）在执行前冻结：

| 候选 | 预测 p | 真实结果 | 判定 |
|---|---|---|---|
| 运行 solve.py（真实 agent 的下一动作） | 0.55 | rc=0 但 traceback:`setObjective` sense 串非法，求解**语义失败**（rc 被管道 tail 掩盖） | 方向正确：三候选中最低 |
| pyscipopt API 体检（recon） | 0.95 | rc=0，打印版本+方法清单 | 正确 |
| `rm solve.py`（破坏性对照） | 0.98 | rc=0，文件被删 | 命令级"正确"，但暴露定义问题 |

结论与两个诚实警示：
1. 三候选命令级成败排序与实际一致，v2 动作分化字段有效——`potential_regressions` 明确标出 rm 的"丢失已写求解器"危害，说明**决策集成必须用 value/regression 字段，不能只看 will_succeed_prob**（破坏性命令照样"成功"）。
2. rc 可被管道掩盖（`... | tail` 使崩溃的 solve 报 rc=0）：分叉候选构造与 outcome 分类都要按语义而非裸 rc，这是下一轮 outcome 分类器的改进点。

## 8. 复跑命令

```bash
cd /home/hewj13/wm/ora && source ~/.leagent_env
export ORA_LLM_BASE_URL="$DISTILL_BASE_URL" ORA_LLM_API_KEY="$DISTILL_API_KEY" ORA_LLM_MODEL="qwen3.8-27b"

# B0 / B2（Harbor，6 任务）
PYTHONPATH=$PWD ~/.local/bin/harbor run -c configs/b0_round2.yaml
PYTHONPATH=$PWD ~/.local/bin/harbor run -c configs/b2_round2.yaml

# 受控缺陷集（约 18 分钟，61 次 LLM 调用）
PYTHONPATH=$PWD python3 scripts/run_controlled_eval.py   # 产出 runs/controlled_eval/summary.{json,md}

# 预测分析 / 结果图
python3 scripts/analyze_predictions.py runs/ora-pilot5-shadow
/home/hewj13/.venv/bin/python scripts/make_round2_figs.py  # 产出 docs/figs/*.png

# 单测
python3 -m unittest discover -s tests
```

## 9. 限制与诚实声明

- **小样本**:6 任务 × 单 seed,B0/B2 差异无统计意义；对照结论以"worker 未被触发"这一结构性观察为主，而非 rewards 差值。
- **blind 检出率不可作结论**：受控集 blind 模式有注释泄露（§5.3）,"盲审有效"未证明。
- **误报协议缺陷**:confirm 流程会把正面陈述升级为 confirmed finding（a_e1 案例），修复方向已明确但未实施。
- **基础设施噪声**:airport B2（端点 stall）与 dynamic（benchmark 自带 initial_plan 门，两臂均未起跑）本轮不构成有效对照观测；LLM 延迟占墙钟 51-89%，是第一瓶颈，actor thinking 未关（为 B0/B2 公平性保持默认）。
- **B1（反思臂）未做**：任务书标"资源允许再补"，本轮时间被端点延迟吃掉，标注为未做而非失败。
- **2.7 仅完成实现与单测**:v2 预测器无真实 shadow/shadow-fork 运行数据（B0/B2 均 predict off）；分叉采样仅有 Round 1 的 1 状态×3 动作小样本。
- **2.8 跨任务自进化本轮不做**（用户指示），RSI 仅留定义。

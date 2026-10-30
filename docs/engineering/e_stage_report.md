# 工程阶段报告（路径 E,B0 → E-B1-off-big)

日期：2026-10-29。范围：任务书 v1.1 路径 E 的对照实验组（ORAgentBench 6 题开发集）+ E1/E2 工程改动的实测效果。**全部为单轮跑分，采样方差未控制**——结论按 v1.1 §7/§14.7 的口径写，需要重复处已标注。

图:`docs/figs/engineering/`(arms_scores.png / thinking_latency.png / final_status_attribution.png，脚本 `scripts/make_engineering_figs.py`，可重跑）。

## 1. 五臂对照总表

| 臂 | 配置要点 | 可行 | quality 和 | 墙钟 | worker 调用 |
|---|---|---|---|---|---|
| B0(round2) | worker 基线 | 3/6 | 0.233 | ~50min | 2 |
| E-B1 | B0 + E1 修复，worker 关 | 3/6 | **2.0** | 49min | 2 |
| E-B2 | E-B1 + 触发器（E2) | 2/6 | 0.0 | 49min | **8** |
| E-B1-off | E-B1 + actor thinking 关 | 2/6 | 0.0 | **29min** | 2 |
| E-B1-off-big(阿里云，污染） | off + max_steps 120 + 2M token | 1/6 | 0.45 | 41min | — |
| **内网同平台对照**（下行起） | | | | | |
| E-B1-v2（内网） | B0 + E1,worker 关，on + reasoning_effort=medium | **3/6** | **2.0** | 43min | 2 |
| E-B1-off-big-v3（内网） | off + max_steps 120 + 2M token | 2/6 | 0.233 | 47min | — |

内网逐题明细(feasibility/quality,on = E-B1-v2,off = off-big-v3):

| 题 | on | off | 说明 |
|---|---|---|---|
| airport | 0/0 | **1.0/0.0** | off 反而可行 |
| carbon | **1.0/0.0** | 0/0 missing_solution | on 胜 |
| bike_share | 0/0 | 0/0 | 都打不出 |
| cell_tower | 1.0/0.0 | **1.0/0.233** | off 反而拿到 quality |
| circular | **1.0/2.0** | 0/0 浅 finish | on 胜，且是唯一非零 quality 来源 |
| dynamic | 门拦 | 门拦 | 与 thinking 无关，initial_plan 门两种模式都拦 |

**同平台结论（单轮）**:on 在总分上占优（2.0 vs 0.233)，但优势全部来自 circular 一题；按题面看 on/off 各赢两题，差异方向不一致。**这与 §2.1 一致：单轮 6 题不足以冻结 thinking 默认值，v1.1 要求代表题型重复后再定。** on 模式跨平台复现性注记：E-B1 在阿里云与内网跑出完全相同的 3/6、2.0(circular 满分复现）。

逐题明细(feasibility/quality):

| 题 | B0 | E-B1 | E-B2 | E-B1-off |
|---|---|---|---|---|
| airport | 1.0/0.0 | 0/0 超时 | 0/0 超时 | 0/0 max_steps |
| carbon | 1.0/0.0 | 1.0/0.0 | 1.0/0.0 | 1.0/0.0 |
| bike_share | 0/0 | 0/0 | 0/0 超时 | 0/0 token 耗尽 |
| cell_tower | 1.0/0.233 | 1.0/0.0 | 1.0/0.0 | 1.0/0.0 |
| circular | 0/0 | **1.0/2.0** | 0/0 | 0/0 |
| dynamic | 0/0 门拦 | 0/0 门拦 | 0/0 门拦 | 0/0 门拦 |

## 2. 关键结论

### 2.1 单点跑分不可比（实证）

cell_tower:同样的臂（E-B1 vs B0 同配置思路）,quality 0.233 → 0.0，原因是可行解利润从低于参考 251 元退到 1225 元——该题质量刻度宽度只有 98.85（参考值 × mip_gap 回退 0.0005)，每差 ~99 元扣 1.0 分。circular:B0 0/0 → E-B1 满分 → E-B2 又 0/0。**任何两臂对比必须多 seed/重复，单轮差异不作结论依据。**

### 2.2 thinking 是第一预算变量（v1.1 §7 筛查第一轮）

on → off 的每次调用延迟：airport 88.6→14.4s(6.2×)、bike 123.3→20.8s(5.9×)、circular 3.4×、cell_tower 2.5×、carbon 2.1×。整轮墙钟 49→29min,**超时死亡 2→0**。

但失败模式迁移而非消失：

- airport：墙钟（13 步撞 2700s)→ **max_steps=40 撞顶**(off 步便宜 6 倍，40 步按 on 校准，属配置混淆）;
- bike_share：墙钟 → **token 预算耗尽**（卡在"约束组单独跑也不可行"的调试循环，38 步烧 1.25M);
- circular:on 满分 → off **10 步浅尝 finish 提交不可行解**。

第一轮不能证明非劣（v1.1 明言单次不足以证明）。第二轮（off-big：步数 120、token 2M）修正配置混淆后重测，结果见 §4。

### 2.3 触发器（E2)：机制有效，发现真漏洞

E-B2 中 `post_first_solution` / `pre_finish_audit` 按设计触发（2 次 pre_finish 弹跳，worker 调用 2→8)。但 circular 暴露设计漏洞：actor 自审后 audit 明确发现 F1,**22 秒后照常 finish**，提交了 208 个执行错误的不可行制品——触发器只查"审没审"，不查"审出的 finding 解没解决"。

已修（E2.1,commit 6ef966b):finish 时存在未解决 finding（含只在 repair 轮次 newly_discovered 出现、未落成 Finding 记录的 id)→ 弹跳一次，列出待决清单，不耗 worker 预算。64/64 单测绿。

### 2.4 失败归因全景（§14.5 分类）

E-B2 的 4 个 0/0:**2 个墙钟、1 个流程漏洞（circular)、1 个 benchmark 门（dynamic)**——没有一个是纯"模型不会做题"。这对研究线的含义：工程预算与流程因素会先淹没能力信号，motivation 测量必须用单次生成（M1/M2 管线）而非 agent 循环成绩。

## 3. 成本账本

| 臂 | 总 token(actor) | 墙钟 | 说明 |
|---|---|---|---|
| B0 | （见 round2 报告） | ~50min | |
| E-B1 | | 49min | thinking on |
| E-B2 | | 49min | +8 worker 调用 |
| E-B1-off | bike 单题即 1.25M(超限） | 29min | thinking off |
| E-B1-off-big | | 41min | 阿里云轮，3/6 题被 llm_error 污染 |
| E-B1-off-big-v3 | | 47min | 内网端点，干净 |

LLM 延迟占墙钟 51–89%(round2 结论，本轮一致）:actor thinking 是成本主体。

## 4. E-B1-off-big 与 M1 先导（2026-10-29 晚）

### 4.1 E-B1-off-big(off + max_steps 120 + token 2M，墙钟 41min)

| 题 | 结果 | 终止状态 |
|---|---|---|
| carbon | **1.0/0.45**(off 模式首个非零 quality) | finished,15 步 |
| circular | 0/0 | finished,18 步（仍偏浅） |
| airport | 0/0 | **llm_error**,29 步 |
| bike_share | 0/0 | **llm_error**,59 步 |
| cell_tower | 0/0 | **llm_error**,31 步 |
| dynamic | 门拦 | — |

**本轮被端点故障污染**:3/6 题死于 MaaS read stall → llm_error（随后端点整体转为 403 AccessDenied.Unpurchased，见 §4.3)，不是任务失败。airport 在 29 步内未超时、步数余量充足，预算修正确认有效，但质量结论仍需重跑。

### 4.2 M1 pilot 首批（RetailOpt-190,f1_52_weeks_v0)

- thinking on:LLM 读取超时（30 分钟，端点故障期）;
- thinking off:94.7s 返回 12,283 字符代码，但输出被 ```python fence 包裹且 fence 未闭合（max_tokens 截断）→ 第一版 extract_code 未容错，SyntaxError。已修（未闭合 fence 回退剥离），重跑待端点恢复。

### 4.3 外部阻塞：MaaS 权限中断

2026-10-29 ~18:40 起，qwen3.8-27b 与 cmaas-qwen3.8-flash 均返回 `AccessDenied.Unpurchased`(403)。所有 LLM 依赖工作（M1 pilot、off-big 重跑、E-B2-off）暂停，待账号权限恢复。**期间可推进的零 LLM 工作**:M2 生成器设计、连接算子库、E 线代码改进、文档。

### 4.4 附：MaaS 上下文上限实测

输入硬上限 **983,616 token(960K)**，服务端 400 错误原文确认；380k 探测正常作答。原生 256K，托管开了扩展窗口。我们最大单调用 ~32k，余量 30 倍——上下文不再是需要测量的变量。

### 4.5 E-B1-off-big-v3：内网端点干净重跑（2026-10-29 夜，墙钟 47min，0 llm_error)

阿里云 403 后切换到内网自托管 vLLM(`Qwen3_8-27B`,`max_model_len` 262144)。两个平台行为差异已适配：关 thinking 必须嵌套 `chat_template_kwargs: {enable_thinking: false}`（顶层写法被内网静默忽略）；内网默认 `reasoning_effort=xhigh`,on 模式需显式设 `medium` 否则单题烧满 32k reasoning token。

| 题 | feas/quality | 终止状态 | 备注 |
|---|---|---|---|
| airport | **1.0/0.0** | finished,17 步 | 可行，score 69370 |
| cell_tower | **1.0/0.233** | finished,26 步 | 利润距参考上界仅 ~250 元 |
| carbon | 0/0 | finished,65 步 | **missing_solution，相对阿里云轮的 1.0/0.45 回退** |
| bike_share | 0/0 | finished,47 步 | missing_solution，配额修正后不再撞限但仍未产出 |
| circular | 0/0 | finished,18 步 | 又交不可行解（verifier 240 个评估错误）;**trajectory 里无任何 pre_finish 触发**——E-B1 系 worker 关闭，E2.1 规则 C 没有 findings 可查，该臂本来就无审计，不是 E2.1 失效；E2.1 的正确检验臂是 E-B2-off |
| dynamic | 门拦 | — | initial_plan reward 0.0 < 0.3,off 模式下首轮规划拿不到分，修 gate 的优先级上升 |

**结论（单轮）**：配额修正有效（无超时、无 token 耗尽、无 llm_error)，但 off 模式质量仍不稳——carbon 从阿里云轮的 1.0/0.45 退回 missing_solution，说明 off 模式在难题上的产出方差大；feas 2/6 与 on 基线持平但题面不重。平台已换，与历史臂的延迟对比失效，质量结论需 E-B1(on）内网重跑后同平台对照。

### 4.6 M1 pilot v4:4 实例 × on/off（内网端点）

7/8 crash，归因清晰且**都不是"推理不会"**:

| 失败模式 | 频次 | 说明 |
|---|---|---|
| 数据誊抄错误 | 4/4(on 模式全灭） | 模型把 prompt 内嵌 JSON 抄成 Python 语法（`[800]*52`),`json.loads` 炸 |
| pyscipopt API 误用 | 3/4(off 模式） | 如 `quicksum` 传 list；我们把 gurobipy 改写成 SCIP 引入的接口噪声 |
| 假成功 | 1/8 | off/high_waste obj=243,884 比已证最优 378,951 好 36% → 必然漏约束；`better_than_reference` 必须触发约束审计，不能算成功 |

对 M1 设计的直接修正：①主测量改用 `prompt_schema` 模式或数据文件化，剥离誊抄；②prompt 加 pyscipopt 惯用法片段；③grade 体系加约束完整性审计。誊抄错误作为独立大头失败模式坐实，写入 motivation 验证发现。

### 4.7 dynamic 题"门拦"根因查明：benchmark 题面欠规约（2026-10-30)

所有臂的 dynamic 都在 initial_plan 拿 0.0 被 min_reward=0.3 门拦。根因**不是** off 模式规划差：verifier(`steps/initial_plan/tests/evaluate_solution.py`）要求 `variable` 列精确取 9 个词表值（`produce_regular`、`ship_plant_dc` 等），但 agent 可见的环境里（PROBLEM_STATEMENT.md、solution_template.csv、skills）**任何地方都没有这个词表**——题面只用散文描述变量类型。agent 写了 `production_regular`,1146 行全部 unknown variable。**与 R 线发现 F3（受控集题面欠规约）同类，互为印证。**

修复：PROBLEM_STATEMENT.md 的 CSV 段补齐精确词表（本地 ORAgentBench 副本，gitignored，本报告为变更记录）。验证跑：`configs/engineering/e_b1_dynfix.yaml`（单题，thinking on)。

### 4.8 dynamic 题四轮 dynfix 全记录：题面修复生效，瓶颈转移到 actor 自验证（2026-10-30)

对 dynamic 单题连续四轮验证（均 thinking on，内网 27B)，失败性质逐轮转移：

| 轮 | 改动 | 结果 | 失败性质 |
|---|---|---|---|
| dynfix1 | 补变量词表 | 0.0,verifier 正常解析但 115 条全在库存下限 | **题面欠规约第二层**:verifier 有三条硬约束（每 DC 每产品库存下限=safety+0.18×下周区域需求；常规物料×robust 折扣；最低服务率）题面未写，模型全按软约束处理 |
| dynfix2 | 题面补"Hard Requirements"一节（三条全列，source/agent_envs 留档版同步） | 0.0,169 需求平衡不符 | 模型写对了（model_initial.md 约束 7 即需求平衡），但 CSV 与模型矛盾，agent 自验发现"两种求和矛盾"，debug 到 39/40 步预算耗尽 |
| dynfix3 | max_steps 40→60,token 1.2M→2.4M | 0.0,60/60 步耗尽 | 第 60 步定位根因（非适格工厂-产品对变量未禁用→幻影产量），修复写进 solve_initial.py 但**没来得及重跑生成 CSV** |
| dynfix4 | max_steps→100,token→4M | 0.0,**但只用 34 步**——agent 自认完成主动收工 | 全新 run 重新犯同一类 bug(PL_EAST 运 P_COLD 但零生产），且这轮**自验全部通过**（"All artifacts are complete and validated")，实际 32 处违规 |

**结论**：题面修复彻底生效（两轮不同的违规构成都落在 verifier 真实规则上）；预算不再是约束（dynfix4 只用 1/3 步数）;**瓶颈是 27B actor 的自验证可靠性**——会重复犯同类建模 bug，且自验查不出来。这正是 E2.1 审计机制的靶心场景。

### 4.9 E-B2-off 首轮（E2.1 检验臂）：触发器会发，但 worker 读错产物文件名（2026-10-30)

`e_b2_off`（触发器+worker 开、thinking off、40 步/1.2M，与 E-B1 各臂同预算）首轮：1/6 feasible(cell_tower,quality 0.233),5 题 0.0。逐题解剖：

- **触发器有效性确认**:cell_tower(4 次 worker 调用）和 circular(3 次）的审计 worker 给出了实质语义发现（如"目标函数漏了 critical-facility 服务分量""韧性信道规则未实现")——机制在简单题上工作正常。
- **dynamic**:post_first_solution_audit 触发，worker 正确抽取 R1-R3 硬性要求（证明 §4.8 的题面补丁对 worker 也可见），但随后报假 finding"model.md 和 solve.py 缺失"——`workers.py` 硬编码 `cat /app/submissions/model.md`，而 benchmark 产物是步级命名（`model_initial.md`/`solve_initial.py`)。假 finding 浪费 actor 步数，trial 32 分钟后被 harbor 以 CancelledError 中止。
- **3 题（airport/bike/carbon)40 步耗尽、0 次 worker 调用**:off 模式 actor 从未产出首个求解器 incumbent，触发器 A（首解审计）无从触发，机制在这些题上完全惰性。

修复：`workers.py` 上下文采集改为 glob(`model*.md`/`solve*.py`),worker prompt 与测试同步更新（tests 65/65 绿）。重跑 `e_b2_off2` 进行中。**待回答**:worker 审计能否抓住 dynfix4 暴露的"幻影运输"类违规——若能，E2.1 的价值主张成立；若不能，需要 proposed_checks 真正被执行（当前 finding 状态止步于 llm_judgment/suspected)。

## 5. 后续动作

1. thinking 默认值：待 off-big + 代表题重复后按 v1.1 质量容忍度冻结；
2. ~~dynamic 题：修 benchmark 的 initial_plan 门~~ → 已查明为题面欠规约并补齐词表（§4.7)，验证中；
3. E-B2-off（触发器 × thinking off）作为模式一致的触发器效益对照（配置已建：configs/engineering/e_b2_off.yaml);
4. 路径 I 预备：M1 pilot 管线（`scripts/m1_pilot.py`）已是单次生成测量骨架，M2 受控集生成器复用同一执行/评分壳。

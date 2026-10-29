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
| E-B1-off-big | off + max_steps 120 + 2M token | （跑完填） | | | |

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
| E-B1-off-big | | | （跑完填） |

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

## 5. 后续动作

1. thinking 默认值：待 off-big + 代表题重复后按 v1.1 质量容忍度冻结；
2. dynamic 题：修 benchmark 的 initial_plan 门（min_reward 0.3）或换题；
3. E-B2-off（触发器 × thinking off）作为模式一致的触发器效益对照；
4. 路径 I 预备：M1 pilot 管线（`scripts/m1_pilot.py`）已是单次生成测量骨架，M2 受控集生成器复用同一执行/评分壳。

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

## 4. E-B1-off-big 与 M1 先导（补充节，跑完填）

（待填：off-big 六题结果、airport 是否在 120 步内收敛、circular 是否仍浅 finish;M1 pilot 前 2 实例 on/off 的执行与 grade。)

## 5. 后续动作

1. thinking 默认值：待 off-big + 代表题重复后按 v1.1 质量容忍度冻结；
2. dynamic 题：修 benchmark 的 initial_plan 门（min_reward 0.3）或换题；
3. E-B2-off（触发器 × thinking off）作为模式一致的触发器效益对照；
4. 路径 I 预备：M1 pilot 管线（`scripts/m1_pilot.py`）已是单次生成测量骨架，M2 受控集生成器复用同一执行/评分壳。

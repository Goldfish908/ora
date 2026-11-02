# ReLoop 同模型对照(Qwen3_8-27B × RetailOpt-190)

日期:2026-11-02。对照对象:ReLoop(junbolian/ReLoop,MIT,NeurIPS 2025),
其论文报告 RetailOpt-190 上 SOTA 为 Claude Opus 4.6 的 31.1%。本次实验把
ReLoop 完整管线移植到与我们相同的模型(内网 Qwen3_8-27B)与相同的开源
求解器(PySCIPOpt/SCIP)上,实现同模型、同数据集、同求解器的严格对照。

## 1. 移植方法(reloop_ext 仓库,分支 `scip-qwen27b`)

官方管线绑死 Gurobi,本地克隆 `/home/hewj13/wm/reloop_ext`(保留 MIT 归属)
做最小侵入改写:

| 文件 | 改动 |
|---|---|
| `reloop/prompts.py` | 5 处生成提示词的 gurobipy 契约 → PySCIPOpt(`m = Model()`、`m.hideOutput()`、`limits/time=60`、`status: {m.getStatus()}` 字符串契约;修复 `.format()` 花括号转义) |
| `reloop/executor.py` | 状态解析兼容 SCIP 字符串状态;IIS 诊断对 SCIP 自动跳过(SCIP 无 IIS,降级为 traceback+状态) |
| `reloop/verification.py` | 执行器超时 60s→120s(给 SCIP 内部 60s 限时留余量) |
| `reloop/generation.py` | `_validate_code` 的 gurobipy 模式 → pyscipopt |
| `run_ablation.py` | `UsageLLM` 加 `httpx verify=False` + thinking 开关(`RELOOP_THINKING`);新增 `adapt_problem_text()`:RetailOpt-190 题面**内嵌** GurobiPy [OUTPUT FORMAT] 契约,正则改写为 SCIP 版(与 m1_pilot 的 `adapt_prompt` 同法) |

数据集用官方自带 `data/RetailOpt-190.jsonl`(190 题,与我们
`data/m1_retailopt/retailopt_190.jsonl` 同源)。运行:
`bash run_qwen27b_arms.sh`(workers=20,温度 0,thinking off)。

## 2. 四臂消融结果(官方 run_ablation.py 口径)

| 臂 | 配置 | 可执行 | Acc@1e-4 | Acc@1e-2 | 平均耗时/题 | 平均 tokens/题 |
|---|---|---|---|---|---|---|
| R0 | direct 直生成,无验证 | 0.5% (1/190) | 0.0% | 0.0% | 109s | 10.0k |
| R1 | CoT 结构化生成,无验证 | 82.6% (157/190) | 1.6% (3) | 3.7% (7) | 125s | 16.6k |
| R2 | CoT + L1 执行恢复环(≤3 次重生成+修复) | 92.6% (176/190) | 2.6% (5) | 5.3% (10) | 136s | 21.3k |
| R3 | 全量 ReLoop(+L2 扰动测试 CPT/OPT) | 91.6% (174/190) | 2.6% (5) | 3.7% (7) | 214s | 47.1k |

读法:
- **direct 臂全军覆没**(0.5% 可执行):LLM 手抄题面内嵌 JSON 数据时产生
  `[99999.0]*52` 之类 Python 表达式混入 JSON 字符串,数据转抄失败——这正是
  ReLoop CoT 抽取路径要消除的模式,也印证我们 crash 挖掘里"数据契约"类的存在。
- **L1 执行恢复有效但微弱**:可执行率 +10pp,准确率 3.7%→5.3%(1e-2 档)。
- **L2 扰动测试零增益甚至负增益**(5.3%→3.7%,耗时 +57%、tokens +121%):
  CPT/OPT 的"行为一致性"检查在这个难度上既不增量检出错误,反而诱发过度修复。
- **与已发表 SOTA(31.1%,Claude Opus 4.6)的差距主要是模型能力差距**;
  在同模型 Qwen3_8-27B 上 ReLoop 全管线只有 2.6%~5.3%。

## 3. 与我们管线的对照(同模型、同数据集)

| 管线 | 预算 | 成功口径 | 成功率 |
|---|---|---|---|
| ReLoop R1(CoT 单次) | 1 次生成 | 目标值匹配 @1e-2 | 3.7% (7/190) |
| **我们 pilot(pass@1)** | 1 次生成 | witness 可行 + 目标值 match/better | **6.8% (13/190)** |
| ReLoop R2(CoT+L1 环) | ≤3 重生成 + ≤3 修复 | 目标值匹配 @1e-2 | 5.3% (10/190) |
| ReLoop R3(全量) | 同上 + CPT/OPT | 目标值匹配 @1e-2 | 3.7% (7/190) |
| **我们 B' 臂(guard v0.1 + 闸门 + witness 环)** | ≤3 轮(闸门/guard 重写不求解) | witness 可行 + match/better | **47.4% (90/190)** |

口径说明:我们的成功口径**更严**(除目标值匹配外还要求 witness 确定性
重算可行,排除幻影);ReLoop 口径只看目标值容差。预算两侧均为"最多 3 轮
修复",量级相当。同模型下同数据集,我们的 harness(闸门+guard+witness)
比 ReLoop 全管线高 **~44 个百分点**。

## 4. 关键发现:幻影的跨管线复现(动机命题的独立证据)

比对 ReLoop R1 与我们 pilot(on 模式)逐题目标值:两边都出解的 54 题中,
**11 题目标值逐位完全一致(差 < 1e-6),且 11/11 全部被 witness 判
infeasible——全部是幻影**。示例:

| scenario_id | 共同幻影值 | 参照值 |
|---|---|---|
| retail_f1_52_weeks_v0 | 940962.0 | 1006432.0 |
| retail_f2_no_substitution_v0 | 313481.5 | — |
| retail_f7_budget_limit_v0 | 460957.17 | — |

两条独立管线(独立提示词、独立生成路径)在同一模型上收敛到**逐位相同
的错误解**,说明幻影不是随机失误,而是被题目的隐藏约定**系统性诱导**的
(C-INIT 类:初始库存语义未言明,模型默认不钉初始库存,求解器"白嫖"
期初库存)。其中 2 例(retail_f5_storage_overflow_v1/v2)幻影目标值甚至
与参照值容差内"match"——**只看目标值会判对,witness 重算判错**,是
motivation F2(目标值匹配产生假成功)的直接实例。

推论:ReLoop 的 consistency-only 检查(CPT/OPT 扰动响应、执行反馈)对此类
自洽的语义误解存在系统性盲区——模型不是"不一致",是忠实地解了另一道题。
抓它需要显式的语义来源:题面台账(闸门)或解的确定性重算(witness)。

## 5. 结论

1. 同模型严格对照成立:我们的 harness(47.4%)≫ ReLoop 全管线(3.7%)。
2. ReLoop 的验证层在弱模型上不迁移:L1 微增益、L2 负增益,验证预算
   (tokens +121%)打了水漂。
3. 幻影跨管线逐位复现(11/11 infeasible),为"隐藏约定诱导的系统性语义
   错误需要显式语义校验"提供独立证据。
4. 后续:ReLoop 的 CPT/OPT 思想(扰动测试)可作为 witness 的 GT-free
   补充层评估,但不应替代语义校验。

数据:`reloop_ext/experiment_results/retailopt_qwen27b/r{0..3}_*/`
(ablation_report.csv + chat_logs.jsonl)。

# PEARL-4B × RetailOpt heldout90 评估记录(2026-11-05)

## 目的

检验 PEARL-4B(Qwen3-4B-Instruct-2507 + GRPO 建模微调,训练集 OptMATH-1100,
求解器在环协议 `<code>→<interpreter>→<answer>`,奖励=目标值匹配)能否作为
RetailOpt 的建模器;以及 harness 适配(data.json 预加载)能否剥离誊抄层。

## 协议

- runner:`scripts/pearl_loop.py`,系统提示词逐字复刻 GRPO 训练分布
  (来源:way2m `pearl_smoke/smoke_train.log` 首条 rollout 样本)。
- 端点:平台托管 `service-large-1178-1792914510594`(pearl-4b,256k ctx)。
- 执行:s142 本地 pyomo+GLPK,600s/次,相同代码熔断,≤12 轮。
- 数据:`data/m1_retailopt/f5f8_heldout90.jsonl`(F5-F8 留出 90 题)。
- 污染检查:GRPO 任务集全库 grep `retail_f`/`retailopt` 零命中 → 无泄题。

## 结果(90 题/臂)

| 臂 | answer 产出 | 求解 optimal | 目标值匹配(1e-2) | 平均轮数 |
|---|---|---|---|---|
| A 原生(数据内嵌题面) | 3/90 (3.3%) | 2/90 | **1/90 (1.1%)** | 4.0 |
| B'(数据剥离+强制 data.json) | 3/90 (3.3%) | 3/90 | **0/90** | 5.6 |

分族:A 臂仅 F5 有 2 题 optimal(其中 1 题匹配,且是 impossible_demand
的目标值=0 特殊题);F6/F7/F8 两臂全零。
终止结构(A):熔断 82、无代码 5、answer 3。B' 中模型从不 json.load,
而是虚构数据结构硬编码(KeyError 依旧)——文件加载在其训练分布之外。

## 结论

1. **PEARL-4B 在 RetailOpt 规模(780+ 变量、52 期)上可执行率≈0**,
   失败集中在誊抄层/代码层(KeyError、Pyomo API),从未到达语义层。
2. **harness 分布锁定**:剥离数据块+强制文件加载并未让它学会读文件;
   接口约定在训练分布之外时,prompt 补丁无效。→ 模型须在目标 harness
   内训练,或评测必须复刻训练 harness。
3. 对本项目的含义:PEARL 不适合直接做 RetailOpt 主力建模器;其价值是
   作为"结果奖励 RL 路线"的对照证据(目标值奖励在难题上连执行层都
   建立不了)。witness/JEV 主线继续以 Qwen3.8-27B 为基座。
4. 若未来要给 PEARL 类小模型接语义层:须在环内做第二轮训练
   (reward = 目标值匹配 + witness 可行),这是后续候选实验。

产物:`work/pearl_pilot/h90_armA_embedded.jsonl`、`h90_armBp_strip.jsonl`
(含完整轨迹)。

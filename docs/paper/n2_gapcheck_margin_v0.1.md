# N2: gapcheck60 阈值确认实验 — 结果与发现

日期: 2026-11-04
状态: 完成
脚本: scripts/d2_author_retail.py, scripts/d2_gap_margin.py
数据: runs/d2_authoring_gap/(60 题规则)+ gap_cells.jsonl(134 细胞: 91 错 / 36 对 / 其余无规则)
Commit: (见 git log)

## 目的

D2.1 在 IndustryOR 240 细胞上发现 "anchor 违例幅度 ≥15%" 阈值可把 FP 12.9%→4.7%。
但该阈值是在测试集上选的,存在选择偏差。本实验在独立集合(RetailOpt gapcheck60,
F1-F4 的 v1/v2/v3 变体)上确认该阈值。

## 做法

1. d2_author_retail.py: 同一套模板-槽位自标定撰写流程,对 gapcheck60 题面盲写规则
   (不看任何模型输出),57/60 题成功,共产出 193 条标定通过规则
   (sense_direction 51, constant_fidelity 66, phantom_resource 50, anchor_bound 13,
   objective_range 3)。
2. d2_gap_margin.py: 规则应用到 134 个已有 witness 标签的细胞,扫描 margin ∈
   {0,5,10,15,20,30}% 的 det/FP/J。

## 结果

| 配置 | det | FP | Youden J |
|---|---|---|---|
| 全部规则 | 63.7% | 72.2% | **-0.085** |
| 剔除 constant_fidelity | 5.5% | 2.8% | +0.027 |
| 仅 anchor_bound | 3.3% | 0.0% | +0.033 |

margin 阈值扫描: 从 0% 到 30%,FP 恒为 72.2%(26/36)——**阈值完全无效**。

## 三个发现(按重要性)

### 1. margin 阈值被否决,且 FP 的根源不是 margin

gapcheck60 的全部 FP 里,anchor_bound 只贡献 1 条(margin 0.65,即便 15% 阈值也
拦不住);37 条 FP 全部来自 constant_fidelity。IndustryOR 上"FP 集中在小 margin
锚界"的现象在 RetailOpt 不存在——**阈值治理的是错误的问题**。

### 2. constant_fidelity 是代码风格脆弱的模板

该模板检查"题目常数是否以字面量出现在代码里"。RetailOpt harness 的 prompt 要求
代码 `json.loads(open('data.json'))` 读数据——正确代码合法地不含任何字面常数,
于是 26/36 个正确细胞被误杀(FP 72%);同时它又确实是检出主力(55/91 错误细胞)。
同一个模板在 IndustryOR(代码内嵌字面量)上低 FP,在 RetailOpt 上不可用。
**模板适用性必须按数据集代码风格门控**,这与 margin 无关。

### 3. 文本匹配类模板结构性抓不到 RetailOpt 的主错误模式

phantom_resource 撰写了 50 条(覆盖大多数题),对错误细胞 **0 次命中**:
它 grep `initial_inventory`/`I0` 等标识符,而真实幻影库存是**缺失**的约束
(`I[p,l,1,r]==0` 没写),代码里根本没有可 grep 的字符串。遗漏型错误
(error of omission)只有数值/语义级检查(anchor、witness、判官)能抓,
文本级模板在原理上不能。这直接支撑 J1 判官与 witness 路线的必要性。

## 结论

- "15% margin 阈值"**不采用**(在独立集合上被否决)。
- anchor_bound 在两个数据集上都保持近零 FP(0-3%),是唯一跨数据集行为一致的
  模板,但 RetailOpt 上覆盖不足(13/57 题),需要强制撰写策略进一步提升实例化率。
- 规则层在 RetailOpt 上的现实上界:低 FP 配置下 det 仅 ~5%;要提升检出必须靠
  数值/语义/判官层,而不是更多文本模板。

## 后续

- constant_fidelity 修复方向(备选): (a) 检测 prompt 是否要求读数据文件,若是则
  禁用该模板; (b) 把 data.json 内容纳入规则可见输入。记入 backlog。
- anchor_bound 实例化率提升(13/57 → 目标 >40/57): 提示词已要求强制尝试,
  需诊断 LLM 拒绝原因(not_used 字段)。记入 N4 后的规则层迭代。

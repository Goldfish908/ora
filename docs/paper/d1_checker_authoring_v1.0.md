# D1: Checker-Authoring 冷启动实验 v1.0(含结果)

日期:2026-11-04。状态:**实验完成,结论明确(未过预注册线,分层诊断有效,D2 方向确定)**。

## 1. 问题

witness 语义规则目前是手工按数据集/题族定制的,换数据集清零(阶段 C 实测:
IndustryOR 上 21–30% 出解细胞是幻影,无任何在线机制能发现)。已有工作
(ReLoop 扰动测试、Li & Hai 的 falsification 电池、ORSMT)都不能覆盖
"幻影组件/错误取值"类错误,也没有自动生产过程。

**D1 回答:LLM 能否只读题面(不看真值、不看失败代码)自动起草出可执行的
语义检查规则,在没见过的数据集上冷启动检出幻影?**

## 2. 诚实性协议(防泄题)

- authoring agent 的输入**只有** `en_question`;**绝不**给 `en_answer`、
  不给被 judge 的代码、不给任何题目的对错信息;
- 规则产出后才在带标签细胞上评估(标签来自 en_answer,oracle 口径
  |obj−ref|/|ref| ≤ 1e-3);
- 这与部署场景同构:新数据集到来,先有题面,规则必须先于任何求解结果存在。

## 3. 规则形式

每条规则 = 一个 Python 函数:

```python
def check(code: str, objective: float | None, params: dict) -> str | None
    # 返回违例描述(str)或 None(通过)
```

- `code`:被审细胞的 gen.py 全文;`objective`:打印的目标值;
- `params`:authoring agent 同时产出的**题面参数抽取**(JSON dict);
- 每题 ≤5 条,沙箱执行(子进程,5s 超时,stdlib only),异常=rule_error
  (不计检出也不计误报)。

## 4. 实施记录(含一处重要工程发现)

- LLM:内网 Qwen3.8-27B。**thinking 必须关闭**:开思考时审计提示词让模型
  把 40960 completion token 全部烧在 reasoning 上、content 一字不发
  (诊断实测,finish=length);关思考后 15–20s/题、稳定返回 5 条规则。
  T=0.3,max_tokens 16384。
- 100 题首轮 95 成功;5 例失败 = JSON 截断(1)与代码字符串内裸换行导致
  解析失败(4)→ `json.loads(strict=False)` + 截断时紧凑重试,补跑后
  **100/100 全覆盖,共 499 条规则**。
- 脚本:`scripts/d1_author.py`(起草)、`scripts/d1_apply.py`(沙箱执行+
  矩阵+规则分层)、`scripts/d1_selfconsistency.py`(A1 臂)。

## 5. 评估集

阶段 C 三臂台账每题最后一轮出解细胞 240 个(61 幻影 / 179 正确,
Z0/Z1/Z2 混合,模拟真实部署中不同质量来源混合的输入流)。

## 6. D1 对照矩阵(结果)

| 门 | 检出率(61 幻影) | 误报率(179 正确) | Youden J |
|---|---|---|---|
| A0 无校验(现状地板) | 0% | 0% | 0 |
| A1 自一致性(3 采样,目标值两两相对差>5%) | 16.4% (10/61) | 5.0% (9/179) | +11.4pp |
| A2 authoring 全部规则 | **52.5%** (32/61) | **49.2%** (88/179) | +3.3pp |
| A2 仅数值规则(读 params/objective) | 23.0% (14/61) | 11.7% (21/179) | +11.3pp |
| A2 仅代码文本规则(纯 grep code) | 32.8% (20/61) | 40.8% (73/179) | **−8.0pp** |
| A1 ∧ A2数值 | 8.2% | 1.1% | +7.1pp |
| A1 ∨ A2数值 | 31.1% | 15.6% | +15.5pp |

- 规则执行健康度:1195 次沙箱调用,rule_error 仅 2 次,无超时;
- A1 覆盖局限:100 题中 55 题有 <2 个可投票样本(裸模型崩溃率 ~51%,
  没有目标值就没有一致性可判);
- 参照(不同错误分布,仅量级参考):falsification 电池检测率 56.1%/
  误报 0%(用真值构造测试);Open-Jev 判官同数据集 AUC 0.662、
  幻影误放行 98.4%@t=0.5。

## 7. 结论(对照预注册通过线)

预注册线:检出 ≥50% 且误报 <5%。**A2 全规则未过线**(检出 52.5% 达标,
误报 49.2% 远超)。按预注册决策树("误报 ≥20% → 转 failure-informed
authoring 并重估方向"),同时分层诊断给出更精确的方向:

1. **误报来源定位成功**:纯代码文本规则(code_grep 类)净效应为负
   (J=−8pp,不如随机);数值规则(读 params/目标值)J=+11pp,与
   自一致性相当。噪声不是均匀分布的,是可切除的。
2. **数值规则盲写即命中动机性幻影机制**:检出的幻影正是本项目立项的
   那类——凭空初始库存(`check_no_initial_inventory`:"Objective 431
   exceeds the cost of buying new tools for every stage (350)")、
   目标值越出物理可能区间("Objective 9.95e13 exceeds maximum possible
   revenue 5.685e7";"Objective 980 lower than theoretical minimum cost
   $15,000")。这些规则全程只看题面。
3. **自一致性安全但弱**:误报达标(5.0%)但检出仅 16.4%,且半数题
   因崩溃无法投票——崩溃率本身就是裸模型的隐形盲区。
4. 与文献对照:我们的盲写检出率(52.5%)在量级上接近 falsification
   电池(56.1%,但后者用真值),瓶颈在误报;这验证了 authoring 路线的
   上限可观,D2 应全力压误报。

## 8. D2 方向(下一轮)

1. **numeric-only authoring**:提示词禁止纯代码文本规则,只允许
   params/目标值/量纲类检查(直接消掉 J<0 的那一半噪声);
2. **自我标定(self-calibration)**:author 必须同时给出每条规则的
   推导依据(引用题面原文数值 span)与"规则不应触发的平凡情形",
   或由 author 自写一份"看似正确"的参考解并验证规则不对它触发——
   零真值的规则自检;
3. **A1∨A2数值 作为过渡门**(J=+15.5pp,当前最优组合);
4. **failure-informed authoring**(预注册分支):给 agent 看 RetailOpt
   的幻影案例,测跨数据集泛化(训练语料与评估集严格不同源,诚实)。
5. authoring 运行的全部副产物(规则、触发记录、细胞标签)落盘,
   为后续 JEV 式判官训练攒标注数据。

## 9. 产物索引

- 规则:`runs/d1_authoring/rules_<id>.json`(100 题 499 条)
- 矩阵:`runs/d1_authoring/matrix.json`(含逐条触发明细)
- 自一致性:`runs/d1_authoring/selfconsistency.json`
- 采样台账:`runs/industryor/m3_z0{b,c}_s*.jsonl`

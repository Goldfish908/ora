# IndustryOR 零适配迁移实验 v0.1(阶段 C)

日期:2026-11-04。状态:设计落档,跑批启动中。

## 1. 动机

RetailOpt 上的全部语义资产(witness 18 条族规则、P3 语义 memory)都是
**数据集内蒸馏**的——换数据集即清零。本实验回答一个工程与科研双重问题:

> **witness 空白期,系统还剩什么?**

工程侧:验证 harness 的"机械层"(崩溃修复环)与"工程先验"(PySCIPOpt
API 知识)有多少是数据集无关、开箱即迁移的。
科研侧:无语义审计时,系统的错误谱长什么样——为"checker 冷启动"
(Open-Jev 判官 / checker-authoring)提供需求实测。

## 2. 数据

- IndustryOR-100(HF `CardinalOperations/IndustryOR`,CC-BY-NC-4.0
  非商用研究许可;本仓 `data/industryor/IndustryOR.json`,gitignore 不入仓,
  获取与完整性:`scripts/fetch_industryor.sh`,sha256
  `5b889e49…5f36`);
- 字段:`id`(1–100)、`en_question`(纯自然语言,**无内嵌数据契约、
  无 data.json**——数据在题面文本里)、`en_answer`(全部可解析为数值
  最优值)、`difficulty`(Easy 39 / Medium 41 / Hard 20);
- 已发表基线(IndustryOR 列):GPT-4 标准 28.0%、ORLM-LLaMA-3-8B 38.0%。
- 官方执行口径:COPT,600s/题;我们:PySCIPOpt,求解限时 570s、
  执行超时 620s(与 RetailOpt 全线一致)。

## 3. 三臂设计(零适配的精确定义)

| 臂 | 生成端 | 环(≤3 轮) | witness | 含义 |
|---|---|---|---|---|
| **Z0** | 裸 NL+SCIP 契约,单发 | 无 | 无 | 地板 |
| **Z1** | 同 Z0 | crash/timeout/infeasible 反馈修复 | 无 | "day-1 系统":只有机械层 |
| **Z2** | Z1 + 工程先验 | 同 Z1 | 无 | +数据集无关的工程知识迁移 |

- 三臂均 thinking on、温度 0.6、max_tokens 32768(与 RetailOpt 主线同配置)。
- **不迁移**:witness 18 规则(RetailOpt 族定制)、P3 语义 memory(7 条
  RetailOpt 语义惯例)、预求解闸门(F13/F14 为 RetailOpt 模式)。
- Z2 先验 = `evo/genomes/g0_seed/code.txt`(G1–G9 PySCIPOpt 工程陷阱 +
  建模程序),**唯一改写**:第 1 条中 data.json 相关两句中性替换为
  "All data appears in the problem text below; transcribe it into Python
  literals at the top of your script."(IndustryOR 无 data.json 基建,
  原句会注入假契约;改写只删环境引用,不引入任何 RetailOpt 语义)。
- 修复环诚实性:环内反馈**只用**执行/求解器信号(crash、timeout、
  declared_infeasible、无目标值),**绝不**用 en_answer——真值只出现在
  事后评分。环在"出解打印目标值"即停,正确性环内不可知。

## 4. 评分口径

- **可执行率**:returncode 0 且打印 objective;
- **Acc@1e-4 / 1e-3 / 1e-2**:|obj − ref| / |ref| ≤ 容差(与 ReLoop 对照
  口径对齐;RetailOpt 主表用 1e-3);
- 难度分层(Easy/Medium/Hard);
- **冷启动幻影代理**:出解且打印目标值、但目标值与 en_answer 不匹配的
  细胞——无语义审计时这就是"看不见的火",只能靠真值事后点亮。
  (注:目标值匹配但语义错误的幻影在此口径下**不可见**,是已知的
  测量下限;RetailOpt 上此类占幻影的 ~4%,见 reloop_qwen27b §4。)

## 5. 预注册式预测(跑批前写死)

1. Z2 相对 Z1 的 crash 率显著下降(RetailOpt 上工程先验把 crash
   64%→7%;若 IndustryOR 上无此效应,说明先验过拟合了 RetailOpt 的
   崩溃台账而非通用工程知识);
2. Z1/Z2 的"出解但目标值不匹配"占比将显著高于 RetailOpt 有 witness
   臂的同类残余(语义防线空白的直接度量);
3. 总 Acc@1e-2 若接近或超过 GPT-4 的 28.0% 已发表基线,说明
   harness 机械层 + Qwen3.8-27B 在新数据集上即战力可观;准确率天花板
   则受限于无语义审计。

## 6. 运行与产物

- 脚本:`scripts/m3_industryor.py`(--arm z0/z1/z2 --shard k/K,
  断点续跑按 (id, arm) 去重);
- 输出:`runs/industryor/m3_<arm>_s<k>.jsonl` + sandbox;
- 分析:`scripts/m3_industryor_analyze.py`(三臂 × 难度 × 口径表,
  幻影代理统计);
- 结果回填本文档 §7。

## 7. 结果

(待填)

# Witness 修复反馈增强:消融实验(A3)

日期:2026-11-03
脚本:`scripts/m1_feedback_ablation.py`(跑批)+
`m1_feedback_ablation_analyze.py`(分析)
数据:`runs/m1_feedback_ablation/ablation.jsonl`

## 动机

主线三链集成(combo3)之后仍残留一批幻影细胞:witness 判不可行但
grade 显示优于参照。修复环给 LLM 的反馈目前只有 witness 的机器判定
("不可行 + 违例规则编号")。假设:在反馈中附上该规则对应的**语义惯例
条款原文**(自然语言解释),能帮助 LLM 更快定位语义错位,提高修复率。

## 设计

- 细胞:combo3 主表首次完整轨迹、末轮 witness=infeasible 的 **59 题**
  (按题去重;grade 构成:幻影 better_than_reference 47 例、
  grade=match 但解转储违例 7 例、suboptimal 5 例——后两类说明
  "目标值对 ≠ 解合法",正是 witness 存在的意义);
- 双臂:
  - **plain**:反馈 = 现有 witness 机器消息(基线,与主线一致);
  - **enriched**:反馈 = 机器消息 + 命中条款的语义原文 + "重读语义后再
    改代码"提醒;
- 每细胞仅 1 次修复调用(thinking-on, temperature 0.6),修复产物重新
  过执行沙箱 + witness + grade,判定口径与主线一致
  (true_success = witness feasible 且 grade match);
- 6 线程并行,双臂同批交错,消除 API 负载漂移的臂间偏差。

## 结果

(待填:两臂修复率、配对 McNemar 分解、按族拆分、时延对比)

## 结论与处置

(待填:若 enriched 显著优 → 并入主线修复环;若无显著差异或更差 →
如实报告负结果,主线保持不变。附决策依据。)

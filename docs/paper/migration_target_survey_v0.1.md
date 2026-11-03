# 迁移目标调研 v0.1:第二数据集候选(阶段 C 前置)

日期:2026-11-03(纯桌面调研,零 LLM/零跑批)

## 候选 1:IndustryOR(首选)

- 来源:ORLM 项目(已被 Operations Research 接收),
  [github.com/Cardinal-Operations/ORLM](https://github.com/Cardinal-Operations/ORLM)
- 规模:100 道真实工业 OR 问题;形式 = 自然语言题面 + 真值最优值;
- 评测口径:执行生成代码,比对最优值(与我们 grade 口径一致);
- **已发表基线(IndustryOR 列)**:GPT-4 标准 28.0%、ORLM-LLaMA-3-8B
  38.0%(ORLM 系列微调模型 27-38%)。这是我们的对标锚点;
- 注意事项:
  - 官方执行用 COPT 求解器,且题规模偏大("无 COPT web license 可能
    直接执行失败")——我们需要 PySCIPOpt 适配层,与 RetailOpt 同款;
  - **问题异质**(不是单一参数化族):witness 无法一套 18 规则通吃,
    正好成为 checker-authoring(仅题目文本通道)的试验场;
  - 许可:仓库公开维护,需在使用前再确认数据文件的 license 字段。

## 候选 2:ComplexOR(备选)

- 来源:[Chain-of-Experts 仓库](https://github.com/xzymustbexzy/Chain-of-Experts),37 题;
- 太小,只能做定性演示,不适合做留出协议。

## 候选 3:LogiOR(备选)

- 92 道物流题,[HF: LabMem012/LogiOR](https://huggingface.co/datasets/LabMem012/LogiOR);
- 领域单一(物流),与 RetailOpt 的零售域相邻,迁移增量信息少。

## 结论

首选 IndustryOR(100 题、工业异质、有发表基线可对标、恰好考验
witness 泛化)。阶段 C 三步走(零适配 → 文本通道 checker → 事后对照)
按此目标设计。启动时机:进化生死判据落地之后。

# IndustryOR 跨域对比:对齐 Opt-Verifier(ICML 2026) v0.1

日期:2026-11-09 · 数据:`runs/industryor/m3_{z0,z1,z2}_s*.jsonl`(已跑完,
本文件为对齐口径的再分析,无新采样)

## 设置对齐

- **数据集**:IndustryOR 官方 100 题(`data/industryor/IndustryOR.json`,
  与 Opt-Verifier 论文 Table 1 同一数据源)。
- **判定**:SA@1e-2(目标值与 en_answer 相对误差 ≤1%);Opt-Verifier 论文
  未公开容差,口径声明在此。真值注意:en_answer 是参考答案而非精确最优
  证明——z2 的 20 个不一致细胞中 8 个目标值**优于** en_answer
  (可能模型对/答案松),12 个劣于(确定模型错);79% 是保守口径。
- **我方模型**:Qwen3.8-27B(thinking on);Opt-Verifier 用 GPT4o-mini,
  基线含 R1/o1——跨模型差异见下"口径声明"。

## 结果(IndustryOR SA,100 题)

| 方法 | 模型 | SA |
|---|---|---|
| Standard(裸) | GPT4o-mini | 24.0 |
| CoT | GPT4o-mini | 27.0 |
| CoE | GPT4o-mini | 29.0 |
| OptiMUS | GPT4o-mini | 31.0 |
| DeepSeek-R1 | R1 | 32.0 |
| OpenAI-o1 | o1 | 36.0 |
| ORLM | LLaMA-3-8B 微调 | 38.0 |
| **Opt-Verifier(ICML'26 最佳)** | GPT4o-mini | **45.0** |
| **z0 裸模单发(我们)** | Qwen3.8-27B | 39.0 |
| **z1 +崩溃修复环(我们)** | Qwen3.8-27B | 67.0 |
| **z2 +工程惯例(我们)** | Qwen3.8-27B | **79.0** |

**2026-11-09 增补**:COOPA(Duke/Yale, arXiv 2606.27611)为当前最强公开
基线:IndustryOR **76.0**(GPT-5.2;GPT-5 75.0、o3 73.0)。z2=79.0
仍最高,领先 +3pp;且 COOPA 用商业旗舰 GPT-5.2,我们用 27B 内网模型。
第三方 benchmark 清洗工作(OpenReview)独立报告 IndustryOR 错误率
≥54%(100 题仅 42 题通过质检)——与 survey(2606.15577)及我们的
8/20"目标值优于参考答案"发现三方互证:该 benchmark 的 SA 普遍受
参考答案噪声影响,79% 为保守口径。

要点:
1. z2 超 Opt-Verifier **+34pp**,超 COOPA **+3pp**(当前最强基线);
2. 同模型内增益:z0→z1 **+28pp**(崩溃修复环,exec 49%→92%),
   z1→z2 **+12pp**(工程惯例,exec 99%)——增益结构与 RetailOpt 一致
   (先能跑→再跑对);
3. **跨域零语义资产**:z1/z2 在 IndustryOR 上无 witness 规则、无语义
   memory、无闸门——纯工程层迁移就有 79%。这正是"分层世界模型"叙事里
   工程层跨域/语义层按域进化的实证;
4. 代价:z2 仍有 20 个 phantom-proxy 细胞运行时不可见(无审计器)——
   判官线的动机场景。

## 口径声明(审稿人预答)

- 模型不同是事实;但 z2 也超过用 R1/o1 的全部基线,且我们的增益结构
  (z0→z1→z2)在同模型内成立,不依赖跨模型比较。
- Opt-Verifier/OptArgus 均未开源(OptArgus 明确"录用后发布"),
  对比数字引自论文 Table 1。
- phantom-proxy ≠ 已证实错误:8/20 目标值优于 en_answer,需 case
  review;保守口径(全部算错)已在上表采用。

## 相关

- 解侧验证头对头(Opt-Verifier LLM 评审 vs 我们 witness 确定性重算,
  已知幻影细胞检出率):`runs/optverifier/solu_head2head.jsonl`(进行中)
- 判官跨域检出:见 p11/p13/p16 系列文档

---

## 增补:COOPA 做法与效果-成本公平对比(2026-11-09)

### COOPA(arXiv 2606.27611, Duke/Yale)做法

三组件:①**迭代置信度建模**——同题生成 k=3 个候选 formulation,
LLM 从 4 维(参数/变量/目标/约束)打置信分,max-min 选优(其消融证明
迭代是增益主来源);②元素级溯源(每元素引用原文);③多求解器路由。

### 公平性质疑的回应:环普遍存在,差别在环的内容与成本

| 方法 | 环的内容 | 每题 LLM 调用 |
|---|---|---|
| COOPA | 固定 k=3 候选生成+3 次评估+求解 | ~6–7(固定) |
| SAC-Opt(我们移植) | 锚点重建+对齐修复 | 4.2(实测) |
| **我们 z2(IndustryOR)** | 崩溃修复环,**出解即停** | **1.15(实测,max 3)** |
| **我们 C 臂(RetailOpt 含语义)** | guard+gate+witness+修复 | ~2.3(实测) |

- z2 实测成本:每题 LLM 41s、completion 3719 tokens、轮数均值 1.15。
- **效果-成本联合结论**:SA 79.0 vs COOPA 76.0 的同时,调用数少 ~5 倍。
- **诚实声明**:z2 便宜部分因"出解即停"未做语义层修复(20 个
  phantom-proxy 由此留下);但即使含完整语义层的 C 臂(~2.3 次/题),
  调用数仍比 COOPA 少约 3 倍。
- 设计哲学对应:确定性拦截(guard/witness 零 LLM 成本)+按需触发环路
  vs COOPA 的固定多候选——成本优势是结构性的。

### 论文需要的效果-成本联合表(素材已齐)

SA + 每题 LLM 调用数 + 每题 token 三列同报,防止"靠堆计算"质疑;
数据:`runs/industryor/m3_z2_s*.jsonl`(成本)、COOPA 调用数按 k=3
推算并注明(其附录有 cost 节)。

# DVSA / RetailOpt dev 固定制品检测 v0.1

状态：完成 16 个参考合格解的四臂检测；不是全 dev40、自然修复或 SOTA 结论。

## 1. 样本与口径

从同一个 20 题 saved dev replay 中，纳入：

- 10 个冻结旧 witness 判为语义违规的解（C-INIT 10 个场景、C-DEMAND 1 个场景，存在机制重叠）；
- 6 个旧 witness 可行且目标值匹配的业务正确解。

另有 1 个仅目标质量不合格解和 3 个无解场景，不混入语义误报分母。旧 witness 同时是 A3 反馈与标签来源，因此 A3 与标签一致不是独立零误报证明。

A0/A1 的 LLM 只看到题面、数据、解和 opaque ID，不看标签、参考目标值或 witness 判决。A1 获得与 DVSA 相同的两条资产文本。两臂统一 `enable_thinking=false + max_tokens=8192`。初次 medium reasoning 耗尽输出、正文为空的失败协议保留在 `work/dvsa/retailopt_llm_judge/`，不进入本结果。

## 2. 检测结果

| 臂 | 错误检出 | 干净解误报 | UNKNOWN |
|---|---:|---:|---:|
| A0 no-memory | 60%（6/10） | 33.3%（2/6） | 8/16 |
| A1 文本 memory | 90%（9/10） | 33.3%（2/6） | 5/16 |
| A2 DVSA | **100%（10/10）** | **0%（0/6）** | **0/16** |
| A3 完整旧 witness | **100%（10/10）** | **0%（0/6）** | **0/16** |

A0/A1 的 UNKNOWN 中，分别有 6、3 个是 `invalid_judge_response`，另外各有 2 个是模型显式 UNKNOWN 或缺少有效判决。它们没有被静默当作 VALID 或检出。

配对检验：

- 检出：A2 对 A0 为 4:2、`p=0.6875`；对 A1 为 1:2、`p=1.0`；对 A3 为 0:0、`p=1.0`。
- 误报：A2 对 A0/A1 均为 0:2、`p=0.5`；对 A3 为 0:0、`p=1.0`。

**没有任何一项相对 A1 的配对优势达到显著性线。小样本的 100%/0% 不能替代分母和配对检验。**

## 3. 两个可复核的文本误报

1. `retail_f2_price_band_tight_v0`：文本评审声称 `SKU_Basic|DC1|1` 销售、替代和 lost 都为零，但 freshest bucket 实际有 `sales=75.75`，恰好满足需求 75.75。这是长稀疏表中的漏读。
2. `retail_f3_storage_bottleneck_v0`：文本评审凭空加入不存在的 Premium 库存，报出 1114.8 > 900；按真实 `solution.I` 重算，DC4/t11 冷储占用为 **784.56 < 900**。这是字段幻觉与错误求和。

这些是可定位的文本评审错误，不支持“LLM 一定不可靠”的笼统说法，但直接说明为什么目标值匹配和长上下文自评都不能替代确定性重算。

## 4. 成本

| 臂 | LLM 调用 | 总 tokens | 生成延迟合计(s) |
|---|---:|---:|---:|
| A0 no-memory | 16 | 764,727 | 723.966 |
| A1 文本 memory | 16 | 753,417 | 545.072 |
| A2 DVSA | 0（本轮确定性重放） | 0 | 0 |
| A3 旧 witness | 0（本轮确定性重放） | 0 | 0 |

A2/A3 的本轮重放不调用 LLM，但既有资产生成/维护成本未摊销，不能写成零成本完整系统。A1 本轮 token 少于 A0 是具体输出分布现象，不据此声称文本 memory 必然节省成本。

## 5. 产物与边界

- 结果：`work/dvsa/retailopt_fixed_arms_analysis/analysis.json`
- 图：`/home/hewj13/paper_icml2027/figures/dvsa_retailopt_dev_fixed_arms.png`
- 盲评：`work/dvsa/retailopt_llm_judge_bounded/`
- 资产 sanity：`work/dvsa/retailopt_core_audit/analysis.json`

两条 DVSA 资产只覆盖 C-INIT/C-DEMAND，不是完整业务验证器。固定制品检测不能直接推出自然代码修复成功率；需要与共享初始的四臂自然修复结果联合解释。正式 direct-legacy 自然修复使用 A1 文本 + 完整旧 witness；legacy-only 仅作敏感性，不与本确定性 A3 混用。

# DVSA 最小统一规格与实验协议 v0.1

日期：2026-11-11。状态：实现前设计；尚未产生 DVSA 实验结果。

前置审查：`docs/paper/dvsa_related_work_v0.1.md`。本文将“跨实例、经验证复用”与“每题临时生成 checker”严格区分。

## 1. 可检验研究问题

> 对共享业务机制的优化问题，能否把文本经验转成带显式作用域、输入绑定和独立验证记录的语义资产，并在不读取 frozen test 反馈的情况下，复用于其他实例的解级核验和修复？

研究假设不是“手写规则必然优于 LLM”，而是：在相同初始候选和相同语义内容下，**确定性执行 + 独立验证 + 明确失效**比纯文本经验减少漏检和不当接受，并最终改善业务正确率。

三个层级分别报告：

1. **规格覆盖**：有没有已验证资产适用于当前实例；没有则 `NOT_APPLICABLE`，不能假装已核验。
2. **检查质量**：适用的资产能否发现独立构造错误、保持独立干净解不误报；故障则 `UNKNOWN`。
3. **修复收益**：数值证据能否让同一生成器修对，而不是只增加拦截或成本。

## 2. 与旧路线的关系

- 旧路线 A：文本 memory/trigger，可能帮助建模，但没有可执行保证。
- 旧路线 B：LLM 针对单题写 Python checker，再对该题反例修复；这是 checker authoring，不自动形成跨题资产。
- 旧路线 C：`m1_witness/retailopt.py`，覆盖 RetailOpt 多机制的硬编码检查器，作为直接旧 witness 对照。
- **DVSA**：共享安全解释器 + 声明式不变量 + 显式数据/解绑定 + 独立验证注册表。每题若仍需重写逻辑，必须记为 `instance-authored`，不能算作复用。

旧 MAMO/NLP4LP sealed 的负结果继续有效。本协议不是通过改名、换分母或删去负结果重启同一实验。

## 3. 资产模型

一个资产包包含：

```text
asset_id / schema_version / asset_version / parent_id
status = candidate | domain_validated | frozen | rejected
source = {type, reference, text_or_requirement_hash}
scope = {domain, required_data, required_solution, applicability}
bindings = {变量、常量、索引、表路径、单位与默认值}
invariants = [forall + safe_expression + relation + tolerance]
validation = {clean_cases, mutations, independent_reference_version}
implementation_sha256 / provenance / created_utc
```

四种资产范围不混用：

| 范围 | 示例 | 允许的迁移主张 |
|---|---|---|
| 通用检查纪律 | 重算目标、检查非负/整数域、缺字段不得视为通过 | 可作为新域先验，但不是业务知识 |
| 领域机制 | 需求平衡、替代方向、库龄递推、运输流守恒 | 仅在声明的机制和 schema 适用时复用 |
| 实例绑定 | 某题字段名、产品集合、数值参数、单位换算 | 不得作为跨题能力证据 |
| 经验证的修复经验 | 某类数值违规如何反馈给生成器 | 单独验证，不与检测增益混称 |

### 3.1 声明式安全表达式

初版只允许 JSON AST，不执行 LLM 提交的 Python，也不提供 `eval`：

```json
{
  "asset_id": "retailopt.demand_substitution_balance",
  "schema_version": "dvsa.expr.v0.1",
  "asset_version": "0.1.0",
  "scope": {"domain": "retailopt", "required_data": ["products", "locations", "periods", "network.sub_edges"]},
  "forall": {
    "p": {"path": "data.products"},
    "l": {"path": "data.locations"},
    "t": {"range": [1, {"add": [{"path": "data.periods"}, 1]}]}
  },
  "relation": "eq",
  "lhs": {"sum": [
    {"var": "sales_by_age"},
    {"var": "substitution_out"},
    {"var": "lost"},
    {"neg": {"var": "substitution_in"}}
  ]},
  "rhs": {"var": "demand"},
  "tolerance": {"abs": 0.0001, "rel": 0.0001}
}
```

解释器实际支持的语法以实现和 schema 测试为准，至少包括：常量、索引变量、有限算术、安全路径/稀疏表查询、动态 range、带过滤的求和、`<= / >= / ==`、有限数检查与绝对/相对容差。数组下标和扁平 `a|b|c` key 的转换只在显式 binding 中进行。

作用域先于求值：

- 适用条件为假：`NOT_APPLICABLE`，不进入检出/误报分母。
- 应适用但字段缺失、单位未知、类型不符、非有限数、表达式越界或超时：`UNKNOWN`，不得当作 satisfied 或 violation。
- 求值完成且约束满足：`SATISFIED`。
- 求值完成且约束违反：`VIOLATED`，输出索引、lhs/rhs、差值、容差和来源。

每个不变量记录单独状态，不能只靠脚本返回码。任一修复前必须给出具体数值证据；UNKNOWN 默认 fail-open，但记录为未验证，不能隐藏覆盖率。

### 3.2 资产不等于任何通过检查

DVSA 判定的是：**当前返回解是否满足已经编码的业务不变量**。它不能单独证明：

- 数学模型与 solver code 等价；
- 漏掉的约束在每个可能数据点都被编码；
- 当前解是全局最优；
- 自然语言业务规约本身无歧义或无错误。

能交给 ORSMT/SOVER 的形式关系，应优先报告形式证明结果；DVSA 不取而代之。

## 4. 原型范围

### 4.1 RetailOpt：域内冻结复用

先实现三个能检验真实 schema 和绑定能力的机制：

1. 需求—销售—替代—lost sales 平衡；
2. 新鲜库存到货与转运净流守恒；
3. 目标值重算（先覆盖采购、损耗、lost sales、库龄库存及已声明固定成本/转运项）。

之后再按开发证据增加库龄/损耗、产能、MOQ/pack、budget 等；每项单独版本化，不用一个不可定位的大脚本冒充统一规格。

`m1_witness/retailopt.py` 仅用于：

- A3 直接旧 witness 对照；
- 检查新解释器在相同案例上的规则级一致性 sanity check；
- 帮助定位实现错误。

它不作为新规格的独立真值。若两者共用业务约定，必须写成“独立实现一致性”，不是“独立语义证明”。

### 4.2 BWOR：新域冷启动与 frozen test

采用 [OR-LLM-Agent/BWOR](https://github.com/bwz96sco/or_llm_agent) 正式 JSONL release。数据卡声明 CC-BY-4.0；保留来源和署名。`data/external/or_llm_agent/artifacts/BWOR/README.md` 记录公开 evaluator；绝对误差口径为 `0.1`。

- 82 条中 2 条 `no_optimal`，按公开评分分母先排除，剩 80。
- 在读取逐题内容前，仅依公开 `problem_type` 元数据选择 LP/IP/MIP：29 + 33 + 11 = **73**。
- 排除 5 个 NLP 与 2 个 goal programming 是表达能力边界，不宣称全 BWOR SOTA。
- 本地 `data/external/bwor.json` 的 80 个 ID 均为正式 release 子集；已结构核验 80/80 题面和答案一致，但未把内容用于资产设计。
- 当前仓的 scripts/work 没有 BWOR 逐题实验记录；此前仅调研公开聚合指标。若发现其他暴露，强制划入 dev 并登记。

新域优先提炼可共享的机制，例如资源上下界、流量/物料守恒、目标重算、变量域和显式容量。**模板复用、仅重新绑定、整题重新 authoring 分开计数。** 没有可复用模板时就报告覆盖失败，不为每题手写规则后宣称跨域资产成功。

## 5. 数据划分与信息隔离

| 集合 | 用途 | 允许的信息 | 禁止的信息 |
|---|---|---|---|
| RetailOpt dev 40 | 域内资产开发与机制消融 | 题面、数据、已有开发轨迹、受控标签 | held-out 答案反写资产 |
| BWOR dev 16 | 新域冷启动、模板/绑定和反馈开发 | 题面、公开答案、独立参考与受控错误 | validation/frozen 输出 |
| BWOR validation 16 | 冻结候选的一次性选择、win-safe 检查 | 冻结资产运行结果和独立评分 | 根据单题答案继续改写后仍称同一版本 |
| BWOR frozen 41 | 最终一次性四臂终验 | 冻结系统输出、盲建参考、最终指标 | 任何提议、选择、调参、资产写回 |

BWOR 使用固定种子 `dvsa-bwor-v0.1` 对 ID 的 SHA256 排序，依次分配 dev 16 / validation 16 / frozen 41；划分脚本、源哈希、ID 文件哈希纳入 `data/dvsa/splits_manifest.json`。不是按成绩、难度或某方法是否有效调样本。

### 5.1 独立参考，而不是循环真值

BWOR 只有公开最优目标值，没有变量级金解。固定制品审计按以下顺序：

1. **参考作者阶段**：只读题面、公开答案和公开元数据，不看候选解、文本 memory、DVSA 资产或旧 witness 输出；独立写出参考模型与解。
2. **参考冻结**：记录模型、解、公式、假设、参考哈希和无法裁决原因。公开答案不一致时标为 `reference_conflict`，不能为了匹配答案偷偷改业务约束。
3. **制品构造**：从独立参考解生成单机制受控变异；记录预期违反的规则，而不是让被测资产自己定义 wrong。
4. **候选评测**：冻结参考后才允许查看被测系统输出；冲突/模糊样本单列，不用事后清洗替换主结果。

对 frozen test，参考作者也必须在系统、prompt、资产、阈值全部冻结之后进行，并且不能向系统作者反馈任何逐题信息。其作用只是建立最终评分参照，不是提前帮助资产适配。若当前执行环境无法保证人员/上下文隔离，应准确称为“盲于候选与资产的独立构造参考”，不能夸大成完全独立人工标注。

RetailOpt 的公开目标值和 frozen 旧 witness 可以作参考实现对照，但若两者业务假设同源，不能称完全独立语义标签。受控变异的目标规则必须来自参考规格，检出指标优先统计**目标机制是否被命中**，而非任意报错都算 TP。

## 6. 四臂与因果对照

所有臂使用同一 Qwen3.8-27B endpoint、同一初始输入/解 schema、同一求解器和时间预算、相同最大修复轮数、相同最终评分。基础求解 prompt 对输出决策的要求也保持一致。

| 臂 | 建模先验 | 修复反馈 | 资产更新 |
|---|---|---|---|
| A0 no-memory | 无文本 memory、无语义资产 | 仅通用执行/求解器反馈 | 无 |
| A1 text-memory | 与 A2 同来源、同语义的文本经验 | 文本经验 + 同一通用执行反馈 | 无 |
| A2 DVSA | 与 A1 同内容的文本先验，不额外塞业务答案 | 冻结资产的数值违规证据；无适用/UNKNOWN 不得冒充反馈 | 仅 dev；validation/frozen 只读 |
| A3 direct-legacy-witness | 与 A1 相同 | 直接套用旧 RetailOpt witness；schema 不符记 UNKNOWN 并 fail-open | 无 |

A2 在新域的冷启动仅发生于 BWOR dev；frozen test 不是在线自进化。文本与资产必须可从同一注册表渲染，避免 A2 多获得一份业务知识而 A1 只是弱泛化提示。

另设共享初始候选的 **repair-only** 重放：同一份初始代码/解分别接受文本反馈和 DVSA 数值反馈，隔离“初始生成不同”与“反馈不同”。它是因果证据优先于四次独立采样的总分差。

为判断资产是否真的复用，日志至少分为：

- `frozen_template_no_llm`：已有绑定直接重放，无 LLM；
- `frozen_template_new_binding`：模板固定，只绑定新实例字段/索引；
- `instance_authored`：新写不变量，不能计入模板复用；
- `not_applicable / unknown`：无有效核验。

## 7. 指标与判定

### 7.1 固定制品

- 目标错误检出率、按机制检出率、干净参考误报率、UNKNOWN/NOT_APPLICABLE 覆盖率；
- 参考冲突数和排除原因必须随分母公开；
- 同题多变体不能当作多套独立任务。逐题汇总后做配对检验，制品级结果另报并按题聚类；
- 报告 Wilson 区间或适当聚类区间，不只写 0/0、100% 等点估计。

### 7.2 端到端

- **公开目标值正确率**：按对应 benchmark 公式评分，所有规定样本留在分母，缺失/超时算错。
- **业务正确率**：有返回解、独立参考业务检查通过且目标值满足口径；无法审计单列，不得默认为正确。不得与模型语义等价或全局最优证明混称。
- **win-safe**：原本业务正确的题不得被修坏，报告 `harmed_win=0` 与逐题变化；仅报告平均提升不够。
- 逐题 McNemar 精确双侧检验，披露 discordant pairs；多样本变体或种子按题聚类，不伪装独立。
- 成本：全部 LLM 调用、输入/输出 token（endpoint 提供时）、solver 次数、墙钟、每题成本；缺失项明确标 NA，不用成功样本归一化掩盖失败成本。

主要配对为 A2 相对 A1。有效线预先固定：

1. frozen test 端到端业务正确率的 McNemar `p < 0.05`；
2. 独立干净制品误报率 `<= 10%`，UNKNOWN 不转化为检出；
3. `harmed_win = 0`；
4. 结果必须来自至少一个真实 `frozen_template` 复用路径，不能全靠逐题 authoring 冒充资产收益。

未达任一项即不启动 SOTA，按规格覆盖、参考标签、规则实现、绑定、判决纪律、修复反馈六层归因。即使固定制品检出显著，也不能替代端到端有效线。

## 8. SOTA 门槛与模型角色

达到有效线后，才运行冻结 harness 的同口径外部对照：相同数据子队列、公开容差、超时/缺失分母、初始生成器与预算。COOPA 全 BWOR 的 80.0% 等数字不能与本协议的 73 题子队列直接排名；必须取逐题公开预测或明确标为不同分母参照。

- Qwen3.8-27B 用于机制开发和主要配对实验。
- 闭源模型只用于最终冻结 harness 的敏感性/质量成本对照，不参与生成 memory、提议规则、选择资产或调参。
- 若无闭源 API，不等待也不影响主结论；不把不同模型的公开排行榜拼成“公平 SOTA”。
- v4 LoRA judge 是独立任务，不与 DVSA 共享调参结果。

## 9. 最小交付与测试

实现文件计划：

- `ora_agent/dvsa.py`：安全表达式、绑定、四态判定、资产验证与哈希；
- `scripts/dvsa_split.py`：只按 ID/公开元数据生成 BWOR 划分与暴露清单；
- `scripts/dvsa_retailopt.py`：RetailOpt 规格适配和旧 witness 对照，不重写伪通用 checker；
- `scripts/dvsa_bwor.py`：冷启动、独立参考、固定制品与端到端记录；
- `scripts/dvsa_analyze.py`：逐题配对、win-safe、成本及图；
- `assets/dvsa/`：版本化规格和验证注册表，不存密钥；
- `work/dvsa/`：可复现输出；论文汇总与图另集中到未提交的 `/home/hewj13/paper_icml2027/`。

必须通过：合法/违规/UNKNOWN/NOT_APPLICABLE、缺字段、动态索引、非有限数、越界、禁用表达式、容差、资产哈希、来源/版本绑定、文本与规格同内容渲染、跨题零 LLM 重放，以及配对统计的单元测试。

完成原型后先跑现有相关测试与新增测试，再做小规模真实调用；不能只测 import 或只用资产自己构造的显然错误宣称成功。

## 10. 开发实现修订（先于 validation/frozen）

以下修订只来自 dev 实现与评测审计，未使用 validation/frozen 结果：

1. **变量变异同步重算目标**：受控变量变化后，报告目标仍由新变量正确计算；只有 `objective_misreport` 专门制造目标误报。否则仅重算目标的检查器会对所有变量变异报警，虚增检出。
2. **唯一解制品分母**：相同变量与目标的解只计一次；可由多个参考规则解释的标签保留，但不重复计数。LLM 盲评使用内容哈希 ID 和随机顺序，不使用会暴露 clean 位置的连续 ID。
3. **共享变量 schema 条件**：首轮 BWOR binding 作者与盲评共享候选参考的变量声明，但不获得参考约束、目标表达式或公开答案。该设置验证条件于变量分解的语义审计，不能宣称自主变量发现或无条件全 pipeline SOTA。
4. **独立 binding 与参考导出 binding 分离**：参考导出只用于执行器 sanity；研究对照使用仅从题面+schema+模板文本生成的 binding。行为覆盖要求全制品激活轨迹与独立参考规则一致。
5. **文本盲评**：A0/A1 都由同一 LLM 盲评相同制品，A1 额外获得与 DVSA 相同的模板文本；INVALID 必须有数值证据，UNKNOWN 不计检出，重复输出 ID 记 UNKNOWN。
6. **参考合格分母**：当前固定制品只覆盖 7/16 个候选参考合格的 dev 问题，必须同时披露其他参考失败，不得称为全 dev16 结果。后续 frozen 的参考失败也必须保留在覆盖/UNKNOWN 报告中，不能事后只保留成功参考。
7. **开发结果未过线**：A2 对 A1 的固定制品配对 `p=0.0625`，不启动 SOTA。需要先完成共享初始候选的自然修复对照，再冻结进入 validation 的配置。

当前实现文件比第 9 节的初始计划更细：`dvsa_model.py` 负责标量 LP/MILP 编译与审计，`dvsa_templates.py`/`dvsa_linear.py` 负责模板和线性绑定，`dvsa_binding_author.py`/`dvsa_llm_judge.py` 负责隔离输入的作者与文本对照，`dvsa_fixed_arm_analyze.py` 负责唯一制品四臂分析。开发结果见 `docs/paper/dvsa_dev_fixed_arms_v0.1.md`。


## 11. 自然修复实现修订（先于 validation/frozen）

1. 四臂共享同一初始模型哈希和求解结果；独立参考只做事后评分。A3 可复用 A1 轨迹验证旧 witness 的 schema 失效，但必须同时报告实际新增成本与独立运行等价成本。
2. 所有臂共享通用执行反馈。A2 在无解时可做一次执行恢复，标为 `execution_failure_unknown_semantics`，不得计入 `dvsa_violation` 语义修复事件。
3. `data` 字段完全省略且模型没有缺失 `data.path` 时，后续版本默认 `data={}`。缺失路径仍返回错误，不把参数默认为零。dev 严格结果与该格式敏感性并列，不能用敏感性替换主结果。
4. 业务正确率按“当前解通过独立参考审计 + 公开目标值绝对误差≤0.1”计算，分别报告语义可行、目标合格与二者同时成立；不据此宣称模型等价。
5. 自然 dev 中 A2 没有 `dvsa_violation` 触发，A2 对 A1 在严格和格式敏感性口径均为 `p=1.0`。因此只能记录保守 gate 的成本/win-safe 信号，不能宣称自然修复提升或启动 SOTA。

自然修复报告：`docs/paper/dvsa_dev_repair_v0.1.md`。


## 12. RetailOpt 自然修复实现修订（先于 validation/frozen）

1. 当前 RetailOpt repair-only 使用 `replay_gen1` 中已有的 20 个 dev 场景，不按本轮结果重新挑题；其中 17 个有解、3 个崩溃。它不是全 dev40 的新采样或完整 pipeline 准确率。
2. 当前只注册需求/替代平衡和期初老库存两个资产。实际错误分布为 `C-INIT` 10 个场景、`C-DEMAND` 1 个场景，两条资产覆盖这些已观察机制，但不覆盖完整旧 witness 的所有业务规则。
3. `C-INIT` 是声明的 RetailOpt 建模约定：期初 `r<shelf_life` 的老库存为零，freshest bucket 由到货方程另行处理。不能把它写成任意库存系统都成立的普遍规则。
4. 解释器必须保持字面整数在稀疏表 key 中的表示（如期数 `1` 不得变成 `1.0`），否则缺省零会造成系统性漏检。真实 17 个解上，两条资产与旧对应规则的计数一致性均为 17/17，且 6 个初始业务正确样本无资产误报。
5. 每臂最多一次反馈/自评修复和一次共享执行恢复。执行恢复只处理求解/API/输出契约失败，单独记录，不计为 DVSA 语义修复事件；可执行但业务错误的解不获得额外执行恢复。
6. A0/A1 对全部场景各有一次自评；A2/A3 在数值违规时修复，无解时共享执行反馈，satisfied 时零调用。所有臂使用同一初始代码哈希和相同求解/输出预算。
7. 业务评分使用冻结旧 witness 的可行性与参考目标值。A3 同时以旧 witness 作反馈，因此它不能作为 A3 的独立真值或证明其普遍零误报；评分结论仍限于当前解，不是模型语义等价。
8. 初始 LLM 生成属于已有缓存输入，本轮只报告 repair-only 增量调用、token、求解次数和墙钟，不把缓存初始成本写成零成本完整系统。


## 13. RetailOpt 文本盲评预算修订

首次文本盲评使用 `reasoning_effort=medium` 和 16K 输出预算时，16,384 个 completion tokens 全部用于 reasoning，正文为空（`finish_reason=length`）。该协议无法产生判决，保留在 `work/dvsa/retailopt_llm_judge/` 作为失败记录，不进入检出/误报分母。

后续两种文本臂统一使用 `chat_template_kwargs.enable_thinking=false` 和 8K 输出预算；同一题先验证两臂均能返回合法 JSON 再启动全量。自然代码修复仍使用 medium reasoning，不因文本评审的预算调整而改变。正式分析只读取 `work/dvsa/retailopt_llm_judge_bounded/`，并记录 decoding 配置，避免把失败协议与有界盲评混合。


## 14. RetailOpt A3 配置纠偏

首轮 A3 实际运行为“仅旧 witness 字符串反馈”，未包含预注册方案中与 A1 相同的文本 memory。该结果保留为 legacy-only 敏感性：

- 轨迹：`work/dvsa/retailopt_repair/dev/*/legacy_witness_only/`
- 分析：`work/dvsa/retailopt_repair_analysis_legacy_only/analysis.json`
- 图：`/home/hewj13/paper_icml2027/figures/dvsa_retailopt_dev_repair_legacy_only.png`

正式 direct-legacy 臂使用 **A1 相同的两条资产文本 + 完整旧 witness 数值反馈**，其余初始代码、反馈次数、执行恢复和求解预算不变。A0/A1/A2 不重跑；legacy-only 不用于正式 A3 对比或 SOTA 判断。固定制品中 A3 是确定性检查，不受这次 prompt 配置纠偏影响。

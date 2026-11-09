# RSI / 自进化文献调研(2026-11-09)

针对 mem_evo2 设计 revise 的文献依据。重点:谁已做过什么、我们的差异点、
可直接借鉴的机制。

## 1. Self-Harness(arXiv 2606.09498)——最近邻

三阶段闭环:Weakness Mining(从执行轨迹挖模型特定失败模式)→
Harness Proposal(多样但最小的 harness 修改)→ Proposal Validation
(回归测试通过才接受)。Terminal-Bench-2.0/SWE-bench Verified/AppWorld
× 3 个基座,9 组合全部正收益(相对增益最高 132%)。

**与我们的差异**:①它改 harness(通用 agent 脚手架),我们进化的是
带确定性信任锚的分层资产(guard/witness/memory)+参数化判官;
②我们的判定更严:逐细胞反事实重放+两级晋升+win 误报=0,它只有
回归测试;③它无参数化审计线。
**借鉴**:Proposal 强调"多样但最小"——对应我们的 R3 锦标赛。

## 2. Self-Evolving Agents Can Repair Failures but Struggle to Generalize
(arXiv 2610.22984)——泛化负结果,我们的 gen1 是它的实例

核心发现:**repair-generalization gap**——失败驱动经验能修已见失败,
但很少迁移到未见任务;即使经验经过验证也难以迁移;verifier 反馈与
额外交互帮助有限,**成功轨迹对迁移更有帮助**。

**对我们的意义**:
- gen1 条款#8(dev +10.4pp → gap +0.0pp)正是 repair-generalization
  gap 的教科书实例;我们的两级晋升是这个 gap 的工程解,引用为动机。
- **新设计启示**:memory 进化目前只用失败簇;该文提示应加入
  **成功轨迹的正例蒸馏**(从做对的细胞提炼"期初库存钉 0"类正向条款)。
  这是 propose 数据源的一个新维度。
- "验证器反馈迁移有限"支持双轨:非参数条款迁移难 → 参数化判官
  赌泛化,两条线的分工有了文献依据。

## 3. AutoSpec——CEGIS 规则进化的直接先例

用反例引导归纳合成(CEGIS)自动进化 LLM agent 的安全规则。
**对应我们的 R2**(win 误伤反例驱动条款细化)与 R1 的 guard 补丁细化
(已实战:数字 sum 误报反例 → 递归污点细化)。

## 4. RSI 主线(引用用)

- **DGM**(Darwin Gödel Machine,ICLR 2026):代码自修改+档案开放式进化。
- **Huxley-Gödel Machine**:lineage meta-productivity 引导搜索。
- **Polaris**(2026):经验抽象+最小补丁修复,7B 小模型 Gödel 框架——
  支持"判官小模型化"的可行性。
- **VeriSkill**(arXiv 2607.27733):程序验证技能自进化,强调
  "技能特定失败的识别"——对应我们的逐细胞反事实信用分配。
- **I-EDI**(IJCAI 2026):可验证反事实模拟,警惕"lucky guess"成功
  ——对应我们 witness 判定作为监督信号的纪律(数值对≠语义对)。

## 5. 设计 revise 的文献-机制对照

| 我们的机制 | 文献依据 |
|---|---|
| R1 确定性资产先行 | VeriSkill(技能特定失败识别)+ 我们的信噪比分析 |
| R2 CEGIS 反例细化 | AutoSpec(同构) |
| R3 表述锦标赛 | Self-Harness(多样最小修改) |
| 两级晋升 | 2610.22984(repair-generalization gap 的工程解) |
| 正例蒸馏(新增) | 2610.22984(成功轨迹迁移更好) |
| 判官参数化迁移 | 2610.22984(验证器反馈迁移有限的出路)+ Polaris(小模型可行) |
| R6 元层进化 | DGM/Huxley(主线,我们是受限安全版) |

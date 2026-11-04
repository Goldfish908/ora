# JEV 融入探索 v0.1(独立探索文档)

日期:2026-11-03。定位:探索性 topic,不占用主线资源;主线(harness + 自进化)
继续推进,本文档只回答一个问题:**JEV(System One 决策模型)能/应该以什么
形态融进我们的 harness,验证路径是什么**。

## 0. TL;DR

1. JEV 不是 LLM、不生成文本,是"状态 → 类型化决策(带校准概率)"的模型。
   它的三种问题形态(Noul 是非题 / Choice 选项集 / Score 量表)恰好覆盖我们
   harness 里的全部决策点。
2. **设计哲学:JEV 当脚手架,不当终审。** 我们的幻影是对抗性"看起来合理"
   的样本,正是各类判官的盲区;终审权永远留给确定性 witness。
3. 我们的独特资产:**witness 是现成的"裁判的裁判"**——已核验 316 个带语义
   真值标签的细胞(225 幻影 + 61 真成功,8 族全覆盖),可用来精确测量任何
   判官在我们分布上的 false-clear / false-alarm 率。
4. 最高价值集成点:**J2 跨数据集冷启动判官**(直接回应 witness 迁移软肋)
   与 **J1 轨迹标签批量生产**(喂 RQ2 反例监督训练)。RetailOpt 域内仲裁的
   提升空间只剩 1.1pp,JEV 的价值不在域内。
5. ~~立即可做(零外部依赖):P0 替身校准实验~~ **已完成(2026-11-04,
   316/316)**:Qwen27B 无思考判官在我们的幻影集上 false-clear 45.3%、
   真成功误报 42.6%、置信度恒 0.95 但高置信判定实际干净率仅 29%——
   判官路线不及格,f1(幻影初始库存主场)检出率仅 14%。全文见 §6 P0 结果。

## 1. JEV 事实卡(2026-11-03 检索,来源见末注)

- **出身**:TypeSafe AI,创始人 Diogo Almeida(前 OpenAI,InstructGPT/RLHF
  论文作者之一)。2026-09-15 发布,early access(需申请 API key)。
- **不是什么**:不是 LLM,不生成字符串。"Type-safety 是数学保证,0% 类型
  错误"——注意这只是 schema 层的保证,**不是语义永远正确的承诺**。
- **是什么**:System One 模型。输入 = 非结构化状态(强调结构化程序状态);
  输出 = 类型化决策 + **校准概率 + 置信分**。训练方法 RLCD(Reinforcement
  Learning for Calibrated Decisions)——优化目标是"带认知诚实概率的决策",
  对照 LLM 的 RLHF(人类偏好)/ RLVR(可验证奖励)。
- **三种原子问题**(可对同一状态并行多个):
  - `Noul`:是/非判断 → 返回 0–1 概率;
  - `Choice`:选项集 → 返回选择 + 各选项概率(基数上限 255,高基数两阶段:
    先独立打分再显式选择);
  - `Score`:有序量表评分。
- **性能(厂商数字 + 第三方复核)**:端到端 70–500ms;$0.042/M 输入 token,
  输出免费。LangChain 实测 0.44s/次、$0.00035/次;二值判断 500/500 与人类
  oracle 一致;连续评分方差比 GPT-5.6/Claude 判官低 92–913×。explainx 独立
  复核:与 Privatemode 的 one-token GLM-5.3-Flash 设置文本精度打平(后者贵
  4 倍)——**说明"限制普通 LLM 只输出单 token 决策"是零依赖 fallback**。
- **定位**:它不是框架级对手,是**可替换组件**;它的同类(plain LLM 判官)
  的校准缺陷(false-clear 率高达 90%,BargLabs 校准研究)正是我们确定性
  witness 存在的理由。

## 2. 相关性地图:JEV 的三种问题形态 = 我们 harness 的三类决策点

| JEV 形态 | 我们 harness 里的对应决策点 | 现状 |
|---|---|---|
| Noul(是/非+概率) | witness 语义判定(违例与否)、预求解闸门(拦截与否) | 确定性 Python 规则 |
| Choice(选项集) | 集成仲裁(多候选选一)、修复环动作路由(修代码/修语义/重生成) | min-目标值仲裁 / 硬编码路由 |
| Score(量表) | 进化适应度预筛、轨迹质量打分(喂 memory 蒸馏/训练) | 全量真实评测 |

## 3. 设计哲学:脚手架,不是终审

三条不可让渡的纪律(来自 E2/F10 的实证):

1. **终审必须确定性**。幻影是被优化压力诱导的对抗性样本,专门伪装"看起来
   合理";任何学习出来的判官(包括校准过的)都必须先证明自己在我们的幻影
   子集上不被骗,才允许进入管线,且只能 fail-open(拿不准就放行/升级人工或
   witness),绝不能 fail-closed。
2. **witness 是裁判的裁判**。我们对 316 个细胞有确定性语义真值标签——这是
   稀缺资产,任何判官(JEV、Qwen、未来的 checker-authoring agent 产出)都
   在它上面校准,校准不过就不用。
3. **JEV 的理想归宿是"自我消除"**:在 witness 缺位的域冷启动 → 积累判定
   → checker-authoring 把判定蒸馏成确定性规则 → JEV 退出,成本归零。判官是
   脚手架,确定性规则才是建筑本体。

## 4. 集成点设计(按价值 × 可行性排序)

### J1 ★ 跨数据集冷启动判官(Noul)——最高价值

- **要解决的痛点**:witness 规则按族定制,换数据集(如 IndustryOR)就没了;
  从数据集提取规则又有"泄题"质疑。这是 witness 路线公认的软肋。
- **契约**:输入 = 题面 + 生成代码 + 解摘要;JEV Noul 问题 "Does this
  solution violate the problem's stated semantics?" → 概率 p。
- **与现有组件关系**:witness 缺席时**唯一**的语义层;witness 在场时降级为
  并联初筛(witness 终审)。
- **部署形态**:p ≥ 0.8 判违例进修复环;0.2 < p < 0.8 放行但记账(低置信
  样本正好是 checker-authoring 的学习材料);p ≤ 0.2 放行。
- **验证实验**:先 P0/P1 校准(§6),再 IndustryOR 零适配迁移实验里做
  "JEV-only vs JEV+随蒸馏 witness vs 无校验"三臂。
- **成本**:190 题 ≈ $0.07/轮;迁移预实验全量也在 $1 量级。
- **风险**:IndustryOR 无参照解也无 witness,校准只能靠抽样人工;若 JEV 在
  RetailOpt 幻影集上 false-clear 率就很高,则本集成点整体不成立——所以 §6
  校准是前置闸门。

### J2 ★ 轨迹标签批量生产(Noul/Choice)——喂 RQ2 反例监督训练

- **用途**:给大规模 agent 轨迹打"语义违例/干净"标签,构造反例监督训练集
  (预注册 RQ2 的数据瓶颈)。RetailOpt 域内 witness 已能做;JEV 的价值在
  **witness 未覆盖的域/族**打标签。
- **铁律**:只允许在"JEV 经 witness 校准达标"的分布上用 JEV 标签;否则
  标签污染训练集,比没有更糟。
- **契约**:批量 Noul(违例与否)+ Choice(违例类型归属:C-INIT 类/
  C-DEMAND 类/……)——JEV 的并行原子问题正好一次问完。
- **与 memory 蒸馏的关系**:当前 G0–G8/P3 条款是从人工归因的崩溃台账蒸馏的;
  JEV 标签可把这一过程半自动化(条款起草仍由 LLM 做,JEV 只做样本筛选)。

### J3 仲裁的语义 tie-break(Choice)——域内空间小,域外有价值

- **现状**:min-目标值仲裁 80.5%,距 Oracle 上界 81.6% 仅 1.1pp——
  **RetailOpt 域内 JEV 仲裁最多再要 1.1pp,不值得**。
- **价值场景**:witness 缺席时仲裁失去"可行候选"过滤器,JEV Choice 直接
  在 K 个候选解中选"最符合题面语义"的一个(基数 ≤255 够用)。
- **验证实验**:回放三链台账,比较 min-obj 仲裁 vs JEV-Choice 仲裁 vs
  min-obj∩JEV 一致子集,指标 = 真实成功(witness 重判)。

### J4 预求解闸门的语义层(Noul)——补 AST 探针的盲区

- **现状**:闸门是 AST 静态探针,只查"该读的数据键读没读"这类结构信号,
  检出率 97.0%,但对"代码读起来语义就不对"无能为力。
- **契约**:生成代码(不求解)→ JEV Noul "Does this model code
  misrepresent the problem?" → 高置信违例才拦截(fail-open 纪律不变)。
- **风险**:增加每 cell 一次外部调用;闸门的核心卖点是零 LLM、确定性、
  离线可复现——JEV 层必须以"可关断的可选层"形态存在,不进默认配置。
- **优先级**:中低。AST 探针 97% 检出之后残余空间不大。

### J5 修复动作路由(Choice)——低优先级

- 现状路由是硬编码(crash→stderr;phantom→witness 清单;timelimit→契约修复)。
- E14 已证明"更丰富的修复反馈"无增益(plain 22.0% vs enriched 20.3%),
  路由选择本身的收益预期低。**记录为可选项,不投入**。

### J6 进化适应度预筛(Score)——中低价值

- 进化瓶颈在 LLM 生成(每基因组 40 题 × 长思考),不在求解与评测;JEV
  预筛只能省"求解+witness"的钱(本来就便宜),省不了生成。
- 可能的形态:对基因组的**条款文本本身**打分(不跑题,"这组惯例看起来
  合理吗")——但条款质量与下游适应度的相关性未建立,属投机。**挂起**。

## 5. 核心风险:判官被幻影系统性欺骗

这是我们与"判官路线"分道扬镳的地方,必须如实写进任何设计:

1. **幻影的成因决定它是判官杀手**:specification gaming 的产物在所有
   "看起来合理"的维度上都合格——代码干净、解结构完整、目标值甚至更优。
   plain LLM 判官对缺陷的 false-clear 率高达 90%(BargLabs 校准研究)。
2. **JEV 的校准声明在它的分布上**;RLCD 给的是"认知诚实的概率",但
   "诚实地承认自己不知道"不等于"知道"。OR 语义违例(免费库存、需求平衡
   破坏)是否在它的校准范围内,是未经验证的实证问题。
3. **LLMs Gaming Verifiers 的警告**:一旦判官进入奖励/选择回路,优化压力
   会主动寻找判官盲区——我们的进化落差实验(gen0 +15.0pp → gen1 +21.7pp)
   已经实证了这个动态在 prompt 进化中存在。用 JEV 做适应度信号必须搭配
   留出集闸门(我们的 F 纪律正好覆盖)。
4. **结论**:JEV 上线前必须过 §6 校准协议;部署形态只能是 fail-open 初审
   或冷启动脚手架;终审永远留给确定性规则。

## 6. 校准协议:witness-as-oracle(三阶段)

### P0(现在可做,零外部依赖)——替身判官校准

- 判官 = 内网 Qwen3.8-27B,提示词复刻 JEV 的 Noul 形态(题面 + 代码 +
  解摘要 → VIOLATION: YES/NO + CONFIDENCE),temperature 0。
- 样本 = `runs/m1_feedback/` 台账中带 witness 真值标签的细胞,**已核验
  316 个可用**(225 幻影 + 61 真成功 + 30 其它,8 族全覆盖;代码与
  solution.json 均在 sandbox 目录)。
- 指标:总体混淆矩阵;**幻影子集 false-clear 率**(判官说"无违例"但
  witness 判违例 —— 最致命);真成功子集 false-alarm 率;按族分层;
  置信度校准曲线(说 0.9 把握的准确率是否真的 ~90%)。
- 脚本:`scripts/judge_calibration_p0.py`(已建,dry-run 通过)。
- 论文价值(双向):若 Qwen 判官 false-clear 率高 → "为什么终审必须确定性"
  的定量证据(直接补强候选 C);若意外地低 → 判官路线在 OR 域可用的证据,
  混合架构成立。**注意**:G1 生态效度组已有小样本预兆(on 3/4 检出、
  off 0/4 检出且 3/4 误报参照解),P0 把它扩到 316 细胞。

#### P0 结果(2026-11-04 凌晨,316/316 全量,判官 = Qwen3.8-27B 无思考模式)

判官形态忠实于 JEV 的"快速非推理决策"设定(temperature 0,短答,
VIOLATION: YES/NO + CONFIDENCE)。**结果:判官路线在我们分布上不及格。**

| 指标 | 数值 | 解读 |
|---|---|---|
| 总体检出率(witness 判违例的 240 细胞) | 56.2%(漏 105) | 近一半语义违例放行 |
| **幻影子集 false-clear 率**(225 例,看起来对实则错) | **45.3%**(102/225) | 最致命的一栏 |
| 真成功子集 false-alarm 率(61 例) | 42.6%(26/61) | 双向都错,判别力接近无效 |
| 平衡准确率 | ≈53% | 仅略好于抛硬币 |
| 置信度校准 | 全部输出恒为 0.95;0.9+ 置信的"放行"判定实际干净率仅 **29%** | 置信度完全不可信 |

**按族分层(检出率)**:f3 容量瓶颈 97%、f4 78%、f5 74% —— 这些违例
"写在面上"(容量被超、需求爆量);而 **f1 仅 14%**、f6 仅 23% —— f1 正是
幻影初始库存(C-INIT)的主场:判官几乎从不发现"库存凭空出现",因为
发现它需要对题面做跨期守恒推理,而非读表面合理性。**幻影的主导机制恰好
是判官的最弱项**——这不是巧合,是 specification gaming 的必然:
被保留下来的失败模式,正是那些能骗过"合理性阅读"的模式。

**三个直接推论**:
1. 候选 C(witness 确定性审计)的差异化叙事从"判官校准文献的间接推断"
   升级为**我们分布上的直接实测**:即使把判官换成 JEV,也必须先在同类
   幻影集上复测;P1(JEV 真身对照)的必要性更尖锐了。
2. "置信度恒为 0.95"实测支持 JEV 的核心卖点(校准概率是普通 LLM 给不出
   的)——但这恰恰意味着 **P0 替身只能定判官路线的下界**,JEV 是否
   在其校准分布内仍待 P1。
3. J1(跨数据集冷启动判官)的部署门槛按 §6 P2 决策矩阵执行:若 JEV 真身
   在幻影子集 false-clear > 30%,判官路线整体不可用于终审,只能做
   高置信拦截的分流器。

实验细节:判官提示词与代码见 `scripts/judge_calibration_p0.py`;分析见
`scripts/judge_calibration_p0_analyze.py`;原始记录
`runs/judge_calib_p0/judge_p0.jsonl`(316 行,含每细胞判定、置信、原文)。

### P1(需要 JEV API key;行动在用户侧)

- 同一套 316 细胞问题集走 JEV API,与 witness 真值、Qwen 判官三方对比。
- 成本估算:316 细胞 × ~$0.0004 ≈ **$0.13**;加仲裁/路由问题形态也不到 $1。
- 工程:内网服务器出外网已验证(git push 正常);JEV 服务在美西,RTT
  ~150–300ms,离线场景无感。
- **合规前置**:外发内容 = RetailOpt-190(公开基准)题面 + 我们生成的代码与
  解。不含任何私有数据。**仍需用户拍板确认可外发**。

### P2 部署决策矩阵(校准结果 → 角色)

| 校准结果(幻影子集 false-clear) | 决策 |
|---|---|
| < 5%(与 witness 接近) | JEV 可作跨数据集冷启动判官(J1 成立),并联初筛上线 |
| 5–30% | 仅作低置信分流器:高置信违例进修复环,其余一律 witness/人工 |
| > 30% | 判官路线在 OR 语义审计不可用,写入论文(强化 witness 必要性) |

## 7. 与创新点裁决的关系(不改裁决,强化闭环)

- **不改变** D(缺陷洗白)/ E(选择放大)/ F(双层留出)主线地位。
- **C(witness 差异化)双向加强**:P0/P1 无论结果好坏都产出论文级证据。
- **E 新增佐证角度**:若用 JEV 作进化适应度信号,必须配 F 纪律——
  "判官进奖励回路会被钻空子"我们已有域内实证。
- 相关工作新增条目:System One/RLCD(决策模型作为验证器组件),与
  LLM-as-judge 校准文献并列。

## 8. 行动清单

**用户侧**:
1. 拍板:RetailOpt 题面+解是否可外发到 JEV(美国)API?
2. (可选)注册 TypeSafe early access 拿 API key。

**我侧**(按主线空档穿插,不抢跑批资源):
1. ~~P0 脚本骨架~~(已完成,dry-run 通过)
2. gen3 跑批结束后:P0 冒烟(3 细胞)→ 全量 316 细胞(估算 ~316 次调用,
   约 0.5–1 小时端点占用)
3. P0 结果回填本文档 §6 表 + 按结果更新 novelty_audit 的候选 C 表述
4. 若用户拿来 JEV key:P1 对照实验

## 9. 开放问题(诚实记录)

1. JEV 对"题面→解"的语义违例判断是否在其 RLCD 校准分布内?无任何公开
   证据,只能实测。
2. JEV 的 255 基数两阶段在 K 候选仲裁(K≈9–15)下够用,但"选项间相关性"
   如何处理未见公开细节。
3. 替身协议的有效性:Qwen 判官与 JEV 的差距可能很大(一个生成模型、一个
   决策模型),P0 结果只能定"判官路线"的下界,不能替代 P1。
4. explainx 复核提到的 one-token LLM 技巧(Privatemode)值得复刻:若
   "Qwen 限单 token 输出"就能逼近决策模型的校准度,P1 可能根本不需要
   外部 API——这本身是 P0 的一个免费变体臂(改 max_tokens=1 或 logprobs
   取 YES/NO 概率)。

## 10. 开源替代调研(2026-11-04,应用户要求)

### 10.1 JEV 本体的部署形态

JEV **只能调 API**。TypeSafe AI 未发布权重、参数量、完整架构与 RLCD
训练配方,无 self-hosted/on-prem 选项,模型只跑在 TypeSafe 基础设施上
(Sanity glossary / Wikipedia / RedBlink 多源一致)。当前为 early access
waitlist 制。数据出境与第三方依赖是其对我们的两大结构性障碍。

### 10.2 开源可自部署替代(三类,全部实测可查)

**A 类:System One 复现**(同形态:非自回归、单次前向、类型化决策 +
校准置信度;社区生态见 VoltAgent/typesafe-jev-ecosystem 精选表):
- **Open-Jev-27B**(Zefan-Cai/Open-Jev,v1.1)——**基座就是
  Qwen3.8-27B,与我们 pipeline 同基座**;TypeSafe 兼容 API,JevBench
  审计结果公开;配套方法论文 arXiv:2610.17205 "Releasing the Inner Jev"
- **kev**(★8.7k)——Qwen3.5/3.8 系决策模型族,可自训自跑
- **decider**(★1.1k)——Qwen3.5 微调,单次前向类型化决策 + 校准概率
- **laya**(★31.7k,Convai Innovations)——ModernBERT 系非自回归决策
  引擎,Apache 2.0,100+ 语言;ollaya 可本地起 TypeSafe 兼容服务
- **so1 / open-alternative-jev**(ikermoel)——把任意开源 LLM 一次前向
  包装成类型化校准决策模型(HF + vLLM),带 honest benchmarks
- AWS **Strands Decider 2B**——AWS 开源的 Jev 启发决策模型
  (来源为二手报道,强度较弱,待直接核实)

**B 类:LLM 判官**(System Two 系,生成式):
- **CompassJudger-1/2**(上海 AI 实验室 OpenCompass;Qwen2.5-7B/32B
  基座,Apache 2.0;第 2 代用 verifiable rewards 训练,
  arXiv:2507.09104)

**C 类:奖励模型**(打分头,可作 Score 近似):
- **Skywork-Reward-V2**(昆仑万维;Qwen3 / Llama-3.1 基座,
  0.6B–8B 共 8 款,Apache 2.0,ModelScope 国内可下,发布时七榜 SOTA)
- **DeepSeek-GRM-27B**(DeepSeek;推理时扩展通用奖励模型路线)

"国内二次开发可用"的准确图景:A 类的 kev/decider/Open-Jev **全部是
Qwen(阿里)基座的二次开发**,Open-Jev-27B 干脆与我们同基座;B/C 类
本身就是国内团队作品。无需等"国内版 JEV",开源生态已经长在 Qwen 上。

### 10.3 推荐融入方案(详设)

**总原则:witness 仍为唯一终审(P0 已证明为什么);System One 模型只作
校准分流器与弱标签机,永不单独放行。**

架构(在现有三层校验之外增加一层,不改动现有链路):

```
L0 确定性检查(现有): 语法/执行/求解器状态 —— 零成本
L1 System One 分流器(新): Open-Jev-27B,一次前向 ~100ms/细胞
     高置信违例 → 直接进修复环(跳过 witness 前的盲目重试)
     其它         → 照常进 witness
L2 witness 确定性审计(现有,终审,永不旁路)
L3 参考解对题(现有,仅数据集有真值时)
```

L1 的真实价值不在域内(witness 是零成本 python,域内无替代必要),而在:

1. **J1 跨数据集冷启动判官**:换数据集(如 IndustryOR)时 witness 规则
   为空,L1 是唯一的语义初筛;其幻影 false-clear 率决定它在冷启动期
   能承担什么角色。
2. **J2 轨迹弱标签批量生产**:RQ2 反例监督训练需要远超 316 的标注轨迹;
   witness 只能标已枚举规则覆盖的部分,L1 给其余细胞打弱标签蒸馏进
   训练集。
3. **校准自主权**:RLCD 是 TypeSafe 的秘方,但我们有 witness 真值标签
   (316 细胞且随跑批增长)——对开源模型原始概率做 Platt/isotonic
   校准,得到的是**我们分布上**的校准置信度;JEV API 的校准分布在
   通用域,这一点官方 API 反而给不了。

**为什么选 Open-Jev-27B 而非其它**:与我们 pipeline 同基座
(Qwen3.8-27B),消除"模型能力差异"这一混杂变量——若它也抓不住幻影,
结论是"System One 形态"的失败而非"模型太小/太弱";这正补在 P0
(Qwen 直球判官 45.3% false-clear)与 witness(误报 1.9%/0%)之间的
证据链缺口上。

**评估协议(沿用 P0/P2,不变更口径)**:同一批 316 个 witness 标注细胞、
同一杀手指标(幻影子集 false-clear 率),按 §6 P2 决策矩阵裁决:
<5% → J1 成立可冷启动;5–30% → 仅作高置信分流器;>30% → System One
路线在 OR 语义审计判死,写入论文("System One 抓不住 System Two 幻影"
本身即是发现:幻影主导机制=跨期守恒推理,是模式匹配形态的结构性盲区)。

**成本与资源**:2 卡 A800(27B bf16 ≈54GB,vLLM)即可自部署;316 细胞
每细胞一次前向,秒级完成,成本主要是部署调试;零数据外发、零 API 费用。
JEV 官方 API 降级为可选对照项(若用户拍板数据外发 + 拿到 early access),
不再是依赖。

**行动序列**:
1. 克隆 Open-Jev / kev 仓库,核实部署需求与许可证,写 316 细胞适配脚本
   (复用 judge_calibration_p0.py 的细胞装载与分析器,只换判定后端)
2. 申请 2 卡 A800,部署 Open-Jev-27B,冒烟 3 细胞
3. 全量 316 细胞 → 三方对比表(Qwen 判官 vs Open-Jev vs witness)
4. witness 标签 Platt/isotonic 校准,出校准曲线
5. 按 P2 矩阵裁决 J1;结果回填本文档与 novelty_audit 候选 C

---

来源:
- TypeSafe 官方发布博客(2026-09-15):https://typesafe.ai/blog/introducing-system-one-models-and-jev
- LangChain 实测(Jev-as-a-Judge,2026-09-20):https://www.langchain.com/blog/jev-agent-evals-langsmith
- Jev 无自部署形态(Sanity glossary,2026-10):https://www.sanity.io/glossary/jev-typesafe-ai-model
- 开源生态精选表(VoltAgent,2026-10-10):https://github.com/VoltAgent/typesafe-jev-ecosystem
- Open-Jev-27B(Zefan-Cai,2026-09):https://github.com/Zefan-Cai/Open-Jev;方法论文 arXiv:2610.17205
- CompassJudger-2(上海AI Lab,2025-07):arXiv:2507.09104
- Skywork-Reward-V2(昆仑万维,2025-07):ModelScope Skywork/Skywork-Reward-V2 系列页
- explainx 独立复核(2026-09-27):https://explainx.ai/blog/jev-speed-cost-claims-fact-check-2026
- 判官校准研究(BargLabs,2026-09;plain LLM 判官 false-clear 率):见
  `docs/paper/novelty_audit_v0.1.md` 候选 C 节引注
- 我们内部的 witness 必要性证据:F10/E2(`motivation_findings_v0.1.md`)、
  G1 生态效度组(同上 §G1)

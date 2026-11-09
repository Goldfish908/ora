# Guard 规则自动进化 R1(2026-11-09)

**自动进化的第一个正收益实证。LLM 提议 + 离线自动验证 + 反例细化,
全程 2 次 LLM 调用,零 LLM 重放成本。**

## 流程与发现

### 1. 失败簇分析(离线)
对 guard3 环路+pilot 台账的 18 个残余 crash 细胞逐一复查:
- **14/18 规则已命中,是环内 budget 放行**(guard_turns=1 修一次没修好
  就执行)——残余 crash 的主因是环内策略,不是规则缺口。
  → 环内改进项:crash 类失败应 fail-closed 或加修预算(另立项)。
- **4/18 真规则盲区**:3 个 expr_compare 变体 + 1 个 KeyError(自替代边)。

### 2. LLM 提议(1 次调用)
给 LLM 最小复现+G11 源码,要求诊断+最小补丁。
诊断正确:`_exprish` 的 Call 名单只认 `quicksum`,不认 Python 内置
`sum()`——`out_sub = sum(sub[...] for ...)` 产生 Expr 但未被污点标记,
后续 `if out_sub != 0` 逃逸。

### 3. 自动验证 → 反例 → 细化(CEGIS)
- 初版补丁(把 `sum` 加进 Call 名单):3 盲区全检出,但**纯数字
  `sum(costs)` 误报** → 违反 win-FP=0 纪律,打回。
- 细化:`sum` 改为**递归检查输入是否 tainted**(生成器 .elt / 容器
  元素),新增 GeneratorExp/List/Tuple/Set/Dict 分支。
- 复验:盲区全检出 + `sum(costs)`/`sum(demand[p]...)`(dict of float)
  均不误报。

### 4. 全量离线回归(380 round-1 细胞,零 LLM)
| 指标 | 补丁前 | 补丁后 |
|---|---|---|
| crash 检出 | 257/263 (97.7%) | **260/263 (98.9%)** |
| win 误报 | 0/13 | **0/13** |

## 对 RSI 设计的意义

- 验证了 R1 判断:**确定性资产的进化信噪比远高于软条款**——验证零
  LLM 成本、零采样噪声、秒级出结果;对比 memory 条款 gen1(3 种子重放、
  翻转率 75%、gapcheck 被拦)。
- CEGIS 细化在规则资产上自然闭环:误报反例直接驱动补丁修订,无需
  LLM 再介入(细化由 agent 完成;全自动版可再加一次 LLM 调用)。
- 环内 budget 放行(14/18)提示:**下一层进化对象是环内策略本身**
  (crash 时 guard 放行预算),与元层进化(R6)衔接。

代码:`scripts/guard_check.py`(_exprish 的 sum/GeneratorExp/容器分支)

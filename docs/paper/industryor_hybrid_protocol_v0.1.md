# IndustryOR 完整管线与 Raw Selected 混合选择协议 v0.1

## 目的与边界

在不修改两个已冻结输入的前提下，评估完整结构化管线和 raw k=3 selected 的候选互补性。输入分别为 `work/industryor_structured_full_v0.4` 的 full-memory 最终输出和 `work/industryor_k3_dev_v0.1` 的无参考答案选择输出。两者都是开发性采样，不是 held-out；本实验新增的是混合选择，不把候选池 oracle 当作可部署结果，也不声称官方 COOPA 或未经复现的 SOTA。

## 冻结选择规则

1. 两个候选分别标记为 A（完整结构化 full-memory）和 B（raw k=3 selected）。任何 prompt 都不得包含 `en_answer`、参考目标值或历史正确性标签。
2. 若一方具有注册题的独立业务接受，则确定性选择该方；双方都有时选择 A。
3. 两者目标值相同（包括都不可用时）选择 A，不调用 LLM。
4. 若一方缺乏完整 `optimal` 执行、完整导出和有限目标值，而另一方具备，则选择执行完整的一方，不调用 LLM。
5. 其余候选调用现有 `selector_prompt` 与 `choose_with_llm`，由 Qwen3.8-27B 根据题面、代码、执行与业务证据给出 variables、parameters、constraints、objective 四维置信度，使用 max-min 选择。temperature=0.2、reasoning_effort=medium、max_tokens=16384。
6. LLM 错误或返回无效时回退 A，并保留失败记录。不得根据参考答案改选。

## 报告与验证

逐题保存选择 prompt、原始响应、置信度、选择来源、最终代码/执行/业务状态和新增成本。报告完整 100 题的公开目标匹配、相对两个输入的增益与损失、注册业务审计、误接受、win 保留、调用和 token。候选并集只作事后上界。运行完整 pytest 与 m2gen 回归，保存 analysis、manifest、报告和结果图。

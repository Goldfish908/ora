# IndustryOR k=1/k=3 候选生成与选择协议 v0.1

## 目标与边界

比较同一题一个候选（k=1）和三个独立 formulation 候选（k=3）的公开目标匹配与业务证据。先不叠加 memory、额外 repair 或外环进化，避免混淆候选多样性、选择器和修复的贡献。

IndustryOR-100 已用于历史开发，本轮仍属于开发性新采样对照，不是 held-out。公开 COOPA=76 仅作为同数据、同绝对误差口径的参考线，不能因单次超过就宣称 SOTA。

## 生成

每题 A/B/C 三次独立调用，使用内网 Qwen3.8-27B、z2 工程先验和 SCIP 输出契约。`temperature=0.6`、`reasoning_effort=medium`、`max_tokens=32768`，不使用 `en_answer`、参考解或参考目标。

k=1 与 k=3-first 共用 A 的原始响应和执行结果，不重复计费。B/C 与 A 使用相同 prompt，不通过不同提示词人为制造某臂优势。不假定服务端支持显式 seed。

## 执行与绑定

每个候选分别执行 PySCIPOpt/SCIP，保存原始代码、插桩代码、stdout/stderr、solution 与成本。对 4/8/9/19/20/21/25/48 使用独立业务 scorer。先尝试免费规范名绑定，不足时由内网 Qwen 提出带代码证据的绑定；绑定调用单独计成本。其余 92 题保持 `business_unverified`，不冒充业务接受。

## 选择

k=1 直接使用 A。k=3 先检查独立业务正确候选；若有，按 LLM/SCIP 成本和字母序选择，不调用选择器。

没有业务正确候选时，由 Qwen 对三个候选的 variables、parameters、constraints、objective 四维 confidence 打分。选择器只获得题面、候选代码、执行状态和业务证据，不获得 `en_answer` 或候选与参考值的差。程序按 max-min confidence 确定候选，校验 JSON、候选 ID、有限数值和选择一致性；无效时明确回退到 A，不读取参考答案挽救。

本轮不增加 repair。这样可以分别测量候选池、选择器和公开最终输出。

## 指标与禁止事项

- k=1：A 的绝对误差 ≤0.1 的目标匹配。
- k=3 selected：按上述无答案规则选中候选的目标匹配与业务结果。
- k=3 oracle：事后从三个候选中挑误差最小者的目标匹配，**只作为候选池上界，不是可部署方法，也不得用于 SOTA 声称**。
- 分别报告执行率、optimal、独立业务正确、错误选择、LLM 调用、tokens、真实延迟和 SCIP 次数。

保存每题全部 prompt、原始响应、绑定、执行、选择、成本、失败和 UNKNOWN。缓存不冒充新调用，运行版本与实现文件快照写入实验目录。

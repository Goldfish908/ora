# IndustryOR 完整管线与 Raw Selected 混合选择

**范围：100 题，开发性冻结候选重放，不是 held-out。** 不使用 raw oracle 或参考答案选择。

| 输出 | 目标匹配 abs≤0.1 | 独立业务正确（8题） |
|---|---:|---:|
| raw k=3 selected | 66 | 3 |
| structured full memory | 74 | 7 |
| hybrid selected | **78** | 7 |

相对 full：新增 IDs=[59, 76, 88, 97]，丢失 IDs=[]。
相对 raw：新增 14，丢失 2。
误接受=0；来源={'raw_selected': 10, 'structured_full': 90}；选择方式={'llm_max_min': 18, 'same_objective_preserve_full': 64, 'independent_business': 7, 'complete_execution': 11}。

## 新增选择成本

```json
{
 "logical_llm_calls": 18,
 "new_llm_calls": 18,
 "api_attempts": 18,
 "completion_tokens": 79555,
 "total_tokens": 119714,
 "llm_latency_s": 799.341,
 "new_llm_latency_s": 799.341
}
```

输入生成成本分别保留在原 full/raw 报告中；此处只计混合选择新增调用，不把缓存复用冒充新请求。
COOPA=76 仅为不同模型和配置的公开参考；本结果是 COOPA-inspired 开发重放，不据此宣称 SOTA。

机器结果：`work/industryor_hybrid_replicate_v0.6/analysis.json`；manifest：`work/industryor_hybrid_replicate_v0.6/manifest.json`。

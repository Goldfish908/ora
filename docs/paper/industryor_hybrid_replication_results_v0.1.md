# IndustryOR 混合选择独立复现

**范围：同一批冻结候选上的三次独立选择采样，不是整条生成管线重采样，也不是 held-out。**

| Run | 目标匹配 | 相对 full 新增 | 相对 full 丢失 | 独立业务正确（8题） | 误接受 | 新增选择调用 |
|---|---:|---|---|---:|---:|---:|
| run_1 | 77 | [59, 76, 97] | [] | 7 | 0 | 18 |
| run_2 | 76 | [59, 76, 88] | [18] | 7 | 0 | 18 |
| run_3 | 78 | [59, 76, 88, 97] | [] | 7 | 0 | 18 |

min/mean/median/max = 76/77.00/77/78；全部三轮 >76：**False**。
每轮都直接输出实际选择结果，不用三轮多数票或候选池 oracle 代替。COOPA=76 是不同模型和配置的公开参考，本复现不据此宣称 SOTA。

机器结果：`work/industryor_hybrid_replication_v0.1/analysis.json`；manifest：`work/industryor_hybrid_replication_v0.1/manifest.json`。

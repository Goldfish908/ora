# J1 跨数据集判官 v1 — 结果与裁决

日期: 2026-11-04
状态: 完成(名义阳性,审计存疑 → 判"证据不足",进入 J1.1)
远程产物: /dfs/data/hewj13/j1_judge/(adapter_ep1/, metrics.json, README.txt)
本地副本: work/j1_judge/remote_ref/

## 结果速览(IndustryOR 240 细胞: 61 错 / 179 对)

| 方法 | AUC | det@t=0.5 | FP@t=0.5 |
|---|---|---|---|
| **J1 judge(adapter_ep1)** | **0.678** | **19.7%** | 5.0% |
| Open-Jev off-the-shelf | 0.662 | 1.6% | 0.0% |
| 自一致性 | — | 16.4% | 5.0% |
| D2 规则门 | — | 9.8% | 5.6% |

训练:1 epoch / 316 steps,loss 0.687→0.231 分段下降,27.9s/step,共 2.49h,
峰值显存 29.4G/34.0G(与 way2m 共卡无碍)。

## 红旗:分布内 sanity 失败

- 同一 adapter 在自己训练过的 316 个 RetailOpt 细胞上 AUC 仅 0.569
  (wrong/pass 两侧 p_fail 均值 0.463 vs 0.458,几乎无分离)——低于分布外的 0.678。
- 自由生成模式下 verdict token 坍缩:对全部 240 个测试细胞输出同一句背诵的
  pass 模板;只有强制前缀打分的 p_fail 通道有信号。
- p_fail 分布为中心 ~0.44 的窄钟形,t=0.5 的 det/FP 对阈值极敏感。

**裁决:1 epoch 未让 verdict token 学到稳定判别信号(loss 下降主要来自模板与
reason 文本记忆);测试集的领先是弱且不可靠的证据,不能声称迁移成功。**

## J1.1 修复清单(远程 README §5)

1. 训满 2-3 epoch,以"分布内 AUC→1"为继续前提;
2. verdict token 单独加 loss 权重(目前仅是 ~43 个监督 token 中的 1 个);
3. 启用剩余 65 个已标注未用细胞;
4. pass 的 reason 改非常量句式(防模板记忆)。

## 对 N4 决策的影响

判官路线未被证明也未被证伪。鉴于 P2 剧本(97.5%)已独立证明修复方向的
数据价值,1k 扩产先投**修复器 SFT 数据**;判官线按上面四条做 J1.1 迭代
(GPU 侧,不占 API),两轮后再定检出端架构。

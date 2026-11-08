# 判官(Semantic Judge)v3:训练与分布内终评报告

版本 v1.0 · 2026-11-08 · 状态:分布内(dev70)已完成;跨族(F5–F8)与跨数据集(IndustryOR)评测在途

---

## 1. 定位

判官是分层业务世界模型的 **L2 直觉层**:一个参数化的语义审计器,用于 witness(L1 确定性规则)尚未覆盖的域——做冷启动初筛(fail-open:高置信才拦截,拿不准放行),并把判定积累成弱标签喂养规则自动生成(checker-authoring),规则成熟后退休。**终审权永远在 witness,不下放。**

## 2. 训练配置

| 项 | 值 |
|---|---|
| 基座 | Qwen3.8-27B(HF 快照,BF16) |
| 方法 | LoRA r=16, alpha=32, target=all-linear;可训练参数 116,727,808(0.43%) |
| 数据 | 868 条(dev40 工厂细胞,witness 判定 ∪ 参考解比对为标签;变异细胞标签构造保证);拒绝采样自教师(thinking on)的推理轨迹,target 为完整推理 + VERDICT 行 |
| 评测集 | dev70(70 条:46 错 / 24 对),dev 与 train 按 scenario 确定性 9:1 切分 |
| 超参 | LR 1e-4,MAXLEN 8192,EPOCHS 3,2×A800 80GB,~36s/步,共 2604 步(~26h) |

## 3. 训练曲线(score-based AUC,dev70)

| epoch | AUC | 备注 |
|---|---|---|
| 1 | 0.6821 | |
| 2 | 0.8075 | |
| 3 | 0.8102 | +0.003,平台期——868 条数据已被吃满,瓶颈在数据量/多样性而非训练轮数 |

## 4. dev70 生成式终评(真生成推理+判决解析,40 细胞:23 错/17 对)

准确率 77.5%,unparsed 0,hard-label AUC 0.804(与 score-based 0.810 互证,推理链路健康)。

混淆矩阵:

| | 判 INVALID | 判 VALID |
|---|---|---|
| 实际错误 (23) | **14(检出 60.9%)** | 9 漏检 |
| 实际正确 (17) | **0(误报 0.0%)** | 17 |

分变异类型:

| 变异类型 | 检出 | 基线对照 |
|---|---|---|
| phantom_inventory(幻影初始库存) | **12/12 = 100%** | 裸 Qwen27B 误放行 45.3%;Open-Jev-27B 误放行 99.6% |
| wrong_constant | 2/6 | — |
| drop_constraint | 0/5 | 解摘要中不留可见痕迹,是已知弱点 |

判读:
1. **旗舰失败模式(幻影)达到确定性规则级可靠性**(100% 检出 + 0 误报),且生成理由显示它在做机制级分析(指出 non-fresh buckets at t=1 未被强制为零),不是模式匹配。
2. **零误报验证 fail-open 定位**:正确解无一冤案,初筛位置安全。
3. 弱点:drop_constraint 类从解摘要中不可见——指向数据增强方向或解摘要信息量上限。

## 5. 三层评测设计(对应分层世界模型故事的可证伪预测①)

| 层 | 集合 | 检验什么 | 状态 |
|---|---|---|---|
| L1 分布内 | dev70(F1–F4 留出细胞) | 学会了吗 | ✅ AUC 0.810,幻影 100% |
| L2 跨族 | eval_f5f8(48 细胞:34 错/14 对,真实轨迹) | 学到业务物理还是记住模板 | 在途(脚本 `scripts/p7_build_judge_eval_f5f8.py`) |
| L3 跨数据集 | eval_industryor(240 细胞:61 错/179 对,z0/z1/z2 三臂) | 换数据域还能用吗 | 细胞已冻结(脚本 `scripts/p8_build_judge_eval_industryor.py`),待 GPU 恢复 |

L3 对照臂:Open-Jev-27B 已有零样本成绩(`runs/industryor/industryor_judge_openjev.jsonl`,p_violation 分数);计划补 Qwen27B 零样本臂(同 JUDGE_PROMPT,隔离"训练"这一变量),形成三方公平对决。

## 6. 远端资产清单(DFS,持久)

- `/dfs/data/hewj13/j3_judge/adapter_v3_ep{1,2,3}`(选优:ep3,AUC 0.810)
- `train_v3.jsonl`(868)/ `eval_v3.jsonl`(70)/ `eval_f5f8.jsonl`(48,sha256 75004bd0…)
- `eval_gen.py`(独立生成式评测脚本,env: EVAL_FILE/ADAPTER/OUT/N/MAX_NEW)
- `logs/gen_eval_v3.jsonl`(dev70 终评 40 条)/ `logs/eval_f5f8.out`(F5–F8 评测输出,关机时 46/48)

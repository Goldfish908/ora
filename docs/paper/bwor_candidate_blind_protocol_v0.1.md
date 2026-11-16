# BWOR 历史候选的候选盲评估协议 v0.1

状态：在读取以下候选的响应内容、旧评分或修复结果之前登记。只检查过参考合格列表和输入文件是否存在。

## 目的与限制

验证当前契约归一化、scoped 资产和控制器在**本管线尚未检视的六个历史候选**上的表现。它们是此前生成并落盘的输入，不是本轮新生成；问题也曾用于旧系统，因此不是全系统首次 frozen，不与旧生成器作因果比较，不称 SOTA。

候选盲指本阶段机制设计和开发人员尚未读取这些候选的内容和结果。不能据此推断其他历史工作从未见过这些题。

## 队列与暴露

按 `work/dvsa/bwor_reference/frozen/summary.json` 的 eligible ID 顺序，排除已经完成开发的六题后，取接下来六题：

```text
BWOR-013, BWOR-018, BWOR-019, BWOR-021, BWOR-024, BWOR-025
```

输入：`work/dvsa/bwor_repair/frozen/<ID>/initial/`。六题的 response/result 均存在，prompt 缺失时记录缺失而不补造。参考模型是此前盲建、经公开目标校验的参考，不是专家金标；参考表达式只能用于已登记的 reference-bound 修复。

## 执行前冻结的实现

- `ora_agent/dvsa_model.py`: `e690e5eafe87dc615fc31c2d3712586997eea55fd6a06e40db12dc8ae18da670`
- `scripts/bwor_saved_contract_replay.py`: `e22b5bfb88faf19c92c7bf40e311c7a1988c04d2e4dc70ff9d817e05ece2a82f`
- `scripts/bwor_scoped_loop.py`: `d424a10817465008137afaf0645174459b86d45d223263192faa8915b104c3fd`
- `scripts/frozen_scoped_evaluate.py`: `699a62af894ced669c673080b518dbb008fe7297589e4405c4cd1e5ac0d89e46`

复用当前变量列表、数据路径、列表索引归一化与 fail-closed 检查。禁止在本轮结果出来后调整这些实现来制造改善。

## 对照和判定

六题全部进入，不挑选、不补题、不重新生成，新 LLM 调用为 0。求解时限 60 秒；no-repair、fixed、progress 共享归一化初始，最多两次确定性修复，资产 gate 不接受 UNKNOWN 或 rejected。

记录初始旧评分（若存在）、当前初始评分、每轮模型/解、动作、独立参考评分、求解和 LLM 成本。契约归一化带来的变化与修复环增益分开统计；fixed/progress 同效不归因控制器。

主要指标：独立正确数、业务恢复、round-0 保留、`harmed_win`、`accepted_but_reference_incorrect`、UNKNOWN、求解次数和成本。出现误接受或 harmed-win 即停止扩展。无论结果正负均保存，不修改队列或标签。

```bash
/home/hewj13/planbb/miniforge3/envs/rl/bin/python3.9 scripts/bwor_candidate_blind_replay.py
```

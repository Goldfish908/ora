# P2: Retrieval-Conditioned Repair Playbook (2026-11-04)

## Motivation
P1 factory final: phantom_inventory repair succeeded only 17.5% (7/40);
32/40 failures burned all 3 rounds emitting near-identical code — the
model cannot restructure a model it does not understand is wrong.
Question: can a *playbook distilled from verified fixes* (same dev40 data
budget a LoRA SFT would get, zero weight updates) rescue these failures?

## Method
- Card authoring (scripts/p2_repair_hints.py): take <=4 VERIFIED
  (broken -> repaired) factory pairs of the same mutant class (disjoint
  scenarios from the failures), show violation text + unified diff,
  distill a ~200-word playbook: RECOGNIZE / ROOT CAUSE / CANONICAL FIX /
  PITFALLS. Cached at runs/p2_hints/card_phantom_inventory.json.
- Rescue: for all 33 factory phantom_inventory samples that were NOT
  fixed by the generic loop, re-run the same <=3-round repair with the
  playbook prepended. Verification unchanged: witness zero violations
  AND |objective - gold| <= 1e-3 (gold never shown to the repairer).

## Result
- **32/33 rescued (97.0%)**, 31 of them in a SINGLE round.
  Baseline on these exact samples: 0/33 (all stuck at max rounds).
- Phantom_inventory total: 7 + 32 = **39/40 = 97.5%** (was 17.5%).
- Factory overall with playbook: (24 + 22 + 39)/104 = **81.7%**
  (was 51.0%).
- Sole failure: retail_f1_52_weeks_v0 — repair still leaves C-INIT
  violations all 3 rounds (better_than_reference grade).

## Interpretation & caveats
- The playbook carried the decisive semantic fact: "initial-inventory
  buckets I[p,l,1,r] for r<SL are unconstrained unless explicitly zeroed;
  add m.addCons(I[(p,l,1,r)]==0)". One distilled sentence replaced 3
  rounds of flailing.
- This is evidence FOR the repair-training thesis, not against: the card
  is exactly the conditional knowledge a parametric repairer must
  internalize to work *without* retrieval at inference time.
- Caveats: (1) mutant class was known (we selected the samples); in
  deployment the witness rule family (C-INIT) provides this routing
  signal. (2) Transfer measured within RetailOpt F1-F4 scenario family;
  cross-dataset transfer is the J-track question. (3) The injected bugs
  are of a known-fixable class by construction — the claim is
  "conditional retrieval >> unconditional iteration", not "all semantic
  errors are fixable".

## Next
- Extend cards to wrong_constant / drop_constraint residual failures.
- JEV/OpenJEV hook: playbook text is the natural "experience" unit to
  evolve; failure-driven card revision (a card that fails to rescue gets
  refined by its own rescue trajectories) is the non-parametric
  evolution loop.

## Addendum 2026-11-04: held-out family transfer (F4) — already satisfied

The phantom_inventory card was distilled from 4 verified successes in
families F1 (x2), F2, F3 only (retail_f1_base_v0, retail_f1_high_waste_v4,
retail_f2_circular_sub_v0, retail_f3_volumetric_constraint_v0). The 33
rescued failures span F1-F4; family F4 was therefore a true held-out
family with respect to the card. Per-family rescue rates:

| family | rescued | total | note |
|---|---|---|---|
| F1 | 5 | 6 | card families |
| F2 | 11 | 11 | card families |
| F3 | 7 | 7 | card families |
| F4 | **9** | **9** | **held-out; all 9 one-shot** |

Overall 32/33 (97%), and 31 of the 32 were rescued in a single round.
The held-out family shows no degradation (9/9 one-shot), i.e. the card
captures a family-general mechanism (uninitialized bucket inventory at
t=1), not family-specific patches. Cross-dataset transfer (IndustryOR)
is tracked separately (N3b).

## Addendum 2026-11-05: 扩产后三类变异全量营救 —— 整体修复率 50.3% → 90.5%

工厂扩产到 600 对(F1-F4 × 100 题 × 3 变异 × 2 注入种子,507 有效)后,
按 N3b 的教训**按变异类型分别蒸馏卡片**(幻影/错常数/删约束各一张,
蒸馏例子里不含 F4 族以保持 held-out),对全部基线失败样本重跑营救:

| 变异类型 | 基线修复 | 卡片营救失败样本 | 合计 |
|---|---|---|---|
| phantom_inventory | 49/200 (24.5%) | 142/150 (94.7%) | **191/200 (95.5%)** |
| wrong_constant | 103/140 (73.6%) | **33/33 (100%)** | **136/140 (97.1%)** |
| drop_constraint | 103/167 (61.7%) | 29/62 (46.8%) | **132/167 (79.0%)** |
| **合计** | **255/507 (50.3%)** | **204** | **459/507 (90.5%)** |

要点:
1. 错常数卡片 33/33 全救回 —— "按类配卡"在非幻影类上同样成立。
2. 删约束类营救率 46.8% 明显偏低:删掉的约束族不同(库存平衡/产能/可用性
   混杂),一张卡片仍盖不住 → 进一步印证"失败聚类同构"是剧本生效前提;
   下一步可对删约束按违例规则(C-BALANCE/C-PRODCAP/C-AVAIL)再细分卡。
3. 营救全部经 witness 零违例 + gold 目标值匹配验证;gold 不进提示词。
4. 数据产出:SFT/DPO 各 459 条(scripts/p3_build_sft.py,90/10 按题划分
   train/dev,F5-F8 零接触;卡片内容不进 prompt,知识由参数内化)。

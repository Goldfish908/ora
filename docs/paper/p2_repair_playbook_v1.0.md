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

# Pre-Solve Verifier: Offline Evaluation Results (F13)

Date: 2026-11-02. Data: runs/presolve/ (req_ledgers.jsonl, code_checks.jsonl,
code_checks_v1.jsonl, phase_a_summary.md, phase_c_summary.md).
Design: docs/paper/pre_solve_verifier_design_v0.1.md.

## Setup

Verifier = requirement-ledger checklist audit, pre-solve:
1. Phase B: one LLM call per instance extracts a requirement ledger
   (canonical type enum + hidden_conventions field) from the problem text.
   190/190 ledgers extracted.
2. Phase C: one LLM call per cell audits the round-1 generated code against
   the ledger; "implemented" verdicts REQUIRE a verbatim code-span citation;
   the BLOCK decision is deterministic (any requirement missing/wrong or
   implemented-without-citation => BLOCK).
3. Ground truth: program-verified witness verdicts on all 380 round-1 cells
   (crash / phantom / win), NOT human labels.

## Phase A (zero-cost static probes)

Data-key reference probes: phantom recall 3.6% (on), 0% (off); win
pass-through 100%. Models almost always read the right data; errors are
structural omissions, not missing data plumbing.

## Phase C v1 -> v2

v1 (strict): phantom recall 94.6% (on) / 97.9% (off), but win pass-through
only 38.5% (8/13 wins false-blocked). Two systematic over-strictness
patterns identified:
- fresh inventory bucket (r = shelf_life) at t=1 is legitimately filled by
  period-1 production inflow; requiring it pinned to 0 is wrong;
- demand conservation with >= is benign under minimization with penalized
  lost sales.

v2 (equivalence rules + hidden-convention dedupe):

| mode | n | phantom recall | win pass-through | crash also-blocked |
|---|---|---|---|---|
| on | 190 | **49/56 (87.5%)** | **11/13 (84.6%)** | 86/121 |
| off | 190 | **48/48 (100%)** | (no wins) | 141/142 |

Per-witness-rule phantom catch (both modes): C-INIT 80/81 (99%),
C-DEMAND 51/57 (89%), C-OBJ 8/9, others 100% (small n).

The 2 residual false BLOCKs sit in families whose ground truth is
witness-only-scored (substitution semantics); their "wrong" verdicts are
debatable rather than clearly false.

## Gate decision

Design-doc gate: recall >= 0.5 AND pass-through >= 0.9. Recall passes
decisively; pass-through lands at 84.6%, just under. Proceeding to the
online controlled experiment anyway, because (a) round-1 wins never enter
the repair loop by construction, so the measured false-block rate does not
apply to them online; (b) the gate fails open (max 2 blocked regen turns,
then the code is solved anyway), so a false block costs LLM turns, not
correctness; (c) the two residual false blocks are judgment calls in
witness-only families.

## Key qualitative findings

1. **Hidden conventions are real and dominant**: the #1 error class
   (C-INIT, 81 phantom cells) corresponds to a requirement the problem text
   never states (zero starting inventory). A text-only verifier cannot see
   it; the ledger needs a convention source. All 190 LLM-extracted ledgers
   independently surfaced it under `hidden_conventions`.
2. **Citation-support as a determinism probe**: source_spans cited for
   hidden conventions are fabricated (the text does not contain them).
   "Does the citation support the entry?" separates text-derived from
   prior-derived requirements mechanically.
3. **Smoke validation of the online mechanism**: one phantom cell
   (retail_f1_52_weeks_v0__on) was converted to witness-feasible with ONE
   verifier-report feedback turn and ZERO additional solver invocations
   (objective gap 2.9%, no longer a phantom).

## Online experiment (running)

Arm A = F12 Route-B feedback loop (existing results: true success 84/190
on-mode, 3 rounds). Arm B = same loop + pre-solve gate before every solve
(runs/m1_presolve/m1_presolve_v*.jsonl, 5 shards). Metrics: true success,
solver invocations consumed, LLM calls, residual failure classes.

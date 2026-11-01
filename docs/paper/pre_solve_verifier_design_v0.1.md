# Pre-Solve Verifier Design v0.1

Date: 2026-11-01. Status: decision recorded, implementation starting.
Scope: ORAgent harness on RetailOpt-190 (M1); portable to ORAgentBench tracks later.

## 1. Problem

Current pipeline failure profile (F10/F12, 380 cells, Qwen3.8-27B):

- Zero-shot true success: on 13/190 (6.8%), off 0/190.
- Dominant failure: model-generation code crashes (121/190 on-mode round-1), and
  "phantom" runs (code executes, witness rejects: 48 on / 43 off).
- Execution feedback (Route-B, 3 rounds) lifts true success to 44.2% on-mode, but each
  round costs a full solve attempt; residual errors concentrate at the specification
  interface (C-INIT: inventory initialization / phantom stock; C-DEMAND: demand
  fulfillment semantics).

A verifier placed *after model/code generation, before the expensive solve* can:

1. Convert phantom/wrong-model failures into cheap early rejections with targeted
   repair messages (save solve budget and feedback rounds).
2. Catch the residual spec-interface class that execution feedback converges to slowly.

## 2. Literature scan and selection

| Work | Verification idea | Judge type | Stage | Key result | Gap for us |
|---|---|---|---|---|---|
| SAC-Opt (arXiv:2510.05115) | Back-translate each generated constraint to NL, anchor-match against problem text, iteratively repair only mismatched components | LLM | pre-solve | Improves modeling accuracy on NL4Opt-style tasks | Judge is pure LLM; our G1 audit shows LLM judging of natural errors is weak (off-mode < coin flip, on 75%). Missing-type errors (C-INIT) are structurally invisible: back-translation compares what was written, phantoms exploit what was *not* written |
| OPTIVER (ICLR 2026 sub) | Dual-side: structure side = multi-level modeling structure (type -> variant -> constraints) distilled from text vs from model; solution side = interpreter + critic on numeric solution | LLM | both pre- and post-solve | +20% SA over Standard with GPT-4o-mini; precision/recall measured on IndustryOR with synthetic negatives | Same LLM-judge weakness; synthetic negatives (delete/rewrite a constraint) are exactly the recipe we need for evaluation, but their ground truth is human-labeled while ours is program-verified (stronger) |
| COOPA (arXiv:2606.27611) | Modular OR-agent architecture survey; names "pre-code formulation verification" as a design dimension | n/a | n/a | taxonomy | conceptual support only |
| Our witness (m1_witness) | Deterministic per-family feasibility/optimality checks on the solved incumbent | deterministic | post-solve | Ground truth for all F10-F12 scoring | only fires after a solve |

Decision: **pre-solve verifier = LLM-extracted structured "requirement ledger" from the
problem text + structured "model ledger" from the generated model/code, aligned and
diffed by a deterministic checker.** We deliberately do *not* use LLM semantic
similarity as the verdict. Reasons:

- Our own evidence-grading data (G1) quantifies why LLM-as-judge underperforms on
  exactly the error distribution we face.
- The top residual error class (C-INIT missing-type: inventory never initialized,
  demand silently droppable) is a *completeness* failure. A ledger diff detects
  absence directly; back-translation and structure matching do not.
- The deterministic diff fills the currently empty `deterministic` tier in the
  harness evidence hierarchy (llm_judgment < actual_test < deterministic), so the
  verifier composes with the existing witness instead of duplicating it.

Differentiation claim (for paper track): "SAC-Opt/OPTIVER-level pre-solve verification,
with a deterministic completeness judge, evaluated against program-verified ground
truth rather than human labels."

## 3. Design

### 3.1 Components

1. **Requirement ledger extractor (LLM, one call per instance, cacheable)**
   Input: problem text. Output JSON:
   ```
   {entities: [...], parameters: [...],
    requirements: [{id, type, subject, qualifier, source_span}],
    objective_terms: [{id, sense, term, source_span}]}
   ```
   `type` in {capacity, demand_satisfaction, flow_balance, inventory_init,
   inventory_carry, linking, nonneg, integrality, ...}.
   Extracted once per instance; reused across modes/rounds.

2. **Model ledger extractor**
   Two routes, prefer deterministic:
   - AST route: walk generated Python (pyscipopt API): collect `addVar`/`addCons`
     calls, index sets, and loop structure -> constraint skeleton.
   - LLM route: ask for the same ledger schema from model.md or code. Used when the
     AST route cannot attribute semantics (e.g., constraint bodies built
     programmatically in non-obvious ways).
   Output same `requirements` schema.

3. **Ledger differ (deterministic, pure Python)**
   Align requirement lists by (type, subject, qualifier) with a small matching
   ruleset; emit: `missing` (in text, not in model), `extra`, `param_mismatch`.
   Verdict: PASS / BLOCK(report). The report is the repair message: it names the
   missing requirement type and quotes the source span, which is exactly the
   targeted-feedback format that worked in F12.

### 3.2 Placement in harness

```
problem text -> [requirement ledger] (once, cached)
LLM modeling  -> model.md/code -> [model ledger] -> differ
                                                   | PASS -> solve -> witness
                                                   | BLOCK -> repair w/ report (max K pre-solve turns) -> re-diff
```

Pre-solve turns are LLM-only (no solver invocation), so they are ~100x cheaper than
execution-feedback rounds.

## 4. Evaluation plan

### 4.1 Offline evaluation first (no new full runs)

Use the existing 380 round-1 artifacts (runs/m1_pilot/sandbox/*/gen.py) with known
witness verdicts as ground truth:

- Build requirement ledgers for all 190 instances (2 x 190 LLM calls for text side,
  cached).
- Extract model ledgers from the 380 gen.py files (AST first, LLM fallback).
- Score: per-cell BLOCK/PASS vs ground truth {crash, phantom, true_success}.
  Metrics: phantom detection recall (primary), true-success pass-through rate
  (must stay ~1.0; a verifier that blocks correct models is harmful), and
  C-INIT/C-DEMAND subclass recall.
- This mirrors OPTIVER's Table 4/5 protocol but with program-verified labels.

Gate: proceed to online integration only if phantom recall >= 0.5 with
true-success pass-through >= 0.9.

### 4.2 Online controlled experiment (after gate)

Arms (on-mode only, since off-mode is no longer the operating point):
- A: current Route-B feedback loop (F12 configuration, 3 rounds).
- B: pre-solve verifier gate (max 2 pre-solve repair turns) + same Route-B loop.
Metrics: true success /190, mean solver invocations per solved instance, mean total
LLM calls, residual error class distribution.

## 5. Self-evolution roadmap (chosen path)

Ordered by asset weight, harness-first:

1. **Harness-level evolution (now)**: treat the Route-B feedback loop as a
   population of programs: mutate feedback message templates + routing policy
   (which evidence tier fires when), select on true-success with budget penalty.
   Infrastructure: openevolve (already installed, unused). Baseline: F12 fixed
   3-round loop = 44.2% on-mode.
2. **Memory layer (next)**: mine trajectories into reusable repair skills
   (failure-class -> message template that fixed it), akin to Evo-Memory's
   test-time memory evolution. The ledger-differ reports give clean failure-class
   labels for free.
3. **Population evolution (later)**: multiple worker personas with
   crossover/selection. Defer until 1-2 show gains.
4. **JEV**: read the public writeup before deciding; not bound to it.

## 6. Risks

- Ledger extraction errors become a new false-positive source -> mitigated by the
  4.1 gate (pass-through >= 0.9) and by making BLOCK reports advisory in the first
  online arm (log-only shadow mode is an option if the gate is borderline).
- Requirement ontology per family may need tuning; the 8 RetailOpt families share
  inventory/routing structure so the ontology is small.
- AST route coverage: code style from Qwen3.8-27B is consistent (F11 showed
  faithful transcription style), so AST attribution should cover most cells;
  measure coverage in 4.1 and fall back to LLM extraction where it fails.

## 6.5 Phase A result and a design-changing discovery (2026-11-01)

Phase A = zero-cost deterministic AST probes (presolve/code_probes.py): does the
generated code even *reference* the data keys each constraint family needs?
Scored against the program-verified witness ground truth on all 380 round-1
cells (runs/presolve/phase_a_summary.md):

- on-mode: phantom recall 2/56 (3.6%), win pass-through 13/13 (100%)
- off-mode: phantom recall 0/48

Interpretation: models almost always *read* the right data; the errors are
**structural omissions** (a constraint that was never written), not missing
data plumbing. Pure static probes are a high-precision but near-zero-recall
signal — confirming that the ledger-diff (Phase B/C) must compare *constraint
structure*, not data references.

Design-changing discovery while building Phase B: **the problem text never
states that starting inventory is zero.** No "initial", no boundary equation,
nothing — yet the witness (encoding intended semantics, matching the reference
solver) requires I[p,l,1,r] = 0. C-INIT (81 phantom cells, the #1 error class)
is therefore *not extractable from the text at all*: it is a hidden convention
of the task family. A pure text<->model ledger diff is structurally blind to
the error class that matters most.

Revised design: the requirement ledger has TWO sources.

1. **Text ledger** (LLM extraction from the problem statement) — as before.
2. **Convention ledger** (task-family prior) — canonical requirements that
   competent modeling assumes but the text does not state ("an inventory
   system starts empty unless initial stock is given"; "demand is either
   served, substituted, or lost — never silently dropped"). v0.1: hand-written
   from the witness rule set. **Target state: mined automatically from F12
   feedback trajectories** — every witness message in rounds 1-3 is a
   post-solve discovery of exactly such a convention; distilling them into
   pre-solve checks is the memory layer of the self-evolution roadmap (§5
   item 2), and gives a concrete measurable evolution demo: post-solve
   evidence at generation t becomes pre-solve prior at generation t+1.

Extraction-audit datum (2026-11-01, all 190 ledgers): every ledger lists
`inventory_init` as a requirement AND flags it under `hidden_conventions` —
but the `source_span` citations for it are fabricated (quoted spans do not
state zero starting inventory; an LLM cannot cite what is not in the text).
Consequence: ledger entries whose citation does not support them are
de-facto convention entries; the citation-support check is itself a
deterministic signal for "this requirement came from priors, not text".

This also sharpens the paper-track story: the interesting phenomenon is not
"LLM makes modeling mistakes" but "the specification interface has a hidden
layer, and agents need an institutional memory of conventions, not just
better reading comprehension."

## 7. References

- SAC-Opt: arXiv:2510.05115 (semantic anchored constraint optimization)
- OPTIVER: ICLR 2026 submission (dual-side verification for optimization modeling)
- COOPA: arXiv:2606.27611 (modular OR agent architecture)
- Internal: F10 (zero-shot main table), F11 (success autopsy), F12 (feedback loop),
  G1 (LLM-audit reliability), m1_witness/retailopt.py

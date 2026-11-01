"""Pre-solve verification (ledger-diff) package.

See docs/paper/pre_solve_verifier_design_v0.1.md.

Phase A (code_probes): fully deterministic AST probes over generated code --
which dataset keys are referenced, which constraint skeletons exist. A required
data key that is never read is near-certain proof the corresponding requirement
is missing (high-precision early BLOCK signal, no solver, no LLM).
"""

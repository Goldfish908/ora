"""M1 per-family witness checkers.

A witness checker recomputes a family's business constraints from the
model's *solution values* (solution.json), not from its code and not from
the objective alone. Output: a list of (rule_id, detail) violations;
empty list = PASS. This replaces objective comparison, which is blind to
constraint holes (finding F2: every "better_than_reference" pilot output
was a false success).

Checker meta-validation (same discipline as m2gen): the checker must PASS
our own reference solution and FAIL each rule-targeted mutant with the
expected rule id (scripts/m1_f1_mutants.py).
"""

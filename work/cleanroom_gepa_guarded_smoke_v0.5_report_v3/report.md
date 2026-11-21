# GEPA candidate report

Both sets participated in GEPA train/validation. Neither is a final held-out set.

| Candidate | Accepted | Dev proxy | Dev true | Transfer proxy | Transfer true | Phantom | UNKNOWN | Tokens |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | True | 0 | 0 | 0 | 0 | 0 | 0 | 323613 |
| 1 | True | 1 | 1 | 0 | 0 | 0 | 0 | 337355 |

## Proposal history

| Iteration | Accepted | Proxy after | Dev true | Dev failures | Transfer |
|---|---|---|---:|---|---|
| seed | True | [] | 0 | {'execution_error': 2, 'quality_shortfall': 1} | complete |
| 37a977ac | False | [0.0, 0.0, 0.0] | 0 | {'execution_error': 3} | not_run |
| 14280590 | False | [0.0, 0.0, 0.0] | 0 | {'execution_error': 3} | not_run |
| 715ce094 | False | [0.0, 0.0, 0.0] | 0 | {'execution_error': 2, 'generation_failure': 1} | not_run |
| 891c5e03 | False | [0.0, 0.0, 0.0] | 0 | {'business_infeasible': 1, 'execution_error': 1, 'incomplete_artifact': 1} | not_run |
| f3eea320 | False | [0.0, 0.0, 0.0] | 0 | {'execution_error': 3} | not_run |
| 691d3481 | True | [1.0, 0.0, 0.0] | 1 | {'execution_error': 2, 'true_correct': 1} | complete |
| 24aa5c1f | False | [0.0, 1.0, 0.0] | 1 | {'generation_failure': 1, 'quality_shortfall': 1, 'true_correct': 1} | not_run |
| 5530dc41 | False | [0.0, 0.0, 0.0] | 0 | {'execution_error': 3} | not_run |

Rejected proposals: 7. Rejected specifications are excluded from the accepted-candidate registry even when iteration text is saved.

Total GEPA metric calls: 50. Candidate costs are token sums across the two selection sets; implementation and per-task records are retained.

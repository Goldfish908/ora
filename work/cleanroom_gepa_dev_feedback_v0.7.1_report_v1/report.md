# GEPA candidate report

Both sets participated in GEPA train/validation. Neither is a final held-out set.

| Candidate | Accepted | Dev proxy | Dev true | Transfer proxy | Transfer true | Phantom | UNKNOWN | Tokens |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | True | 0 | 0 | 0 | 0 | 0 | 0 | 121852 |
| 1 | True | 1 | 1 | 0 | 0 | 0 | 0 | 135442 |
| 2 | True | 2 | 2 | 0 | 0 | 0 | 0 | 144033 |

## Proposal history

| Iteration | Accepted | Proxy after | Dev true | Dev failures | Transfer |
|---|---|---|---:|---|---|
| seed | True | [] | 0 | {'execution_error': 3} | complete |
| eb5a8410 | False | [0.0, 0.0, 0.0] | 0 | {'execution_error': 3} | not_run |
| b7269fa0 | False | [0.0, 0.0, 0.0] | 0 | {'execution_error': 1, 'quality_shortfall': 2} | not_run |
| aa99b23e | True | [1.0, 0.0, 0.0] | 1 | {'execution_error': 2, 'true_correct': 1} | complete |
| 3b10a429 | False | [0.0, 1.0, 0.0] | 1 | {'execution_error': 2, 'true_correct': 1} | not_run |
| 826f34c1 | False | [0.0, 1.0, 0.0] | 1 | {'execution_error': 2, 'true_correct': 1} | not_run |
| 9aa82b64 | False | [0.0, 0.0, 0.0] | 0 | {'business_infeasible': 2, 'incomplete_artifact': 1} | not_run |
| ecf150f1 | True | [1.0, 1.0, 0.0] | 2 | {'incomplete_artifact': 1, 'true_correct': 2} | complete |
| 812cc6b1 | False | [1.0, 0.0, 1.0] | 2 | {'business_infeasible': 1, 'true_correct': 2} | not_run |

Rejected proposals: 6. Rejected specifications are excluded from the accepted-candidate registry even when iteration text is saved.

Total GEPA metric calls: 51. Candidate costs are token sums across the two selection sets; implementation and per-task records are retained.

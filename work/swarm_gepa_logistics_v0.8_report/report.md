# GEPA candidate report

Both sets participated in GEPA train/validation. Neither is a final held-out set.

| Candidate | Accepted | Dev proxy | Dev true | Transfer proxy | Transfer true | Phantom | UNKNOWN | Tokens |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | True | 2 | 0 | 0 | 0 | 0 | 0 | 177812 |

## Proposal history

| Iteration | Accepted | Proxy after | Dev true | Dev failures | Transfer |
|---|---|---|---:|---|---|
| seed | True | [] | 0 | {'execution_error': 1, 'phantom_proxy': 2} | complete |
| 74c74299 | False | [0.0, 0.0, 0.0] | 0 | {'business_infeasible': 1, 'execution_error': 2} | not_run |
| 10df62dd | False | [0.0, 1.0, 0.0] | 0 | {'execution_error': 1, 'incomplete_artifact': 1, 'phantom_proxy': 1} | not_run |
| 6ecd3bc6 | False | [0.0, 0.0, 0.0] | 0 | {'execution_error': 3} | not_run |
| 1ba4e1e4 | False | [0.0, 0.0, 1.0] | 0 | {'incomplete_artifact': 1, 'phantom_proxy': 1, 'quality_shortfall': 1} | not_run |
| f9b5d608 | False | [0.0, 0.0, 1.0] | 0 | {'business_infeasible': 1, 'incomplete_artifact': 1, 'phantom_proxy': 1} | not_run |
| c38a620b | False | [1.0, 1.0, 0.0] | 1 | {'execution_error': 1, 'phantom_proxy': 1, 'true_correct': 1} | not_run |

Rejected proposals: 6. Rejected specifications are excluded from the accepted-candidate registry even when iteration text is saved.

Negative review: no non-seed candidate was accepted. Do not claim a GEPA gain or promote memory as a positive result; inspect proposal history and seed failure classes.

Total GEPA metric calls: 37. Candidate costs are token sums across the two selection sets; implementation and per-task records are retained.

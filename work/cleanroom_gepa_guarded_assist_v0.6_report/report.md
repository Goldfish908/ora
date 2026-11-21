# GEPA candidate report

Both sets participated in GEPA train/validation. Neither is a final held-out set.

| Candidate | Accepted | Dev proxy | Dev true | Transfer proxy | Transfer true | Phantom | UNKNOWN | Tokens |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | True | 0 | 0 | 0 | 0 | 0 | 0 | 122981 |
| 1 | True | 1 | 1 | 0 | 0 | 0 | 0 | 146383 |

## Proposal history

| Iteration | Accepted | Proxy after | Dev true | Dev failures | Transfer |
|---|---|---|---:|---|---|
| seed | True | [] | 0 | {'business_infeasible': 1, 'execution_error': 2} | complete |
| d8ec455a | False | [0.0, 0.0, 0.0] | 0 | {'execution_error': 2, 'incomplete_artifact': 1} | not_run |
| ac709c68 | False | [0.0, 0.0, 0.0] | 0 | {'execution_error': 3} | not_run |
| f061653c | False | [0.0, 0.0, 0.0] | 0 | {'business_infeasible': 1, 'execution_error': 2} | not_run |
| efcaf7eb | False | [0.0, 0.0, 0.0] | 0 | {'execution_error': 1, 'incomplete_artifact': 1, 'quality_shortfall': 1} | not_run |
| 80c8ae16 | False | [0.0, 0.0, 0.0] | 0 | {'execution_error': 1, 'incomplete_artifact': 1, 'quality_shortfall': 1} | not_run |
| 5b1ec8e9 | False | [0.0, 0.0, 0.0] | 0 | {'execution_error': 1, 'incomplete_artifact': 1, 'quality_shortfall': 1} | not_run |
| a9f2bb4b | False | [0.0, 0.0, 0.0] | 0 | {'execution_error': 2, 'incomplete_artifact': 1} | not_run |
| 579fd526 | True | [1.0, 0.0, 0.0] | 1 | {'execution_error': 2, 'true_correct': 1} | complete |

Rejected proposals: 7. Rejected specifications are excluded from the accepted-candidate registry even when iteration text is saved.

Total GEPA metric calls: 50. Candidate costs are token sums across the two selection sets; implementation and per-task records are retained.

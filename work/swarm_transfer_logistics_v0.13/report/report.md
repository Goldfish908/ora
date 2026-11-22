# Clean-room B0-B3 paired report

Only equal task sets support paired comparisons. Missing arms/tasks are not_run, never zero-filled.

| Arm | Coverage | Direct true | Direct phantom | Final true | Final phantom | UNKNOWN | Wins +/− | Attempts | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0_empty_specification | 4/4 | 0 | 0 | 0 | 0 | 0 | +0/−0 | 0 | 382999 |
| B1_gepa_specification | 4/4 | 1 | 0 | 1 | 0 | 0 | +0/−0 | 0 | 411209 |
| B2_gepa_residual_dag | 4/4 | 1 | 0 | 2 | 0 | 0 | +1/−0 | 7 | 755497 |
| B3_verified_memory | not_run | — | — | — | — | — | — | — | — |

## Per-task outcomes

| Task | Arm | True direct→final | Phantom direct→final | UNKNOWN | Failure after | Repair status | Attempts | Win-safe | Tokens |
|---|---|---|---|---|---|---|---:|---|---:|
| cold_chain_locker_capacity_planning | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 34382 |
| cycling_network_design | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 53811 |
| federated_learning_cohort_selection | B0_empty_specification | False→False | False→False | False | quality_shortfall | not_applicable | 0 | True | 247357 |
| nurse_rostering | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 47449 |
| cold_chain_locker_capacity_planning | B1_gepa_specification | False→False | False→False | False | business_infeasible | not_applicable | 0 | True | 41817 |
| cycling_network_design | B1_gepa_specification | False→False | False→False | False | quality_shortfall | not_applicable | 0 | True | 60485 |
| federated_learning_cohort_selection | B1_gepa_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 252853 |
| nurse_rostering | B1_gepa_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 56054 |
| cold_chain_locker_capacity_planning | B2_gepa_residual_dag | False→False | False→False | False | business_infeasible | rejected_regression | 3 | True | 153165 |
| cycling_network_design | B2_gepa_residual_dag | False→True | False→False | False | true_correct | accepted | 1 | True | 142829 |
| federated_learning_cohort_selection | B2_gepa_residual_dag | True→True | False→False | False | true_correct | preserved_win | 0 | True | 252853 |
| nurse_rostering | B2_gepa_residual_dag | False→False | False→False | False | execution_error | rejected_regression | 3 | True | 206650 |

## Interpretation

Compare only equal task coverage and record the authorized memory scope.

Cost records include LLM tokens/latency and solver/evaluator wall time in batch_summary.json. Selection tasks are not held-out. See implementation manifests and per-task records for evidence.

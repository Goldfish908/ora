# Clean-room B0-B3 paired report

Only equal task sets support paired comparisons. Missing arms/tasks are not_run, never zero-filled.

| Arm | Coverage | Direct true | Direct phantom | Final true | Final phantom | UNKNOWN | Wins +/− | Attempts | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0_empty_specification | 4/4 | 0 | 1 | 0 | 1 | 0 | +0/−0 | 0 | 344756 |
| B1_gepa_specification | 4/4 | 1 | 0 | 1 | 0 | 0 | +0/−0 | 0 | 367228 |
| B2_gepa_residual_dag | 4/4 | 1 | 0 | 1 | 0 | 0 | +0/−0 | 9 | 1393162 |
| B3_verified_memory | not_run | — | — | — | — | — | — | — | — |

## Per-task outcomes

| Task | Arm | True direct→final | Phantom direct→final | UNKNOWN | Failure after | Repair status | Attempts | Win-safe | Tokens |
|---|---|---|---|---|---|---|---:|---|---:|
| container_gate_dro_appointment_planning | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 74498 |
| electric_medical_waste_lrp | B0_empty_specification | False→False | True→True | False | phantom_proxy | not_applicable | 0 | True | 222074 |
| offshore_wind_maintenance | B0_empty_specification | False→False | False→False | False | incomplete_artifact | not_applicable | 0 | True | 24263 |
| portable_battery_swap_rebalancing | B0_empty_specification | False→False | False→False | False | quality_shortfall | not_applicable | 0 | True | 23921 |
| container_gate_dro_appointment_planning | B1_gepa_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 80229 |
| electric_medical_waste_lrp | B1_gepa_specification | False→False | False→False | False | incomplete_artifact | not_applicable | 0 | True | 228519 |
| offshore_wind_maintenance | B1_gepa_specification | False→False | False→False | False | business_infeasible | not_applicable | 0 | True | 29395 |
| portable_battery_swap_rebalancing | B1_gepa_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 29085 |
| container_gate_dro_appointment_planning | B2_gepa_residual_dag | False→False | False→False | False | execution_error | bounded_failure | 3 | True | 218938 |
| electric_medical_waste_lrp | B2_gepa_residual_dag | False→False | False→False | False | incomplete_artifact | repair_failed | 3 | True | 990252 |
| offshore_wind_maintenance | B2_gepa_residual_dag | False→False | False→False | False | business_infeasible | rejected_regression | 3 | True | 154887 |
| portable_battery_swap_rebalancing | B2_gepa_residual_dag | True→True | False→False | False | true_correct | preserved_win | 0 | True | 29085 |

## Interpretation

Compare only equal task coverage and record the authorized memory scope.

Cost records include LLM tokens/latency and solver/evaluator wall time in batch_summary.json. Selection tasks are not held-out. See implementation manifests and per-task records for evidence.

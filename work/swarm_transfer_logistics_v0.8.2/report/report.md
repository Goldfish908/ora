# Clean-room B0-B3 paired report

Only equal task sets support paired comparisons. Missing arms/tasks are not_run, never zero-filled.

| Arm | Coverage | Direct true | Direct phantom | Final true | Final phantom | UNKNOWN | Wins +/− | Attempts | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0_empty_specification | 4/4 | 0 | 0 | 0 | 0 | 0 | +0/−0 | 0 | 312061 |
| B1_gepa_specification | 4/4 | 0 | 0 | 0 | 0 | 0 | +0/−0 | 0 | 333372 |
| B2_gepa_residual_dag | 4/4 | 0 | 0 | 0 | 0 | 0 | +0/−0 | 11 | 1402251 |
| B3_verified_memory | not_run | — | — | — | — | — | — | — | — |

## Per-task outcomes

| Task | Arm | True direct→final | Phantom direct→final | UNKNOWN | Failure after | Repair status | Attempts | Win-safe | Tokens |
|---|---|---|---|---|---|---|---:|---|---:|
| evtol_vertiport_recovery | B0_empty_specification | False→False | False→False | False | incomplete_artifact | not_applicable | 0 | True | 38356 |
| naloxone_drone_response_network | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 23968 |
| robotic_mobile_fulfillment_orchestration | B0_empty_specification | False→False | False→False | False | incomplete_artifact | not_applicable | 0 | True | 40823 |
| wastewater_sentinel_site_selection | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 208914 |
| evtol_vertiport_recovery | B1_gepa_specification | False→False | False→False | False | incomplete_artifact | not_applicable | 0 | True | 46208 |
| naloxone_drone_response_network | B1_gepa_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 29866 |
| robotic_mobile_fulfillment_orchestration | B1_gepa_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 39922 |
| wastewater_sentinel_site_selection | B1_gepa_specification | False→False | False→False | False | execution_timeout | not_applicable | 0 | True | 217376 |
| evtol_vertiport_recovery | B2_gepa_residual_dag | False→False | False→False | False | incomplete_artifact | no_verified_progress | 3 | True | 206010 |
| naloxone_drone_response_network | B2_gepa_residual_dag | False→False | False→False | False | execution_error | no_verified_progress | 3 | True | 145254 |
| robotic_mobile_fulfillment_orchestration | B2_gepa_residual_dag | False→False | False→False | False | execution_error | no_verified_progress | 2 | True | 143846 |
| wastewater_sentinel_site_selection | B2_gepa_residual_dag | False→False | False→False | False | execution_timeout | rejected_regression | 3 | True | 907141 |

## Interpretation

Compare only equal task coverage and record the authorized memory scope.

Cost records include LLM tokens/latency and solver/evaluator wall time in batch_summary.json. Selection tasks are not held-out. See implementation manifests and per-task records for evidence.

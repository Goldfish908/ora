# Clean-room B0-B3 paired report

Only equal task sets support paired comparisons. Missing arms/tasks are not_run, never zero-filled.

| Arm | Coverage | Direct true | Direct phantom | Final true | Final phantom | UNKNOWN | Wins +/− | Attempts | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0_empty_specification | 4/4 | 2 | 0 | 2 | 0 | 0 | +0/−0 | 0 | 106398 |
| B1_gepa_specification | 4/4 | 2 | 1 | 2 | 1 | 0 | +0/−0 | 0 | 127706 |
| B2_gepa_residual_dag | 3/4 | 2 | 1 | 1 | 1 | 0 | +0/−0 | 3 | 317446 |
| B3_verified_memory | not_run | — | — | — | — | — | — | — | — |

## Per-task outcomes

| Task | Arm | True direct→final | Phantom direct→final | UNKNOWN | Failure after | Repair status | Attempts | Win-safe | Tokens |
|---|---|---|---|---|---|---|---:|---|---:|
| fuel_tanker_compartment_routing | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 29078 |
| hybrid_telehealth_appointment_scheduling | B0_empty_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 20178 |
| robust_microgrid_islanding_dispatch | B0_empty_specification | False→False | False→False | False | incomplete_artifact | not_applicable | 0 | True | 37974 |
| smart_building_demand_response_dispatch | B0_empty_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 19168 |
| fuel_tanker_compartment_routing | B1_gepa_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 32790 |
| hybrid_telehealth_appointment_scheduling | B1_gepa_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 26637 |
| robust_microgrid_islanding_dispatch | B1_gepa_specification | False→False | True→True | False | phantom_proxy | not_applicable | 0 | True | 44226 |
| smart_building_demand_response_dispatch | B1_gepa_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 24053 |
| fuel_tanker_compartment_routing | B2_gepa_residual_dag | False→False | False→False | False | execution_error | no_verified_progress | 1 | True | 78905 |
| hybrid_telehealth_appointment_scheduling | B2_gepa_residual_dag | True→not_run | False→not_run | False | not_run | not_run | — | None | — |
| robust_microgrid_islanding_dispatch | B2_gepa_residual_dag | False→False | True→True | False | phantom_proxy | duplicate_repair | 2 | True | 214488 |
| smart_building_demand_response_dispatch | B2_gepa_residual_dag | True→True | False→False | False | true_correct | preserved_win | 0 | True | 24053 |

## Interpretation

Compare only equal task coverage and record the authorized memory scope.

Cost records include LLM tokens/latency and solver/evaluator wall time in batch_summary.json. Selection tasks are not held-out. See implementation manifests and per-task records for evidence.

# Clean-room B0-B3 paired report

Only equal task sets support paired comparisons. Missing arms/tasks are not_run, never zero-filled.

| Arm | Coverage | Direct true | Direct phantom | Final true | Final phantom | UNKNOWN | Wins +/− | Attempts | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0_empty_specification | 4/4 | 2 | 0 | 2 | 0 | 0 | +0/−0 | 0 | 102766 |
| B1_gepa_specification | 4/4 | 1 | 0 | 1 | 0 | 0 | +0/−0 | 0 | 125938 |
| B2_gepa_residual_dag | 4/4 | 1 | 0 | 2 | 0 | 0 | +1/−0 | 8 | 324772 |
| B3_verified_memory | not_run | — | — | — | — | — | — | — | — |

## Per-task outcomes

| Task | Arm | True direct→final | Phantom direct→final | UNKNOWN | Failure after | Repair status | Attempts | Win-safe | Tokens |
|---|---|---|---|---|---|---|---:|---|---:|
| platelet_inventory_rotation | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 14423 |
| retail_media_campaign_allocation | B0_empty_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 20391 |
| stochastic_surgery_capacity_planning | B0_empty_specification | False→False | False→False | False | incomplete_artifact | not_applicable | 0 | True | 30113 |
| vertical_farm_harvest_energy_planning | B0_empty_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 37839 |
| platelet_inventory_rotation | B1_gepa_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 18407 |
| retail_media_campaign_allocation | B1_gepa_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 24556 |
| stochastic_surgery_capacity_planning | B1_gepa_specification | False→False | False→False | False | incomplete_artifact | not_applicable | 0 | True | 37678 |
| vertical_farm_harvest_energy_planning | B1_gepa_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 45297 |
| platelet_inventory_rotation | B2_gepa_residual_dag | False→False | False→False | False | execution_error | rejected_regression | 3 | True | 54056 |
| retail_media_campaign_allocation | B2_gepa_residual_dag | False→True | False→False | False | true_correct | accepted | 2 | True | 56291 |
| stochastic_surgery_capacity_planning | B2_gepa_residual_dag | False→False | False→False | False | incomplete_artifact | rejected_regression | 3 | True | 169128 |
| vertical_farm_harvest_energy_planning | B2_gepa_residual_dag | True→True | False→False | False | true_correct | preserved_win | 0 | True | 45297 |

## Interpretation

Compare only equal task coverage and record the authorized memory scope.

Cost records include LLM tokens/latency and solver/evaluator wall time in batch_summary.json. Selection tasks are not held-out. See implementation manifests and per-task records for evidence.

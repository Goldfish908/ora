# Clean-room B0-B3 paired report

Only equal task sets support paired comparisons. Missing arms/tasks are not_run, never zero-filled.

| Arm | Coverage | Direct true | Direct phantom | Final true | Final phantom | UNKNOWN | Wins +/− | Attempts | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0_empty_specification | 4/4 | 1 | 0 | 1 | 0 | 0 | +0/−0 | 0 | 232124 |
| B1_gepa_specification | 4/4 | 1 | 1 | 1 | 1 | 0 | +0/−0 | 0 | 249413 |
| B2_gepa_residual_dag | 4/4 | 1 | 1 | 1 | 1 | 0 | +0/−0 | 6 | 562189 |
| B3_verified_memory | not_run | — | — | — | — | — | — | — | — |

## Per-task outcomes

| Task | Arm | True direct→final | Phantom direct→final | UNKNOWN | Failure after | Repair status | Attempts | Win-safe | Tokens |
|---|---|---|---|---|---|---|---:|---|---:|
| ev_battery_recycling_network | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 29246 |
| industrial_water_reuse_blending | B0_empty_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 12900 |
| mass_timber_panel_cutting_plan | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 163463 |
| real_world_3d_bin_packing | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 26515 |
| ev_battery_recycling_network | B1_gepa_specification | False→False | False→False | False | business_infeasible | not_applicable | 0 | True | 33205 |
| industrial_water_reuse_blending | B1_gepa_specification | False→False | True→True | False | phantom_proxy | not_applicable | 0 | True | 17243 |
| mass_timber_panel_cutting_plan | B1_gepa_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 170344 |
| real_world_3d_bin_packing | B1_gepa_specification | False→False | False→False | False | incomplete_artifact | not_applicable | 0 | True | 28621 |
| ev_battery_recycling_network | B2_gepa_residual_dag | False→False | False→False | False | business_infeasible | duplicate_repair | 3 | True | 223208 |
| industrial_water_reuse_blending | B2_gepa_residual_dag | False→False | True→True | False | phantom_proxy | no_verified_progress | 1 | True | 42158 |
| mass_timber_panel_cutting_plan | B2_gepa_residual_dag | True→True | False→False | False | true_correct | preserved_win | 0 | True | 170344 |
| real_world_3d_bin_packing | B2_gepa_residual_dag | False→False | False→False | False | incomplete_artifact | duplicate_repair | 2 | True | 126479 |

## Interpretation

Compare only equal task coverage and record the authorized memory scope.

Cost records include LLM tokens/latency and solver/evaluator wall time in batch_summary.json. Selection tasks are not held-out. See implementation manifests and per-task records for evidence.

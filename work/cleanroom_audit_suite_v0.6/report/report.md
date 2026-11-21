# Clean-room B0-B3 paired report

Only equal task sets support paired comparisons. Missing arms/tasks are not_run, never zero-filled.

| Arm | Coverage | Direct true | Direct phantom | Final true | Final phantom | UNKNOWN | Wins +/− | Attempts | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0_empty_specification | 2/2 | 0 | 1 | 0 | 1 | 0 | +0/−0 | 0 | 177378 |
| B1_gepa_specification | 2/2 | 1 | 1 | 1 | 1 | 0 | +0/−0 | 0 | 186191 |
| B2_gepa_residual_dag | 2/2 | 1 | 1 | 2 | 0 | 0 | +1/−0 | 1 | 213885 |
| B3_verified_memory | not_run | — | — | — | — | — | — | — | — |

## Per-task outcomes

| Task | Arm | Direct | Final | Failure after | Repair status | Attempts |
|---|---|---|---|---|---|---:|
| industrial_water_reuse_blending | B0_empty_specification | False | False | execution_error | not_applicable | 0 |
| mass_timber_panel_cutting_plan | B0_empty_specification | False | False | phantom_proxy | not_applicable | 0 |
| industrial_water_reuse_blending | B1_gepa_specification | False | False | phantom_proxy | not_applicable | 0 |
| mass_timber_panel_cutting_plan | B1_gepa_specification | True | True | true_correct | not_applicable | 0 |
| industrial_water_reuse_blending | B2_gepa_residual_dag | False | True | true_correct | accepted | 1 |
| mass_timber_panel_cutting_plan | B2_gepa_residual_dag | True | True | true_correct | preserved_win | 0 |

## Interpretation

Compare only equal task coverage and record the authorized memory scope.

Cost records include LLM tokens/latency and solver/evaluator wall time in batch_summary.json. Selection tasks are not held-out. See implementation manifests and per-task records for evidence.

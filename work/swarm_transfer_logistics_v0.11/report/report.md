# Clean-room B0-B3 paired report

Only equal task sets support paired comparisons. Missing arms/tasks are not_run, never zero-filled.

| Arm | Coverage | Direct true | Direct phantom | Final true | Final phantom | UNKNOWN | Wins +/− | Attempts | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0_empty_specification | 4/4 | 0 | 0 | 0 | 0 | 0 | +0/−0 | 0 | 128294 |
| B1_gepa_specification | 4/4 | 2 | 1 | 2 | 1 | 0 | +0/−0 | 0 | 156031 |
| B2_gepa_residual_dag | 4/4 | 2 | 1 | 2 | 1 | 0 | +0/−0 | 5 | 523316 |
| B3_verified_memory | not_run | — | — | — | — | — | — | — | — |

## Per-task outcomes

| Task | Arm | True direct→final | Phantom direct→final | UNKNOWN | Failure after | Repair status | Attempts | Win-safe | Tokens |
|---|---|---|---|---|---|---|---:|---|---:|
| carbon_removal_credit_portfolio | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 14185 |
| cell_tower_coverage_expansion | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 43748 |
| edge_cache_content_placement | B0_empty_specification | False→False | False→False | False | quality_shortfall | not_applicable | 0 | True | 57137 |
| private_5g_small_cell_planning | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 13224 |
| carbon_removal_credit_portfolio | B1_gepa_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 18103 |
| cell_tower_coverage_expansion | B1_gepa_specification | False→False | True→True | False | phantom_proxy | not_applicable | 0 | True | 50427 |
| edge_cache_content_placement | B1_gepa_specification | False→False | False→False | False | quality_shortfall | not_applicable | 0 | True | 63575 |
| private_5g_small_cell_planning | B1_gepa_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 23926 |
| carbon_removal_credit_portfolio | B2_gepa_residual_dag | True→True | False→False | False | true_correct | preserved_win | 0 | True | 18103 |
| cell_tower_coverage_expansion | B2_gepa_residual_dag | False→False | True→True | False | phantom_proxy | no_verified_progress | 3 | True | 282062 |
| edge_cache_content_placement | B2_gepa_residual_dag | False→False | False→False | False | quality_shortfall | no_verified_progress | 2 | True | 199225 |
| private_5g_small_cell_planning | B2_gepa_residual_dag | True→True | False→False | False | true_correct | preserved_win | 0 | True | 23926 |

## Interpretation

Compare only equal task coverage and record the authorized memory scope.

Cost records include LLM tokens/latency and solver/evaluator wall time in batch_summary.json. Selection tasks are not held-out. See implementation manifests and per-task records for evidence.

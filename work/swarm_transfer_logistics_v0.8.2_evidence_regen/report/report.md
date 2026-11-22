# Clean-room B0-B3 paired report

Only equal task sets support paired comparisons. Missing arms/tasks are not_run, never zero-filled.

| Arm | Coverage | Direct true | Direct phantom | Final true | Final phantom | UNKNOWN | Wins +/− | Attempts | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0_empty_specification | 4/4 | 1 | 0 | 1 | 0 | 0 | +0/−0 | 0 | 154316 |
| B1_gepa_specification | 4/4 | 1 | 3 | 1 | 3 | 0 | +0/−0 | 0 | 178864 |
| B2_gepa_residual_dag | 4/4 | 1 | 3 | 2 | 2 | 0 | +1/−0 | 8 | 613669 |
| B3_verified_memory | not_run | — | — | — | — | — | — | — | — |

## Per-task outcomes

| Task | Arm | True direct→final | Phantom direct→final | UNKNOWN | Failure after | Repair status | Attempts | Win-safe | Tokens |
|---|---|---|---|---|---|---|---:|---|---:|
| autonomous_lab_courier_tsptw | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 20107 |
| curbside_delivery_slot_coordination | B0_empty_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 37950 |
| flood_relief_multimodal_routing | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 19483 |
| shared_drone_base_delivery_assignment | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 76776 |
| autonomous_lab_courier_tsptw | B1_gepa_specification | False→False | True→True | False | phantom_proxy | not_applicable | 0 | True | 26058 |
| curbside_delivery_slot_coordination | B1_gepa_specification | True→True | False→False | False | true_correct | not_applicable | 0 | True | 44723 |
| flood_relief_multimodal_routing | B1_gepa_specification | False→False | True→True | False | phantom_proxy | not_applicable | 0 | True | 27329 |
| shared_drone_base_delivery_assignment | B1_gepa_specification | False→False | True→True | False | phantom_proxy | not_applicable | 0 | True | 80754 |
| autonomous_lab_courier_tsptw | B2_gepa_residual_dag | False→True | True→False | False | true_correct | accepted | 2 | True | 91227 |
| curbside_delivery_slot_coordination | B2_gepa_residual_dag | True→True | False→False | False | true_correct | preserved_win | 0 | True | 44723 |
| flood_relief_multimodal_routing | B2_gepa_residual_dag | False→False | True→True | False | phantom_proxy | repair_failed | 3 | True | 132291 |
| shared_drone_base_delivery_assignment | B2_gepa_residual_dag | False→False | True→True | False | phantom_proxy | bounded_failure | 3 | True | 345428 |

## Interpretation

Compare only equal task coverage and record the authorized memory scope.

Cost records include LLM tokens/latency and solver/evaluator wall time in batch_summary.json. Selection tasks are not held-out. See implementation manifests and per-task records for evidence.

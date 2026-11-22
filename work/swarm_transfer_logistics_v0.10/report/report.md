# Clean-room B0-B3 paired report

Only equal task sets support paired comparisons. Missing arms/tasks are not_run, never zero-filled.

| Arm | Coverage | Direct true | Direct phantom | Final true | Final phantom | UNKNOWN | Wins +/− | Attempts | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0_empty_specification | 4/4 | 0 | 0 | 0 | 0 | 0 | +0/−0 | 0 | 94386 |
| B1_gepa_specification | 4/4 | 0 | 2 | 0 | 2 | 0 | +0/−0 | 0 | 118869 |
| B2_gepa_residual_dag | 4/4 | 0 | 2 | 0 | 2 | 0 | +0/−0 | 10 | 477242 |
| B3_verified_memory | not_run | — | — | — | — | — | — | — | — |

## Per-task outcomes

| Task | Arm | True direct→final | Phantom direct→final | UNKNOWN | Failure after | Repair status | Attempts | Win-safe | Tokens |
|---|---|---|---|---|---|---|---:|---|---:|
| airport_gate_assignment | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 31670 |
| circular_packaging_replenishment | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 20431 |
| coastal_aquaculture_feed_oxygen_planning | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 12353 |
| home_healthcare_routing | B0_empty_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 29932 |
| airport_gate_assignment | B1_gepa_specification | False→False | False→False | False | quality_shortfall | not_applicable | 0 | True | 33481 |
| circular_packaging_replenishment | B1_gepa_specification | False→False | True→True | False | phantom_proxy | not_applicable | 0 | True | 26191 |
| coastal_aquaculture_feed_oxygen_planning | B1_gepa_specification | False→False | True→True | False | phantom_proxy | not_applicable | 0 | True | 20640 |
| home_healthcare_routing | B1_gepa_specification | False→False | False→False | False | execution_error | not_applicable | 0 | True | 38557 |
| airport_gate_assignment | B2_gepa_residual_dag | False→False | False→False | False | quality_shortfall | rejected_regression | 3 | True | 175887 |
| circular_packaging_replenishment | B2_gepa_residual_dag | False→False | True→True | False | phantom_proxy | rejected_regression | 3 | True | 129457 |
| coastal_aquaculture_feed_oxygen_planning | B2_gepa_residual_dag | False→False | True→True | False | phantom_proxy | no_verified_progress | 2 | True | 78989 |
| home_healthcare_routing | B2_gepa_residual_dag | False→False | False→False | False | execution_error | duplicate_repair | 2 | True | 92909 |

## Interpretation

Compare only equal task coverage and record the authorized memory scope.

Cost records include LLM tokens/latency and solver/evaluator wall time in batch_summary.json. Selection tasks are not held-out. See implementation manifests and per-task records for evidence.

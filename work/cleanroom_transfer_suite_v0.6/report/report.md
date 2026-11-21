# Clean-room B0-B3 paired report

Only equal task sets support paired comparisons. Missing arms/tasks are not_run, never zero-filled.

| Arm | Coverage | Direct true | Direct phantom | Final true | Final phantom | UNKNOWN | Wins +/− | Attempts | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0_empty_specification | 1/1 | 0 | 0 | 0 | 0 | 0 | +0/−0 | 0 | 39107 |
| B1_gepa_specification | 1/1 | 0 | 0 | 0 | 0 | 0 | +0/−0 | 0 | 32127 |
| B2_gepa_residual_dag | 1/1 | 0 | 0 | 0 | 0 | 0 | +0/−0 | 3 | 204644 |
| B3_verified_memory | not_run | — | — | — | — | — | — | — | — |

## Per-task outcomes

| Task | Arm | Direct | Final | Failure after | Repair status | Attempts |
|---|---|---|---|---|---|---:|
| ev_battery_recycling_network | B0_empty_specification | False | False | generation_failure | not_applicable | 0 |
| ev_battery_recycling_network | B1_gepa_specification | False | False | business_infeasible | not_applicable | 0 |
| ev_battery_recycling_network | B2_gepa_residual_dag | False | False | business_infeasible | bounded_failure | 3 |

## Interpretation

Compare only equal task coverage and record the authorized memory scope.

Cost records include LLM tokens/latency and solver/evaluator wall time in batch_summary.json. Selection tasks are not held-out. See implementation manifests and per-task records for evidence.

# Controlled eval summary (2.5b)

- mutants detected (full): 7/7
- mutants detected (blind): 6/7
- false positives on correct/equivalent: confirmed=2, suspected=0 (n=6)
- repairs succeeded: 6/7

| artifact | kind | mutation | confirmed | suspected | detected | repair witness | wall_s |
|---|---|---|---|---|---|---|---|
| tiny_assign/a_e1 | equivalent | - | 1 | 0 | - | None | 86.0 |
| tiny_assign/a_m1 | mutant | omission | 1 | 0 | True | None | 38.5 |
| tiny_assign/a_m2 | mutant | index | 2 | 0 | True | PASS | 64.6 |
| tiny_assign/correct | correct | - | 0 | 0 | - | - | 13.5 |
| tiny_sched/c_e1 | equivalent | - | 1 | 0 | - | PASS | 56.6 |
| tiny_sched/c_m1 | mutant | precedence | 1 | 0 | True | PASS | 131.9 |
| tiny_sched/c_m2 | mutant | omission | 1 | 0 | True | PASS | 129.1 |
| tiny_sched/c_m3 | mutant | data_mapping | 1 | 0 | True | PASS | 43.7 |
| tiny_sched/correct | correct | - | 0 | 0 | - | - | 8.7 |
| tiny_transport/b_e1 | equivalent | - | 0 | 0 | - | - | 8.2 |
| tiny_transport/b_m1 | mutant | direction | 1 | 0 | True | PASS | 32.6 |
| tiny_transport/b_m2 | mutant | unit | 2 | 0 | True | PASS | 51.0 |
| tiny_transport/correct | correct | - | 0 | 0 | - | - | 7.7 |

## Blind-mode detection (input control)

| artifact | detected_blind | n_confirmed |
|---|---|---|
| tiny_assign/a_m1 | False | 0 |
| tiny_assign/a_m2 | True | 1 |
| tiny_sched/c_m1 | True | 1 |
| tiny_sched/c_m2 | True | 1 |
| tiny_sched/c_m3 | True | 1 |
| tiny_transport/b_m1 | True | 1 |
| tiny_transport/b_m2 | True | 2 |

## Confirmed finding texts (for manual review of detection and localization)
- tiny_assign/a_e1 F-002 [semantic]: The check confirmed that the CSV data contains the entry for W2,J3. Since the code creates variables for all entries in the CSV, the variable `x_W2_J3` exists, and setting its upper bound to 0 correctly enforces the hard constraint that W2 cannot do J3.
- tiny_assign/a_m1 F-001 [implementation]: The code does not contain any logic to exclude the (W2, J3) pair. The absence of a constraint or variable fix for this specific pair confirms that the business rule R3 is not implemented in the solver.
- tiny_assign/a_m2 F-001 [implementation]: The code explicitly forbids W2 from doing J4 instead of J3. The constraint `x["W2", "J4"] == 0` is present on line 34, and there is no corresponding constraint for `x["W2", "J3"]`. This directly violates Business Rule 3 which states W2 cannot do J3.
- tiny_assign/a_m2 F-002 [feasibility]: With the incorrect constraint forbidding W2-J4, the solver can assign W2 to J3 (cost 1), leading to a suboptimal objective value of 27.0 compared to the true minimum under correct rules. The solution.json file was not found at the expected path, but the stdout confirms the wrong objective was computed.
- tiny_sched/c_e1 F-001 [semantic]: The code explicitly includes the term `0.0001 * sum(start[j] for j in jobs)` in the objective function, which is not specified in the problem statement.
- tiny_sched/c_m1 F-001 [semantic]: The code explicitly contains `model.addCons(start[u] >= start[v] + proc[v])` for the precedence pair (J1, J3). This enforces Start(J1) >= End(J3), which is the inverse of the required constraint End(J1) <= Start(J3). The runtime check failed due to missing output file, but the source code inspection confirms the logical inversion.
- tiny_sched/c_m2 F-001 [implementation]: The code explicitly restricts the no-overlap disjunctive constraints to only the first machine (M1) via `machines[:1]`. This confirms that jobs assigned to M2 are not constrained from overlapping, violating Business Rule 2.
- tiny_sched/c_m3 F-001 [implementation]: The check confirmed that `load_data` returns processing times based on `setup_min` (e.g., J1=12.0) instead of `proc_min` (expected 3.0). The grep also confirmed the line `proc[r["job_id"]] = float(r["setup_min"])` exists in the code.
- tiny_transport/b_m1 F-001 [implementation]: The code explicitly uses `x['P2', w] <= MIN_FROM_P2` (line 43), which is an upper bound. The problem statement requires a lower bound (`>= 20`). This confirms the inequality direction is reversed.
- tiny_transport/b_m2 F-001 [implementation]: Confirmed: load_data() returns demand values in boxes (80.0, 90.0, 80.0) without applying the BOX_TO_PIECES conversion factor of 10. The constant is defined but never used in the code path.
- tiny_transport/b_m2 F-002 [semantic]: Confirmed: total demand in the model is 250 (boxes) instead of 2500 (pieces). The demand constraints will enforce equality to box values rather than piece values, violating R2 and R4.
- tiny_assign/a_m2 F-001 [implementation]: The grep output confirms the code contains `model.addCons(x["W2", "J4"] == 0)` immediately following the comment `# W2 is not qualified for J3.`. This is a direct semantic inconsistency: the constraint forbids assignment to J4, while the comment claims qualification issues for J3. Since the problem statement is hidden and no data indicates disqualification (costs exist for all pairs), this constraint is unsupported or mislabeled.
- tiny_sched/c_m1 F-001 [implementation]: The code explicitly enforces `start[pred] >= start[succ] + proc[succ]`, which is the reverse of the required precedence constraint (pred must finish before succ starts). This is a confirmed implementation error.
- tiny_sched/c_m2 F-001 [implementation]: The code explicitly restricts the no-overlap disjunctive constraints to only the first machine (M1). Since there are two machines, M2 has no overlap constraints, allowing jobs assigned to M2 to overlap arbitrarily. This is a direct implementation bug violating R2.
- tiny_sched/c_m3 F-001 [implementation]: The code explicitly loads `setup_min` into the `proc` dictionary (line 16), ignoring `proc_min`. The data check confirms these columns have different values (3 vs 12 for J1). This is a confirmed implementation error where setup times are used as processing times.
- tiny_transport/b_m1 F-001 [implementation]: The code explicitly defines `MIN_FROM_P2 = 20` with a comment stating 'at least 20 pieces', but the constraint implemented is `x['P2', w] <= MIN_FROM_P2`. This is an upper bound (maximum), which contradicts the variable name and comment indicating a lower bound (minimum). The semantic inversion is confirmed by the source code.
- tiny_transport/b_m2 F-001 [implementation]: Confirmed that BOX_TO_PIECES is defined but never used in the code. The demand values are loaded directly from CSV (80, 90, 80) and used as-is in the model constraints, while the constant suggests a conversion to pieces was intended. This creates a unit mismatch if the data is indeed in boxes.
- tiny_transport/b_m2 F-003 [quality]: Confirmed that model.md is missing from the submission directory.

localization_correct: 待人工复核填写（summary.json 各行为 null）。

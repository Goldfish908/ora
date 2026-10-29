# Controlled eval summary (2.5b)

- mutants detected (full): 7/7
- mutants detected (blind): 5/7
- false positives on correct/equivalent: confirmed=1, suspected=0 (n=6)
- repairs succeeded: 4/7

| artifact | kind | mutation | confirmed | suspected | detected | repair witness | wall_s |
|---|---|---|---|---|---|---|---|
| tiny_assign/a_e1 | equivalent | - | 0 | 0 | - | - | 6.4 |
| tiny_assign/a_m1 | mutant | omission | 1 | 0 | True | FAIL | 60.4 |
| tiny_assign/a_m2 | mutant | index | 1 | 0 | True | None | 32.0 |
| tiny_assign/correct | correct | - | 0 | 0 | - | - | 12.0 |
| tiny_sched/c_e1 | equivalent | - | 1 | 0 | - | PASS | 93.3 |
| tiny_sched/c_m1 | mutant | precedence | 1 | 0 | True | None | 42.6 |
| tiny_sched/c_m2 | mutant | omission | 2 | 0 | True | PASS | 45.4 |
| tiny_sched/c_m3 | mutant | data_mapping | 1 | 0 | True | PASS | 49.5 |
| tiny_sched/correct | correct | - | 0 | 0 | - | - | 9.1 |
| tiny_transport/b_e1 | equivalent | - | 0 | 0 | - | - | 8.9 |
| tiny_transport/b_m1 | mutant | direction | 1 | 0 | True | PASS | 55.4 |
| tiny_transport/b_m2 | mutant | unit | 1 | 0 | True | PASS | 46.8 |
| tiny_transport/correct | correct | - | 0 | 0 | - | - | 10.1 |

## Blind-mode detection (input control)

| artifact | detected_blind | n_confirmed |
|---|---|---|
| tiny_assign/a_m1 | False | 0 |
| tiny_assign/a_m2 | True | 1 |
| tiny_sched/c_m1 | True | 1 |
| tiny_sched/c_m2 | True | 2 |
| tiny_sched/c_m3 | True | 2 |
| tiny_transport/b_m1 | True | 1 |
| tiny_transport/b_m2 | False | 0 |

## Confirmed finding texts (for manual review of detection and localization)
- tiny_assign/a_m1 F-001 [implementation]: The code does not enforce the constraint that Worker W2 cannot be assigned to Job J3. The variable x['W2', 'J3'] is created and included in the objective function without being fixed to 0 or constrained to be 0. Since the cost for (W2, J3) is 1 (the lowest in the matrix), the solver will likely assign this pair, violating the business rule.
- tiny_assign/a_m2 F-001 [implementation]: Confirmed: The code sets x['W2','J4']==0 instead of x['W2','J3']==0. The AST check for a constraint involving both 'W2' and 'J3' returned FAIL, confirming no such constraint exists. The solver produced an objective of 27.0, which is only achievable if W2 is assigned to J3 (cost 1), violating requirement R3.
- tiny_sched/c_e1 F-001 [semantic]: The objective function explicitly includes a tie-breaking term `0.0001 * sum(start[j] for j in jobs)` in addition to `cmax`. This deviates from the strict requirement to minimize makespan only.
- tiny_sched/c_m1 F-001 [implementation]: The code explicitly contains `model.addCons(start[u] >= start[v] + proc[v])` for the precedence pair (J1, J3). This enforces that J1 starts after J3 finishes, which is the exact opposite of the required constraint (J1 finishes before J3 starts). The logic is definitively reversed.
- tiny_sched/c_m2 F-001 [implementation]: The code explicitly restricts the no-overlap disjunctive constraints to only the first machine (M1) via `machines[:1]`. Machine M2 has no overlap-prevention constraints, allowing jobs assigned to M2 to overlap in time. This is a direct implementation defect violating R2.
- tiny_sched/c_m2 F-002 [semantic]: The objective function includes an unsourced secondary term `1e-4 * sum(starts)` not specified in the problem statement. The problem requires minimizing makespan only. While the coefficient is small, it modifies the optimization landscape and could theoretically lead to a different optimal solution than pure makespan minimization, constituting an unsourced objective term.
- tiny_sched/c_m3 F-001 [implementation]: The code explicitly reads `setup_min` (line 16) instead of `proc_min` for job durations. The data check confirms J1 has proc_min=3 but setup_min=12, proving the model uses incorrect processing times, violating R4.
- tiny_transport/b_m1 F-001 [implementation]: The code explicitly uses `x["P2", w] <= MIN_FROM_P2` (line 43), which imposes an upper bound of 20 instead of the required lower bound (`>=`). This directly contradicts Business Rule 3 ('at least 20 pieces'). The first check failed due to a missing file, but the source code inspection definitively confirms the logical error in the constraint implementation.
- tiny_transport/b_m2 F-001 [implementation]: The check confirmed that `load_data()` returns D1 demand as 80.0 instead of the required 800 pieces. The constant `BOX_TO_PIECES` is defined but never used in the code to convert the demand values from boxes to pieces, violating requirement R4.
- tiny_assign/a_m2 F-001 [implementation]: The code explicitly contains the constraint `model.addCons(x["W2", "J4"] == 0)` at line 34. Since the problem statement is hidden and no such restriction appears in the provided data overview or standard assignment problem definitions, this is an unsourced hard constraint that artificially restricts the feasible region.
- tiny_sched/c_m1 F-001 [semantic]: The code explicitly enforces `start[u] >= start[v] + proc[v]` for precedence pairs `(u, v)` where `u` is the predecessor. This constraint forces the predecessor to start after the successor has finished, which is the reverse of the standard precedence requirement (predecessor must finish before successor starts). The runtime check failed because the solution file was not generated in the expected path, but the static code analysis confirms the logical inversion.
- tiny_sched/c_m2 F-001 [implementation]: The code does not reference 'setup' anywhere, confirming that the 'setup_min' column from jobs.csv is completely ignored in the model formulation.
- tiny_sched/c_m2 F-002 [implementation]: The disjunctive constraints for machine non-overlap are explicitly limited to `machines[:1]` (only M1). Jobs assigned to M2 have no non-overlap constraints, allowing simultaneous scheduling on M2.
- tiny_sched/c_m3 F-001 [implementation]: Confirmed: The code loads 'setup_min' (value 12 for J1) into the 'proc' dictionary instead of 'proc_min' (value 3 for J1). The loaded values are {J1: 12.0, J2: 5.0, J3: 6.0, J4: 8.0, J5: 9.0} which correspond to setup times, not processing times. This fundamentally changes the problem instance being solved.
- tiny_sched/c_m3 F-004 [implementation]: Confirmed: model.md file does not exist at /app/submissions/model.md. The submission is missing the required mathematical model documentation.
- tiny_transport/b_m1 F-001 [implementation]: The execution of the submitted code resulted in 'MODEL STATUS infeasible'. This confirms that the constraint `x['P2', w] <= 20` (applied per warehouse) renders the model infeasible given the demand and supply data. Since a standard transport problem with sufficient supply should be feasible, this indicates an incorrect or unsupported hard constraint implementation.

localization_correct: 待人工复核填写（summary.json 各行为 null）。

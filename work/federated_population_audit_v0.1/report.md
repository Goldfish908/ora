# Federated same-root population audit

Population: k=3, depth=2, evaluation_budget=6, allow_exploration=True. Single-chain uses the same six-evaluation cap and operators. Direct-full is one full-variable reoptimization from the identical root.

All proposals carry the parent artifact hash and a neighborhood signature. Candidates use the real public checker and PySCIPOpt sub-MILPs. Official evaluation is run only after all final elite-best artifacts are frozen; official results never enter candidate selection.

Search cost includes root checking, all proposals (including duplicates), all candidate checks, and solver time. Candidate counts include the root; evaluated counts exclude it. Official wall time is stored separately in audit.json.

| Scenario | Strategy | Official true | Official feasible | Official quality | Official objective | Total search s | Solver s | Candidates (evaluated) | Exploration | Lost-win events | New-hard-error rejections |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| duplicate_client | single_chain | True | True | 2.0 | 6021.247619499998 | 31.027818 | 17.100692 | 5 (4) | 1 | 0 | 1 |
| duplicate_client | population | True | True | 2.0 | 6021.247619499996 | 46.293523 | 25.071100 | 7 (6) | 2 | 0 | 2 |
| duplicate_client | direct_full | True | True | 1.9999999999978852 | 6020.689909999997 | 12.830976 | 8.963914 | 2 (1) | 0 | 0 | 0 |
| stream_minimums | single_chain | True | True | 2.0 | 6021.5907284999985 | 47.348682 | 28.342289 | 6 (5) | 3 | 0 | 1 |
| stream_minimums | population | True | True | 2.0 | 6021.590728499997 | 50.280220 | 30.198444 | 7 (6) | 2 | 0 | 2 |
| stream_minimums | direct_full | True | True | 1.9999999999981872 | 6020.689909999998 | 13.403285 | 9.621432 | 2 (1) | 0 | 0 | 0 |
| all_budgets | single_chain | True | True | 2.0 | 6021.247619499998 | 38.745370 | 23.065756 | 6 (5) | 2 | 0 | 1 |
| all_budgets | population | True | True | 2.0 | 6020.703447599998 | 36.656981 | 22.991629 | 7 (6) | 2 | 0 | 2 |
| all_budgets | direct_full | True | True | 1.9999999999969789 | 6020.689909999995 | 12.390312 | 8.556406 | 2 (1) | 0 | 0 | 0 |

Guard totals: 9 UNKNOWN candidates (all rejected), 0 candidates with introduced public violations, and 0 lost-win events. New-hard-error rejections also include UNKNOWN/no-candidate errors; the separate introduced-violation count avoids conflating them.

## Population comparisons

Objective deltas are population minus comparator; the objective is maximized.

| Scenario | Public population vs single | Public Δ objective | Official gain vs single | Official Δ objective | Official gain vs direct-full |
|---|---|---:|---|---:|---|
| duplicate_client | tie | 0.000000 | tie | -0.000000 | positive |
| stream_minimums | tie | 0.000000 | tie | -0.000000 | positive |
| all_budgets | single_chain | -0.544172 | negative | -0.544172 | positive |

Overall post-hoc official population-vs-single verdict: **negative**.

## Clean control

| Strategy | Unchanged | Not worse than root | Best from elite | Public status | Public objective | Official true | Official feasible |
|---|---|---|---|---|---:|---|---|
| single_chain | False | True | True | FEASIBLE | 6021.247620 | True | True |
| population | False | True | True | FEASIBLE | 6021.247620 | True | True |
| direct_full | True | True | True | FEASIBLE | 6020.689910 | True | True |

Common clean root: `c4f7070fb060e8c0727215645bb6075389f58976c6344df25bbc3c57abc2a115`. Each scenario builds its corrupted root once from this clean artifact and reuses that exact root for all three strategies. Public checks are not official business truth; no global-optimality claim is made.

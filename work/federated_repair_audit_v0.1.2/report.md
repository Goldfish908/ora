# Federated declarative repair audit

Zero LLM calls. Official outcomes are used only for final independent scoring, not candidate selection.

| Scenario | Public before → after | Official true before → after | Official feasible after | Official quality after | Objective before → after | SCIP seconds |
|---|---|---|---|---:|---|---:|
| duplicate_client | fail → pass | False → True | True | 2.0 | 6029.078750 → 6021.271243 | 0.628 |
| stream_minimums | fail → pass | False → True | True | 2.0 | 4695.628619 → 6021.590729 | 0.855 |
| all_budgets | fail → pass | False → True | True | 2.0 | 6549.361358 → 6020.703448 | 0.840 |

"""m2gen parameter samplers: one per structure, seeded and deterministic.

Design rule (from inv_cap vertical slice): continuous variables + flat costs
let mutant optima plateau onto the true rule; integer variables, sloped
costs and tight shared resources are what make connection errors visible.
Samplers below bias toward that regime, and emit.py's validation loop
rejects any draw where a mutant does not actually fail its witness rules.
"""

import random


def sample_inv_cap(rng: random.Random) -> dict:
    T = 3
    demand = {p: [rng.randint(2, 6) for _ in range(T)] for p in ("P1", "P2")}
    prod_cost_p2_base = rng.randint(2, 3)
    return {
        "products": ["P1", "P2"],
        "periods": T,
        "demand": demand,
        "init_inv": {p: rng.randint(0, 3) for p in ("P1", "P2")},
        # cap >= max per-period demand keeps every draw feasible
        "prod_cap": {p: max(demand[p]) + rng.randint(0, 2)
                     for p in ("P1", "P2")},
        # P1 flat, P2 rising slope: production timing becomes a real decision
        "prod_cost": {"P1": rng.randint(2, 3),
                      "P2": [prod_cost_p2_base, prod_cost_p2_base + 1,
                             prod_cost_p2_base + 1]},
        "hold_cost": {"P1": 1, "P2": rng.choice([0, 1])},
        # P2 strictly bulkier than P1 so a C1 volume misbind is observable
        "volume": {"P1": 1, "P2": rng.randint(2, 3)},
        # tight shared storage: the discriminating resource
        "storage_cap": rng.randint(2, 4),
    }


def sample_setup_charge(rng: random.Random) -> dict:
    T = 3
    demand = {p: [rng.randint(2, 6) for _ in range(T)] for p in ("P1", "P2")}
    return {
        "products": ["P1", "P2"],
        "periods": T,
        "demand": demand,
        "init_inv": {p: rng.randint(0, 2) for p in ("P1", "P2")},
        # cap >= max per-period demand keeps every draw feasible
        "prod_cap": {p: max(demand[p]) + rng.randint(0, 2)
                     for p in ("P1", "P2")},
        "prod_cost": {p: rng.randint(2, 4) for p in ("P1", "P2")},
        "hold_cost": {p: rng.randint(0, 1) for p in ("P1", "P2")},
        # clearly nonzero setup fees so dropping the cost term is observable
        "setup_cost": {"P1": rng.randint(5, 8), "P2": rng.randint(2, 4)},
    }


def sample_flow_dir(rng: random.Random) -> dict:
    # d1 > d2 > 0 keeps the C2 sign-reversal mutant feasible
    d2 = rng.randint(2, 4)
    d1 = d2 + rng.randint(1, 3)
    total = d1 + d2
    s_a = rng.randint(d1, total + 2)
    s_b = rng.randint(d2, total + 2)
    cap_ah = rng.randint(d1, total + 2)
    cap_bh = rng.randint(d2, total + 2)
    cost_ah = rng.randint(1, 4)
    cost_bh = cost_ah
    while cost_bh == cost_ah:
        cost_bh = rng.randint(1, 4)  # must differ so a C1 cost misbind shows
    return {
        "plants": ["A", "B"],
        "hub": "H",
        "demand_points": ["D1", "D2"],
        "edges": [["A", "H"], ["B", "H"], ["H", "D1"], ["H", "D2"]],
        "supply": {"A": s_a, "B": s_b},
        "demand": {"D1": d1, "D2": d2},
        "edge_cap": {"A->H": cap_ah, "B->H": cap_bh,
                     "H->D1": d1, "H->D2": d2},
        "transp_cost": {"A": {"H": cost_ah}, "B": {"H": cost_bh},
                        "H": {"D1": rng.randint(1, 4),
                              "D2": rng.randint(1, 4)}},
        "prod_cost": {"A": rng.randint(1, 3), "B": rng.randint(1, 3)},
    }


SAMPLERS = {
    "inv_cap": sample_inv_cap,
    "setup_charge": sample_setup_charge,
    "flow_dir": sample_flow_dir,
}

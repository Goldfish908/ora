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


def sample_assign_fixed(rng: random.Random) -> dict:
    W = ["W1", "W2", "W3"]
    J = ["J1", "J2", "J3", "J4"]
    fixed = {w: rng.randint(5, 10) for w in W}
    # fixed fees must differ so a swap in the objective is observable
    while len(set(fixed.values())) < len(W):
        fixed = {w: rng.randint(5, 10) for w in W}
    return {
        "workers": W,
        "jobs": J,
        "cost": {w: {j: rng.randint(2, 8) for j in J} for w in W},
        # capacities sum above |J| so every draw is feasible, but not all
        # on one worker
        "cap": {w: 2 for w in W},
        "fixed": fixed,
    }


def sample_dist_plan(rng: random.Random) -> dict:
    T = 3
    W = ["W1", "W2"]
    S = ["S1", "S2", "S3"]
    demand = {s: [rng.randint(2, 5) for _ in range(T)] for s in S}
    # lag-1 transit: period-1 demand can only be met from init_inv
    init_inv = {s: demand[s][0] + rng.randint(0, 1) for s in S}
    need = [sum(demand[s][t] for s in S) for t in range(T)]
    max_need = max(need[1:])  # arrivals at t>=2 must be shipped at t-1
    # aggregate caps: sum covers peak need (feasible) but each warehouse
    # alone does not -> scope binding and route choice both matter
    c1 = rng.randint(max(2, max_need // 2), max_need - 1)
    cap = {"W1": c1, "W2": max_need - c1 + rng.randint(0, 2)}
    # W1 strictly cheaper everywhere: the C5 per-route mutant pushes all
    # flow through W1 and breaks the true aggregate cap; W1/W2 costs must
    # differ on every route so a C6 cost-map swap changes the objective
    cost = {"W1": {}, "W2": {}}
    for s in S:
        cost["W2"][s] = rng.randint(3, 5)
        cost["W1"][s] = rng.randint(1, 2)
    return {
        "warehouses": W, "stores": S, "periods": T,
        "demand": demand, "init_inv": init_inv,
        "cap": cap, "cost": cost,
        "hold_cost": {s: rng.randint(1, 2) for s in S},
    }


def sample_atom_scope(rng: random.Random) -> dict:
    W = ["W1", "W2"]
    S = ["S1", "S2", "S3"]
    demand = {s: rng.randint(2, 5) for s in S}
    total = sum(demand.values())
    # each cap below total (both warehouses needed), sum covers total;
    # per-route mutant gets 3x cap on W1 -> must exceed aggregate cap
    c1 = rng.randint(max(2, (total + 2) // 3), total - 1)
    cap = {"W1": c1, "W2": total - c1 + rng.randint(0, 1)}
    cost = {"W1": {}, "W2": {}}
    for s in S:
        cost["W2"][s] = rng.randint(3, 5)
        cost["W1"][s] = rng.randint(1, 2)
    return {"warehouses": W, "stores": S, "demand": demand,
            "cap": cap, "cost": cost}


def sample_atom_lag(rng: random.Random) -> dict:
    T = 3
    demand = [rng.randint(2, 5) for _ in range(T)]
    # period-1 demand must come from init stock (lag); later periods force
    # shipping, and decreasing ship costs make the lag decision-relevant
    return {
        "periods": T,
        "demand": demand,
        "init_inv": demand[0] + rng.randint(0, 1),
        "ship_cost": sorted((rng.randint(3, 6) for _ in range(T)),
                            reverse=True),
        "hold_cost": rng.randint(1, 2),
    }


def sample_atom_map(rng: random.Random) -> dict:
    W = ["W1", "W2"]
    S = ["S1", "S2"]
    cost = {"W1": {}, "W2": {}}
    for s in S:
        a, b = rng.randint(1, 4), rng.randint(1, 4)
        while b == a:
            b = rng.randint(1, 4)  # costs must differ so a map swap shows
        cost["W1"][s], cost["W2"][s] = a, b
    return {"warehouses": W, "stores": S,
            "demand": {s: rng.randint(2, 6) for s in S},
            "cost": cost}


def sample_atom_link(rng: random.Random) -> dict:
    W = ["W1", "W2"]
    S = ["S1", "S2", "S3"]
    demand = {s: rng.randint(2, 5) for s in S}
    total = sum(demand.values())
    # neither warehouse alone covers total demand -> both must open;
    # the no-link mutant pays no fixed fees at all
    cap = {"W1": rng.randint(max(2, total // 2), total - 1),
           "W2": rng.randint(max(2, total // 2), total - 1)}
    cap["W2"] = max(cap["W2"], total - cap["W1"] + rng.randint(0, 1))
    fixed = {"W1": rng.randint(6, 10), "W2": rng.randint(6, 10)}
    cost = {"W1": {s: rng.randint(1, 3) for s in S},
            "W2": {s: rng.randint(1, 3) for s in S}}
    return {"warehouses": W, "stores": S, "demand": demand,
            "cap": cap, "fixed": fixed, "cost": cost}


def sample_dist_setup(rng: random.Random) -> dict:
    p = sample_dist_plan(rng)
    # depot fixed charge per warehouse-period; clearly nonzero so a
    # dropped activation link is observable in the objective
    p["depot_cost"] = {"W1": rng.randint(6, 10), "W2": rng.randint(6, 10)}
    return p


SAMPLERS = {
    "inv_cap": sample_inv_cap,
    "setup_charge": sample_setup_charge,
    "flow_dir": sample_flow_dir,
    "assign_fixed": sample_assign_fixed,
    "dist_plan": sample_dist_plan,
    "atom_scope": sample_atom_scope,
    "atom_lag": sample_atom_lag,
    "atom_map": sample_atom_map,
    "atom_link": sample_atom_link,
    "dist_setup": sample_dist_setup,
}

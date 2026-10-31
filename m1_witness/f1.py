"""Family F1 (Core Operations) witness checker.

Input contract (solution.json, produced by the model's own code):
{
  "objective": float,
  "Q":     {"p|l|t":   qty},     # order qty, period t = 1..T
  "sales": {"p|l|t|r": units},   # sales out of bucket with r periods left
  "I":     {"p|l|t|r": units},   # inventory at START of period t, r left
  "W":     {"p|l|t":   units},   # expired waste
  "lost":  {"p|l|t":   units},   # lost sales
  "sub":   {"pf|pt|l|t": units}  # substitution: pf's demand served by pt
}

Rules recomputed from the family prompt (retail_f1_*):
  C-INIT    I[p,l,1,r] == 0 for r < shelf_life[p] (no initial stock in data)
  C-INFLOW  I[p,l,t,SL] == Q[p,l,t-LT] + return_rate[p]*sum_r sales[p,l,t-1,r]
            (+ net transshipment when trans_edges present)
  C-AGING   I[p,l,t+1,r] == I[p,l,t,r+1] - sales[p,l,t,r+1]   (r = 1..SL-1)
  C-WASTE   W[p,l,t] == I[p,l,t,1] - sales[p,l,t,1] >= 0
  C-AVAIL   sales[p,l,t,r] <= I[p,l,t,r]
  C-DEMAND  sales_total[p,l,t] + sub_out - sub_in + lost == demand
            (demand[p,l,t] = demand_curve[p][t] * demand_share[l])
  C-PRODCAP sum_l Q[p,l,t] <= production_cap[p][t]
  C-STORAGE sum_p cold_usage[p] * sum_r I[p,l,t,r] <= cold_capacity[l]
  C-SUBEDGE sub only on declared sub_edges, same-location, >= 0
  C-FIFO    fresher bucket sold while older bucket has leftover -> violation
  C-NONNEG  all quantities >= 0
  C-OBJ     recomputed objective == reported objective (purchase + holding
            on end-of-period r>=2 buckets + waste + lost-sales penalties)
"""

from __future__ import annotations

TOL = 1e-4
REL_TOL = 1e-4


def _get(table: dict, *key) -> float:
    return float(table.get("|".join(str(k) for k in key), 0.0))


def _violations_append(out: list, rule: str, detail: str,
                       cap: dict[str, int]) -> None:
    # one line per (rule, p, l, t) cell is enough; cap per rule for readability
    if cap.get(rule, 0) < 5:
        out.append((rule, detail))
    cap[rule] = cap.get(rule, 0) + 1


def check(data: dict, sol: dict) -> dict[str, list]:
    # violations = hard economic/consistency breaks; warnings = convention
    # deviations that cannot change the optimal cost (e.g. FIFO among r>=2
    # buckets with uniform holding cost).
    v: list[tuple[str, str]] = []
    w: list[tuple[str, str]] = []
    cap: dict[str, int] = {}
    P, L = data["products"], data["locations"]
    T = data["periods"]
    SL = data["shelf_life"]
    LT = data["lead_time"]
    rr = data["return_rate"]
    costs = data["costs"]
    sub_edges = {tuple(e) for e in data["network"]["sub_edges"]}
    trans_edges = [tuple(e) for e in data["network"]["trans_edges"]]
    Q = sol.get("Q", {})
    S = sol.get("sales", {})
    I = sol.get("I", {})
    W = sol.get("W", {})
    LO = sol.get("lost", {})
    SB = sol.get("sub", {})

    def nonneg(name, table):
        for k, val in table.items():
            if float(val) < -TOL:
                _violations_append(v, "C-NONNEG", f"{name}[{k}]={val}", cap)

    for name, table in (("Q", Q), ("sales", S), ("I", I),
                        ("W", W), ("lost", LO), ("sub", SB)):
        nonneg(name, table)

    for p in P:
        sl = SL[p]
        for l in L:
            # C-INIT: buckets r < SL at t=1 must be zero
            for r in range(1, sl):
                iv = _get(I, p, l, 1, r)
                if abs(iv) > TOL:
                    _violations_append(
                        v, "C-INIT", f"I[{p},{l},1,{r}]={iv} != 0", cap)
            for t in range(1, T + 1):
                # C-INFLOW: fresh bucket
                lt = LT[p]
                inflow = _get(Q, p, l, t - lt) if t - lt >= 1 else 0.0
                if t > 1:
                    inflow += rr[p] * sum(
                        _get(S, p, l, t - 1, r) for r in range(1, sl + 1))
                for (src, dst) in trans_edges:
                    if dst == l:
                        inflow += _get(sol.get("X", {}), p, src, dst, t)
                    if src == l:
                        inflow -= _get(sol.get("X", {}), p, src, dst, t)
                lhs = _get(I, p, l, t, sl)
                if abs(lhs - inflow) > TOL * max(1.0, abs(inflow)):
                    _violations_append(
                        v, "C-INFLOW",
                        f"I[{p},{l},{t},{sl}]={lhs} != inflow {inflow}", cap)
                # C-AGING (bucket r at t+1 from r+1 at t)
                if t < T:
                    for r in range(1, sl):
                        nxt = _get(I, p, l, t + 1, r)
                        src_amt = _get(I, p, l, t, r + 1) - _get(
                            S, p, l, t, r + 1)
                        if abs(nxt - src_amt) > TOL * max(1.0, abs(src_amt)):
                            _violations_append(
                                v, "C-AGING",
                                f"I[{p},{l},{t+1},{r}]={nxt} != "
                                f"I-sales of r+1 ({src_amt})", cap)
                # C-WASTE
                wv = _get(W, p, l, t)
                exp_left = _get(I, p, l, t, 1) - _get(S, p, l, t, 1)
                if abs(wv - exp_left) > TOL * max(1.0, abs(exp_left)):
                    _violations_append(
                        v, "C-WASTE",
                        f"W[{p},{l},{t}]={wv} != expiring leftover "
                        f"{exp_left}", cap)
                # C-AVAIL + C-FIFO
                for r in range(1, sl + 1):
                    sv, iv = _get(S, p, l, t, r), _get(I, p, l, t, r)
                    if sv > iv + TOL * max(1.0, abs(iv)):
                        _violations_append(
                            v, "C-AVAIL",
                            f"sales[{p},{l},{t},{r}]={sv} > I={iv}", cap)
                for r_old in range(1, sl):
                    leftover = (_get(I, p, l, t, r_old)
                                - _get(S, p, l, t, r_old))
                    if leftover <= TOL:
                        continue
                    for r_new in range(r_old + 1, sl + 1):
                        if _get(S, p, l, t, r_new) > TOL:
                            _violations_append(
                                w, "C-FIFO",
                                f"[{p},{l},{t}] sold r={r_new} while r="
                                f"{r_old} leftover={leftover}", cap)
                            break
                # C-DEMAND
                dem = data["demand_curve"][p][t - 1] * data["demand_share"][l]
                s_tot = sum(_get(S, p, l, t, r) for r in range(1, sl + 1))
                sub_out = sum(_get(SB, p, pt, l, t)
                              for (pf, pt) in sub_edges if pf == p)
                sub_in = sum(_get(SB, pf, p, l, t)
                             for (pf, pt) in sub_edges if pt == p)
                bal = s_tot + sub_out - sub_in + _get(LO, p, l, t)
                if abs(bal - dem) > TOL * max(1.0, abs(dem)):
                    _violations_append(
                        v, "C-DEMAND",
                        f"[{p},{l},{t}] sales+sub-lost balance {bal} "
                        f"!= demand {dem}", cap)
        # C-PRODCAP
        for t in range(1, T + 1):
            tot = sum(_get(Q, p, l, t) for l in L)
            capv = data["production_cap"][p][t - 1]
            if tot > capv + TOL * max(1.0, abs(capv)):
                _violations_append(
                    v, "C-PRODCAP",
                    f"sum_l Q[{p},*,{t}]={tot} > cap {capv}", cap)

    # C-STORAGE
    for l in L:
        for t in range(1, T + 1):
            used = sum(data["cold_usage"][p]
                       * sum(_get(I, p, l, t, r) for r in range(1, SL[p] + 1))
                       for p in P)
            capv = data["cold_capacity"][l]
            if used > capv + TOL * max(1.0, abs(capv)):
                _violations_append(
                    v, "C-STORAGE",
                    f"[{l},{t}] storage used {used} > cap {capv}", cap)

    # C-SUBEDGE
    for k, val in SB.items():
        pf, pt, l, t = k.split("|")
        if float(val) > TOL and (pf, pt) not in sub_edges:
            _violations_append(
                v, "C-SUBEDGE", f"sub[{k}]={val} on undeclared edge", cap)

    # C-OBJ
    obj = 0.0
    for p in P:
        for l in L:
            for t in range(1, T + 1):
                obj += costs["purchasing"][p] * _get(Q, p, l, t)
                obj += costs["waste"][p] * _get(W, p, l, t)
                obj += costs["lost_sales"][p] * _get(LO, p, l, t)
                for r in range(2, SL[p] + 1):
                    obj += (costs["inventory"][p]
                            * (_get(I, p, l, t, r) - _get(S, p, l, t, r)))
    rep = sol.get("objective")
    if rep is None:
        v.append(("C-OBJ", "solution.json missing 'objective'"))
    elif abs(obj - float(rep)) > REL_TOL * max(1.0, abs(float(rep))):
        v.append(("C-OBJ", f"recomputed {obj} != reported {rep}"))

    return {"violations": v, "warnings": w}

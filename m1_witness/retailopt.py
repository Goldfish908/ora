"""Generalized RetailOpt witness checker (all 190 instances, 38 archetypes).

Same solution.json contract as m1_witness.f1, plus optional fields:
  "X": {"p|src|dst|t": units}   # transshipment flow (f7 network archetypes)

Mechanisms activate from the instance data (not from the scenario name):
  costs.fixed_order > 0          -> C-FIXED in objective (per (p,l,t) with Q>0)
  constraints.moq > 0            -> C-MOQ: Q in {0} u [moq, inf)
  constraints.pack_size > 1      -> C-PACK: Q multiple of pack_size
  constraints.budget_per_period  -> C-BUDGET: per-period spend cap
  constraints.waste_limit_pct    -> C-WASTELIMIT: sum W <= pct * sum demand
  network.trans_edges non-empty  -> C-XEDGE/C-XNET, transshipment cost in obj
  labor_usage any > 0 and
    labor_cap[l][t] < 99999      -> C-LABOR: usage * handled <= cap
  lead_time[p] > 0               -> already in C-INFLOW (Q[p,l,t-LT])
  return_rate[p] > 0             -> already in C-INFLOW (rr * sales[t-1])

units_handled for C-LABOR is ambiguous in the prompt ("sum of units
received, picked, or moved"); `handled_mode` selects the interpretation.
Calibrated against reference_objective on retail_f8_ship_from_store_v1
(the one archetype-variant where the cap binds hard enough to
discriminate): "received" matches to 5e-7, "received_picked" is refuted
(1.4e-3 too expensive). Default: "received".
  "received"         fresh inflow only (Q arrival + returns + net X in)
  "received_picked"  fresh inflow + total sales
  "full"             fresh inflow + sales + X out
"""

from __future__ import annotations

TOL = 1e-4
REL_TOL = 1e-4


def _get(table: dict, *key) -> float:
    return float(table.get("|".join(str(k) for k in key), 0.0))


def _violations_append(out: list, rule: str, detail: str,
                       cap: dict[str, int]) -> None:
    if cap.get(rule, 0) < 5:
        out.append((rule, detail))
    cap[rule] = cap.get(rule, 0) + 1


def active_features(data: dict) -> dict:
    costs = data["costs"]
    cons = data.get("constraints", {})
    labor_usage = data.get("labor_usage", {})
    labor_on = (any(v > 0 for v in labor_usage.values())
                and any(c < 99999 for c in data["labor_cap"][data["locations"][0]]))
    return {
        "fixed_order": float(costs.get("fixed_order", 0.0)),
        "trans_cost": float(costs.get("transshipment", 0.0)),
        "moq": float(cons.get("moq") or 0.0),
        "pack_size": float(cons.get("pack_size") or 1.0),
        "budget": cons.get("budget_per_period"),
        "waste_limit_pct": cons.get("waste_limit_pct"),
        "labor": labor_on,
    }


def check(data: dict, sol: dict,
          handled_mode: str = "received") -> dict[str, list]:
    v: list[tuple[str, str]] = []
    w: list[tuple[str, str]] = []
    cap: dict[str, int] = {}
    P, L = data["products"], data["locations"]
    T = data["periods"]
    SL = data["shelf_life"]
    LT = data["lead_time"]
    rr = data["return_rate"]
    costs = data["costs"]
    feat = active_features(data)
    sub_edges = {tuple(e) for e in data["network"]["sub_edges"]}
    trans_edges = {tuple(e) for e in data["network"]["trans_edges"]}
    Q = sol.get("Q", {})
    S = sol.get("sales", {})
    I = sol.get("I", {})
    W = sol.get("W", {})
    LO = sol.get("lost", {})
    SB = sol.get("sub", {})
    X = sol.get("X", {})

    def nonneg(name, table):
        for k, val in table.items():
            if float(val) < -TOL:
                _violations_append(v, "C-NONNEG", f"{name}[{k}]={val}", cap)

    for name, table in (("Q", Q), ("sales", S), ("I", I),
                        ("W", W), ("lost", LO), ("sub", SB), ("X", X)):
        nonneg(name, table)

    def fresh_inflow(p, l, t):
        """The RHS of the fresh-bucket identity at (p,l,t)."""
        lt = LT[p]
        infl = _get(Q, p, l, t - lt) if t - lt >= 1 else 0.0
        if t > 1:
            infl += rr[p] * sum(
                _get(S, p, l, t - 1, r) for r in range(1, SL[p] + 1))
        for (src, dst) in trans_edges:
            if dst == l:
                infl += _get(X, p, src, dst, t)
            if src == l:
                infl -= _get(X, p, src, dst, t)
        return infl

    def received(p, l, t):
        """Units received at (p,l,t): order arrival + returns + inbound X."""
        lt = LT[p]
        rec = _get(Q, p, l, t - lt) if t - lt >= 1 else 0.0
        if t > 1:
            rec += rr[p] * sum(
                _get(S, p, l, t - 1, r) for r in range(1, SL[p] + 1))
        rec += sum(_get(X, p, src, l, t) for (src, dst) in trans_edges
                   if dst == l)
        return rec

    for p in P:
        sl = SL[p]
        for l in L:
            for r in range(1, sl):                      # C-INIT
                iv = _get(I, p, l, 1, r)
                if abs(iv) > TOL:
                    _violations_append(
                        v, "C-INIT", f"I[{p},{l},1,{r}]={iv} != 0", cap)
            for t in range(1, T + 1):
                inflow = fresh_inflow(p, l, t)          # C-INFLOW
                lhs = _get(I, p, l, t, sl)
                if abs(lhs - inflow) > TOL * max(1.0, abs(inflow)):
                    _violations_append(
                        v, "C-INFLOW",
                        f"I[{p},{l},{t},{sl}]={lhs} != inflow {inflow}", cap)
                if t < T:                               # C-AGING
                    for r in range(1, sl):
                        nxt = _get(I, p, l, t + 1, r)
                        src_amt = (_get(I, p, l, t, r + 1)
                                   - _get(S, p, l, t, r + 1))
                        if abs(nxt - src_amt) > TOL * max(1.0, abs(src_amt)):
                            _violations_append(
                                v, "C-AGING",
                                f"I[{p},{l},{t+1},{r}]={nxt} != "
                                f"I-sales of r+1 ({src_amt})", cap)
                wv = _get(W, p, l, t)                   # C-WASTE
                exp_left = _get(I, p, l, t, 1) - _get(S, p, l, t, 1)
                if abs(wv - exp_left) > TOL * max(1.0, abs(exp_left)):
                    _violations_append(
                        v, "C-WASTE",
                        f"W[{p},{l},{t}]={wv} != expiring leftover "
                        f"{exp_left}", cap)
                for r in range(1, sl + 1):              # C-AVAIL
                    sv, iv = _get(S, p, l, t, r), _get(I, p, l, t, r)
                    if sv > iv + TOL * max(1.0, abs(iv)):
                        _violations_append(
                            v, "C-AVAIL",
                            f"sales[{p},{l},{t},{r}]={sv} > I={iv}", cap)
                for r_old in range(1, sl):              # C-FIFO (warning)
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
                dem = (data["demand_curve"][p][t - 1]   # C-DEMAND
                       * data["demand_share"][l])
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
        for t in range(1, T + 1):                       # C-PRODCAP
            tot = sum(_get(Q, p, l, t) for l in L)
            capv = data["production_cap"][p][t - 1]
            if tot > capv + TOL * max(1.0, abs(capv)):
                _violations_append(
                    v, "C-PRODCAP",
                    f"sum_l Q[{p},*,{t}]={tot} > cap {capv}", cap)

    for l in L:                                         # C-STORAGE
        for t in range(1, T + 1):
            used = sum(data["cold_usage"][p]
                       * sum(_get(I, p, l, t, r)
                             for r in range(1, SL[p] + 1))
                       for p in P)
            capv = data["cold_capacity"][l]
            if used > capv + TOL * max(1.0, abs(capv)):
                _violations_append(
                    v, "C-STORAGE",
                    f"[{l},{t}] storage used {used} > cap {capv}", cap)

    for k, val in SB.items():                           # C-SUBEDGE
        pf, pt, l, t = k.split("|")
        if float(val) > TOL and (pf, pt) not in sub_edges:
            _violations_append(
                v, "C-SUBEDGE", f"sub[{k}]={val} on undeclared edge", cap)

    for k, val in X.items():                            # C-XEDGE
        p, src, dst, t = k.split("|")
        if float(val) > TOL and (src, dst) not in trans_edges:
            _violations_append(
                v, "C-XEDGE", f"X[{k}]={val} on undeclared edge", cap)

    if feat["moq"] > 0:                                 # C-MOQ
        moq = feat["moq"]
        for k, val in Q.items():
            qv = float(val)
            if TOL < qv < moq - TOL * max(1.0, moq):
                _violations_append(
                    v, "C-MOQ", f"Q[{k}]={qv} in (0, moq={moq})", cap)

    if feat["pack_size"] > 1:                           # C-PACK
        pk = feat["pack_size"]
        for k, val in Q.items():
            qv = float(val)
            rem = abs(qv - round(qv / pk) * pk)
            if rem > TOL * max(1.0, abs(qv)):
                _violations_append(
                    v, "C-PACK", f"Q[{k}]={qv} not multiple of {pk}", cap)

    if feat["budget"] is not None:                      # C-BUDGET
        bud = float(feat["budget"])
        for t in range(1, T + 1):
            spend = 0.0
            for p in P:
                for l in L:
                    qv = _get(Q, p, l, t)
                    spend += costs["purchasing"][p] * qv
                    if qv > TOL:
                        spend += feat["fixed_order"]
            if spend > bud + TOL * max(1.0, bud):
                _violations_append(
                    v, "C-BUDGET",
                    f"[t={t}] spend {spend} > budget {bud}", cap)

    if feat["labor"]:                                   # C-LABOR
        usage = data["labor_usage"]
        for l in L:
            for t in range(1, T + 1):
                used = 0.0
                for p in P:
                    handled = 0.0
                    if handled_mode in ("received", "received_picked",
                                        "full"):
                        handled += received(p, l, t)
                    if handled_mode in ("received_picked", "full"):
                        handled += sum(_get(S, p, l, t, r)
                                       for r in range(1, SL[p] + 1))
                    if handled_mode == "full":
                        handled += sum(_get(X, p, l, dst, t)
                                       for (src, dst) in trans_edges
                                       if src == l)
                    used += usage[p] * handled
                capv = data["labor_cap"][l][t - 1]
                if used > capv + TOL * max(1.0, capv):
                    _violations_append(
                        v, "C-LABOR",
                        f"[{l},{t}] labor used {used} > cap {capv} "
                        f"(mode={handled_mode})", cap)

    if feat["waste_limit_pct"] is not None:             # C-WASTELIMIT
        pct = float(feat["waste_limit_pct"])
        tot_w = sum(float(x) for x in W.values())
        tot_dem = sum(data["demand_curve"][p][t - 1] * data["demand_share"][l]
                      for p in P for l in L for t in range(1, T + 1))
        if tot_w > pct * tot_dem + TOL * max(1.0, pct * tot_dem):
            _violations_append(
                v, "C-WASTELIMIT",
                f"total waste {tot_w} > {pct} * total demand {tot_dem}", cap)

    # C-OBJ
    obj = 0.0
    for p in P:
        for l in L:
            for t in range(1, T + 1):
                qv = _get(Q, p, l, t)
                obj += costs["purchasing"][p] * qv
                if feat["fixed_order"] and qv > TOL:
                    obj += feat["fixed_order"]
                obj += costs["waste"][p] * _get(W, p, l, t)
                obj += costs["lost_sales"][p] * _get(LO, p, l, t)
                for r in range(2, SL[p] + 1):
                    obj += (costs["inventory"][p]
                            * (_get(I, p, l, t, r) - _get(S, p, l, t, r)))
    if feat["trans_cost"]:
        obj += feat["trans_cost"] * sum(float(x) for x in X.values())
    rep = sol.get("objective")
    if rep is None:
        v.append(("C-OBJ", "solution.json missing 'objective'"))
    elif abs(obj - float(rep)) > REL_TOL * max(1.0, abs(float(rep))):
        v.append(("C-OBJ", f"recomputed {obj} != reported {rep}"))

    return {"violations": v, "warnings": w}

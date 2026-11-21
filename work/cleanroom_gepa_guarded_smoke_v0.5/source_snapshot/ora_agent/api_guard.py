"""Deterministic, auditable repairs for a narrow set of known PySCIPOpt API errors."""
from __future__ import annotations

import ast

REPLACEMENTS = (
    ("from pypscip import *", "from pyscipopt import *", "wrong_import"),
    ("from pycipopt import *", "from pyscipopt import *", "wrong_import"),
    ("from pypcipopt import *", "from pyscipopt import *", "wrong_import"),
    ("from pypscip import Model\n", "from pyscipopt import Model\n", "wrong_import"),
    ("from pycipopt import Model\n", "from pyscipopt import Model\n", "wrong_import"),
    ("from pypcipopt import Model\n", "from pyscipopt import Model\n", "wrong_import"),
    ("from scipyopt import Model, quicksum", "from pyscipopt import Model, quicksum", "wrong_import"),
    ("from scipyopt import Model\n", "from pyscipopt import Model\n", "wrong_import"),
    ("from scipyopt import *", "from pyscipopt import *", "wrong_import"),
    ("from scipopt import Model, quicksum", "from pyscipopt import Model, quicksum", "wrong_import"),
    ("from scipopt import Model\n", "from pyscipopt import Model\n", "wrong_import"),
    ("from scipopt import *", "from pyscipopt import *", "wrong_import"),
    ("from pyscip import Model, quicksum", "from pyscipopt import Model, quicksum", "wrong_import"),
    ("from pyscip import Model\n", "from pyscipopt import Model\n", "wrong_import"),
    ("from pyscip import *", "from pyscipopt import *", "wrong_import"),
    ("from pypscip import Model, QuickSum", "from pyscipopt import Model, quicksum", "wrong_import"),
    ("from pycipopt import Model, QuickSum", "from pyscipopt import Model, quicksum", "wrong_import"),
    ("from pypcipopt import Model, QuickSum", "from pyscipopt import Model, quicksum", "wrong_import"),
    ("import scipopt as sp", "from pyscipopt import Model, quicksum", "wrong_import"),
    ("sp.Optimize()", "Model()", "model_construction"),
    (".setUb(", ".chgVarUb(", "upper_bound"),
    (".setLb(", ".chgVarLb(", "lower_bound"),
    (".createVar(", ".addVar(", "variable_construction"),
    (".solve()", ".optimize()", "solve_call"),
    ("getNvars()", "getNVars()", "variable_count_method"),
    ("getNconss()", "getNConss()", "constraint_count_method"),
    ("getSolStatus()", "getStatus()", "status_method"),
    ("getOrigObjval()", "getObjVal()", "objective_method"),
    ("setParam(\"gaprel\"", "setRealParam(\"limits/gap\"", "gap_parameter"),
    ("setParam('gaprel'", "setRealParam('limits/gap'", "gap_parameter"),
    ("setRealParam(\"gap/rel\"", "setRealParam(\"limits/gap\"", "gap_parameter"),
    ("setRealParam('gap/rel'", "setRealParam('limits/gap'", "gap_parameter"),
    ("setRealParam(\"mip/gap\"", "setRealParam(\"limits/gap\"", "gap_parameter"),
    ("setRealParam('mip/gap'", "setRealParam('limits/gap'", "gap_parameter"),
    ("getObjval()", "getObjVal()", "objective_method"),
    ("getNsolns()", "getNSols()", "solution_count_method"),
    ('sense="min"', 'sense="minimize"', "objective_sense"),
    ("sense='min'", "sense='minimize'", "objective_sense"),
    ('sense="max"', 'sense="maximize"', "objective_sense"),
    ("sense='max'", "sense='maximize'", "objective_sense"),
    ("setObjective(obj_terms,", "setObjective(quicksum(obj_terms),", "objective_expression"),
    ("setObjective(objective_terms,", "setObjective(quicksum(objective_terms),", "objective_expression"),
    ("setObjective(obj,", "setObjective(quicksum(obj),", "objective_expression"),
    ("setObjective(expr,", "setObjective(quicksum(expr),", "objective_expression"),
    ("getOrigtime()", "getOrigTime()", "time_method"),
    ("getVarVal(", "getVal(", "variable_value_method"),
    ('"material_purchase"', '"procure_material"', "output_schema"),
    ("'material_purchase'", "'procure_material'", "output_schema"),
    ('"plant_startup"', '"startup"', "output_schema"),
    ("'plant_startup'", "'startup'", "output_schema"),
)


def repair_known_api_errors(code: str) -> tuple[str, list[dict]]:
    repaired = code
    applied = []
    for old, new, category in REPLACEMENTS:
        if old in repaired:
            repaired = repaired.replace(old, new)
            applied.append({"category": category, "from": old, "to": new})
    if not applied:
        return code, []
    try:
        ast.parse(repaired)
    except SyntaxError as exc:
        raise ValueError("API guard produced syntactically invalid code") from exc
    return repaired, applied

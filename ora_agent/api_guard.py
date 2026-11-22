"""Deterministic, auditable repairs for a narrow set of known PySCIPOpt API errors."""
from __future__ import annotations

import ast

REPLACEMENTS = (
    ("from pypscip import *", "from pyscipopt import *", "wrong_import"),
    ("from pycipopt import *", "from pyscipopt import *", "wrong_import"),
    ("from pypcipopt import *", "from pyscipopt import *", "wrong_import"),
    ("from pysis import ", "from pyscipopt import ", "wrong_import"),
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
    ("getNCons()", "getNConss()", "constraint_count_method"),
    ("getSolStatus()", "getStatus()", "status_method"),
    ("getOrigObjval()", "getObjVal()", "objective_method"),
    ("setParam(\"gaprel\"", "setRealParam(\"limits/gap\"", "gap_parameter"),
    ("setParam('gaprel'", "setRealParam('limits/gap'", "gap_parameter"),
    ("setRealParam(\"gaprel\"", "setRealParam(\"limits/gap\"", "gap_parameter"),
    ("setRealParam('gaprel'", "setRealParam('limits/gap'", "gap_parameter"),
    ("setParam(\"gap/rel\"", "setRealParam(\"limits/gap\"", "gap_parameter"),
    ("setParam('gap/rel'", "setRealParam('limits/gap'", "gap_parameter"),
    (".setMinimize(False)", ".setMaximize()", "objective_direction"),
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
)

OUTPUT_CONTRACT_REPLACEMENTS = {
    "industrial_supply_planning": (
        ('"material_purchase"', '"procure_material"', "procure_material"),
        ("'material_purchase'", "'procure_material'", "procure_material"),
        ('"plant_startup"', '"startup"', "startup"),
        ("'plant_startup'", "'startup'", "startup"),
    ),
}


class _VerifiedApiTransformer(ast.NodeVisitor):
    def __init__(self, code: str):
        self.code = code
        self.repairs = []
        self.replacements = []
        self.needs_quicksum = False
        self.scip_aliases = set()

    def visit_ImportFrom(self, node):
        if node.module != "pyscipopt":
            return
        invalid = [alias for alias in node.names if alias.name == "SCIP"]
        if not invalid:
            return
        for alias in invalid:
            self.scip_aliases.add(alias.asname or alias.name)
        kept = [alias for alias in node.names if alias.name != "SCIP"]
        imported = [alias.name + (f" as {alias.asname}" if alias.asname else "") for alias in kept]
        if not any(alias.name == "Model" and alias.asname is None for alias in kept):
            imported.insert(0, "Model")
        self.replacements.append((node, "from pyscipopt import " + ", ".join(imported)))
        self.repairs.append({"category": "wrong_import", "from": "SCIP import", "to": "Model import"})

    def visit_Call(self, node):
        self.generic_visit(node)
        function = node.func
        if isinstance(function, ast.Name) and function.id in self.scip_aliases:
            self.replacements.append((function, "Model"))
            self.repairs.append({"category": "model_construction", "from": "SCIP()", "to": "Model()"})
            return
        if not isinstance(function, ast.Attribute):
            return
        if function.attr == "quicksum":
            self.needs_quicksum = True
            self.replacements.append((function, "quicksum"))
            self.repairs.append({"category": "module_quicksum", "from": ".quicksum(", "to": "quicksum("})
        elif function.attr == "changeCoeff" and len(node.args) == 2 and not node.keywords \
                and isinstance(function.value, (ast.Name, ast.Attribute)):
            variable, coefficient = node.args
            receiver = ast.get_source_segment(self.code, function.value)
            variable_text = ast.get_source_segment(self.code, variable)
            coefficient_text = ast.get_source_segment(self.code, coefficient)
            if isinstance(coefficient, (ast.BinOp, ast.BoolOp, ast.Compare, ast.IfExp)):
                coefficient_text = f"({coefficient_text})"
            replacement = (f"{receiver}.setObjective({receiver}.getObjective() + "
                           f"{coefficient_text} * {variable_text})")
            self.replacements.append((node, replacement))
            self.repairs.append({"category": "objective_coefficient",
                                 "from": "changeCoeff(variable, coefficient)",
                                 "to": "setObjective(getObjective() + coefficient * variable)"})

    def visit_Compare(self, node):
        self.generic_visit(node)
        if len(node.ops) != 1 or not isinstance(node.ops[0], ast.NotIn) \
                or not isinstance(node.left, ast.Name) \
                or node.left.id not in {"status", "solver_status", "scip_status", "model_status"}:
            return
        for comparator in node.comparators:
            if not isinstance(comparator, (ast.List, ast.Tuple, ast.Set)):
                continue
            statuses = [element.value for element in comparator.elts
                        if isinstance(element, ast.Constant) and isinstance(element.value, str)]
            if "optimal" not in statuses or "gaplimit" in statuses:
                continue
            source = ast.get_source_segment(self.code, comparator)
            self.replacements.append((comparator, source[:-1] + ', "gaplimit"' + source[-1]))
            self.repairs.append({"category": "solver_status_acceptance",
                                 "from": "status whitelist without gaplimit",
                                 "to": "status whitelist with gaplimit"})


def _apply_verified_transformers(code: str) -> tuple[str, list[dict]]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError("incomplete_artifact: API guard could not parse solver code") from exc
    if not any(isinstance(node, ast.ImportFrom) and node.module == "pyscipopt" for node in ast.walk(tree)):
        return code, []
    transformer = _VerifiedApiTransformer(code)
    transformer.visit(tree)
    if not transformer.replacements:
        return code, []
    imported = any(isinstance(node, ast.ImportFrom) and node.module == "pyscipopt"
                   and any(alias.name == "quicksum" and alias.asname is None for alias in node.names)
                   for node in tree.body)
    insertions = []
    if transformer.needs_quicksum and not imported:
        index = max((index for index, node in enumerate(tree.body)
                     if isinstance(node, (ast.Import, ast.ImportFrom))), default=-1)
        insertions.append((tree.body[index].end_lineno + 1 if index >= 0 else 1,
                           "from pyscipopt import quicksum\n"))
    lines = [line.encode("utf-8") for line in code.splitlines(keepends=True)]

    def offset(lineno, column):
        return sum(len(line) for line in lines[:lineno - 1]) + column

    spans = sorted((offset(node.lineno, node.col_offset), offset(node.end_lineno, node.end_col_offset), text)
                   for node, text in transformer.replacements)
    if any(next_span[0] < span[1] for span, next_span in zip(spans, spans[1:])):
        raise ValueError("unsupported nested API guard rewrite")
    for lineno, text in insertions:
        spans.append((offset(lineno, 0), offset(lineno, 0), text))
    transformed = bytearray(code.encode("utf-8"))
    for start, end, text in sorted(spans, reverse=True):
        transformed[start:end] = text.encode("utf-8")
    return transformed.decode("utf-8"), transformer.repairs


def repair_known_api_errors(code: str) -> tuple[str, list[dict]]:
    repaired = code
    applied = []
    for old, new, category in REPLACEMENTS:
        if old in repaired:
            repaired = repaired.replace(old, new)
            applied.append({"category": category, "from": old, "to": new})
    transformed, ast_applied = _apply_verified_transformers(repaired)
    applied.extend(ast_applied)
    if not applied:
        return code, []
    try:
        ast.parse(transformed)
    except SyntaxError as exc:
        raise ValueError("API guard produced syntactically invalid code") from exc
    return transformed, applied


def repair_public_output_contract(code: str, task_name: str, public_document: str) -> tuple[str, list[dict]]:
    applied = []
    for old, new, source_quote in OUTPUT_CONTRACT_REPLACEMENTS.get(task_name, ()):
        if source_quote not in public_document or old not in code:
            continue
        code = code.replace(old, new)
        applied.append({"category": "public_output_contract", "scope": task_name,
                        "source_quote": source_quote, "from": old, "to": new})
    return code, applied

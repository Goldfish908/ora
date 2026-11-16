"""Leakage-controlled candidate features for the pairwise repair pilot."""
from __future__ import annotations

import ast
import math
import re
import statistics
from collections import Counter
from typing import Mapping, Optional


_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_]\w*\b")

_NODE_TYPES = (
    "Assign", "AnnAssign", "AugAssign", "For", "While", "If", "FunctionDef",
    "Call", "Compare", "BinOp", "BoolOp", "UnaryOp", "Subscript", "Dict",
    "List", "Tuple", "GeneratorExp", "ListComp", "DictComp", "Name", "Constant",
)
_CALL_NAMES = (
    "addVar", "addCons", "setObjective", "optimize", "getVal", "quicksum",
    "hideOutput", "setRealParam", "dump", "open",
)
_MODEL_NAMES = ("Q", "I", "sales", "W", "lost", "sub", "X", "y", "m", "data")
_CONCEPT_PATTERNS = {
    "availability": (r"sales availability|sales\s*\[.*\]\s*<=|availability", r"avail"),
    "production_capacity": (r"production capacit|aggregate production", r"production_cap|pcap"),
    "cold_capacity": (r"cold.storage|cold_capacity", r"cold_cap|cold_usage|cold"),
    "labor_capacity": (r"labor capacit|labor_cap", r"labor_cap|labor_usage|labor"),
    "demand_balance": (r"demand fulfillment|demand balance|lost sales", r"demand_|lost"),
    "aging": (r"aging:|inventory tomorrow|remaining life", r"age_|aging"),
    "initial_inventory": (r"initial inventory|period.?1 inventory|I\[.*1.*\]\s*=\s*0", r"init_|initial"),
    "waste": (r"waste|expir", r"waste|\bw\b"),
    "budget": (r"budget", r"budget"),
    "moq": (r"\bmoq\b|minimum order", r"moq"),
    "pack_size": (r"pack.size|pack_size", r"pack_size|n_pack"),
    "fixed_order": (r"fixed.order|fixed_order", r"fixed_order"),
    "transshipment": (r"transshipment", r"trans_edges|transship|trans_in|trans_out"),
    "substitution": (r"substitution|sub_edges", r"sub_edges|sub_in|sub_out"),
    "lead_time": (r"lead.time|lead_time", r"lead_time|\blt\b"),
    "shelf_life": (r"shelf.life|shelf_life", r"shelf_life|\bsl\b"),
}


def style_features(prompt: str, code: str,
                   execution: Optional[Mapping] = None) -> dict:
    """Return only surface length/style features; prompt and execution are unused."""
    del prompt, execution
    lines = code.splitlines()
    nonempty = [line for line in lines if line.strip()]
    lengths = [len(line) for line in lines]
    comments = [line for line in lines if line.lstrip().startswith("#")]
    identifiers = _IDENTIFIER_RE.findall(code)
    identifier_lengths = [len(token) for token in identifiers]
    return {
        "char_count": float(len(code)),
        "line_count": float(len(lines)),
        "nonempty_line_count": float(len(nonempty)),
        "blank_line_count": float(len(lines) - len(nonempty)),
        "comment_line_count": float(len(comments)),
        "comment_char_count": float(sum(len(line) for line in comments)),
        "comment_line_ratio": len(comments) / max(1, len(lines)),
        "inline_comment_count": float(sum(
            "#" in line and not line.lstrip().startswith("#") for line in lines)),
        "mean_line_length": statistics.mean(lengths) if lengths else 0.0,
        "median_line_length": statistics.median(lengths) if lengths else 0.0,
        "max_line_length": float(max(lengths, default=0)),
        "mean_indent": statistics.mean(
            [len(line) - len(line.lstrip(" \t")) for line in nonempty]
        ) if nonempty else 0.0,
        "tab_line_count": float(sum(line.startswith("\t") for line in lines)),
        "trailing_space_line_count": float(sum(
            line.rstrip() != line for line in lines)),
        "identifier_count": float(len(identifiers)),
        "identifier_mean_length": statistics.mean(identifier_lengths) if identifiers else 0.0,
        "single_quote_count": float(code.count("'")),
        "double_quote_count": float(code.count('"')),
        "markdown_fence_count": float(code.count("```")),
        "non_ascii_char_count": float(sum(ord(char) > 127 for char in code)),
    }


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _empty_structural_features() -> dict:
    features = {"ast_valid": 0.0, "ast_node_count": 0.0, "ast_depth": 0.0}
    for node_type in _NODE_TYPES:
        features[f"node_{node_type}"] = 0.0
    for call_name in _CALL_NAMES:
        features[f"call_{call_name}"] = 0.0
        features[f"density_{call_name}"] = 0.0
    for name in _MODEL_NAMES:
        features[f"name_{name}"] = 0.0
    for operator in ("Eq", "LtE", "GtE", "Add", "Sub", "Mult", "Div"):
        features[f"operator_{operator}"] = 0.0
    features["execution_available"] = 0.0
    return features


def _execution_features(execution: Optional[Mapping]) -> dict:
    if execution is None:
        return {"execution_available": 0.0}
    exec_status = str(execution.get("exec_status", ""))
    solver_status = str(execution.get("solver_status", ""))
    violations = execution.get("witness_rules") or execution.get("violations") or []
    objective = execution.get("objective")
    try:
        wall_s = float(execution.get("wall_s", 0.0))
    except (TypeError, ValueError):
        wall_s = 0.0
    try:
        objective_finite = float(objective is not None and math.isfinite(float(objective)))
    except (TypeError, ValueError):
        objective_finite = 0.0
    return {
        "execution_available": 1.0,
        "execution_ok": float(exec_status == "ok"),
        "execution_crash": float(exec_status == "crash"),
        "execution_timeout": float(exec_status == "timeout"),
        "solver_optimal": float(solver_status == "optimal"),
        "solver_infeasible": float(solver_status == "infeasible"),
        "objective_finite": objective_finite,
        "log_wall_s": math.log1p(max(0.0, wall_s)),
        "witness_violation_count": float(len(violations)),
        "witness_warning_count": float(execution.get("witness_warnings", 0.0) or 0.0),
    }


def structural_features(prompt: str, code: str,
                        execution: Optional[Mapping] = None) -> dict:
    """Extract AST, solver-call, and generic prompt/code alignment features.

    Only allowlisted execution fields are read. Metadata and raw prompt tokens are
    deliberately not represented.
    """
    features = _empty_structural_features()
    features.update(_execution_features(execution))
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, TypeError):
        features["syntax_error"] = 1.0
        return features

    features["ast_valid"] = 1.0
    features["syntax_error"] = 0.0
    nodes = list(ast.walk(tree))
    features["ast_node_count"] = float(len(nodes))

    def depth(node: ast.AST) -> int:
        children = list(ast.iter_child_nodes(node))
        return 1 + max((depth(child) for child in children), default=0)

    features["ast_depth"] = float(depth(tree))
    node_counts = Counter(type(node).__name__ for node in nodes)
    for node_type in _NODE_TYPES:
        features[f"node_{node_type}"] = float(node_counts[node_type])

    call_counts = Counter(
        _call_name(node.func) for node in nodes if isinstance(node, ast.Call))
    for call_name in _CALL_NAMES:
        features[f"call_{call_name}"] = float(call_counts[call_name])
        features[f"density_{call_name}"] = (
            1000.0 * call_counts[call_name] / max(1, len(nodes)))

    names = Counter(node.id for node in nodes if isinstance(node, ast.Name))
    for name in _MODEL_NAMES:
        features[f"name_{name}"] = float(names[name])
    operator_types = (ast.Eq, ast.LtE, ast.GtE, ast.Add, ast.Sub, ast.Mult, ast.Div)
    for operator_type in operator_types:
        name = operator_type.__name__
        features[f"operator_{name}"] = float(sum(
            isinstance(node, operator_type) for node in nodes))

    strings = [node.value for node in nodes
               if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    structural_text = " ".join(strings + list(names)).lower()
    prompt_lower = prompt.lower()
    for concept, (prompt_pattern, code_pattern) in _CONCEPT_PATTERNS.items():
        prompt_has = bool(re.search(prompt_pattern, prompt_lower, re.DOTALL))
        code_has = bool(re.search(code_pattern, structural_text, re.DOTALL))
        features[f"prompt_code_{concept}"] = float(prompt_has and code_has)
        features[f"prompt_missing_{concept}"] = float(prompt_has and not code_has)
    return features


def feature_difference(feature_kind: str, prompt: str, chosen: str, rejected: str,
                       chosen_execution: Optional[Mapping] = None,
                       rejected_execution: Optional[Mapping] = None) -> dict:
    """Return chosen-minus-rejected features without reading pair metadata."""
    extractor = style_features if feature_kind == "style" else structural_features
    if feature_kind not in ("style", "ast"):
        raise ValueError(f"unknown numeric feature kind: {feature_kind}")
    positive = extractor(prompt, chosen, chosen_execution)
    negative = extractor(prompt, rejected, rejected_execution)
    return {key: float(positive.get(key, 0.0)) - float(negative.get(key, 0.0))
            for key in set(positive) | set(negative)}

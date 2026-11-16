"""Candidate-code to business-schema binding with explicit pre-solve evidence."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

from ora_agent import llm as llm_mod
from ora_agent.scoped_ir import extract_spec
from scripts.industryor_next_stage import _variable_specs, instrument_code

PROMPT = """You bind PySCIPOpt variables to an independent business audit schema.
Return ONLY one JSON object:
{{"aliases":[{{"solver_name":"actual solver variable name","semantic_name":"schema variable name","evidence":"short VERBATIM code span supporting this role"}}]}}

[BUSINESS QUESTION]
{question}

[CANDIDATE CODE]
{code}

[REQUIRED SEMANTIC VARIABLES]
{contract}

[OBSERVED SOLVER VARIABLE NAMES AND TYPES]
{observed}

Rules:
1. Map every required schema variable exactly once when its role exists in the model.
2. solver_name must be the model's exported variable name, not a Python dictionary or list expression.
3. evidence must be copied exactly from the candidate code and must support the semantic role or index mapping.
4. Do not infer a different business meaning merely to make names match. If a required role is absent, omit its alias.
5. Do not change objectives, constraints, domains, or numerical values. This is only a name-binding proposal.
6. Do not use or guess a reference objective. The business question and candidate code are the only modeling inputs.
"""


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def semantic_contract(problem_id: int) -> dict:
    return copy.deepcopy(_variable_specs(problem_id))


def _addvar_metadata(call: ast.Call) -> tuple[ast.AST | None, str]:
    name_node = None
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        name_node = call.args[0]
    for keyword in call.keywords:
        if keyword.arg == "name" and isinstance(keyword.value, (ast.Constant, ast.JoinedStr)):
            name_node = keyword.value
    vtype = next((keyword.value.value for keyword in call.keywords
                  if keyword.arg == "vtype" and isinstance(keyword.value, ast.Constant)), "C")
    return name_node, vtype


def _name_template(node: ast.AST | None, variable: str) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if not isinstance(node, ast.JoinedStr):
        return None
    parts = []
    substitutions = 0
    for item in node.values:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            parts.append(item.value)
        elif (isinstance(item, ast.FormattedValue) and isinstance(item.value, ast.Name)
              and item.value.id == variable and item.format_spec is None):
            parts.append("{}")
            substitutions += 1
        else:
            return None
    return "".join(parts) if substitutions == 1 else None


def _collection(node: ast.AST, literals: dict) -> list | None:
    if isinstance(node, (ast.List, ast.Tuple)):
        try:
            value = ast.literal_eval(node)
        except (ValueError, TypeError):
            return None
        return list(value) if all(isinstance(item, (str, int)) and not isinstance(item, bool)
                                  for item in value) else None
    if isinstance(node, ast.Name):
        return literals.get(node.id)
    return None


def declaration_index(code: str) -> dict:
    tree = ast.parse(code)
    literals = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            values = _collection(node.value, literals)
            if values is not None:
                literals[node.targets[0].id] = values
    result = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "addVar":
            name_node, vtype = _addvar_metadata(node.value)
            if not isinstance(name_node, ast.Constant):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result[name_node.value] = {"local_name": target.id, "vtype": vtype}
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        container = node.targets[0].id
        if isinstance(node.value, ast.DictComp) and len(node.value.generators) == 1:
            generator = node.value.generators[0]
            call = node.value.value
            if not (isinstance(generator.target, ast.Name) and isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute) and call.func.attr == "addVar"):
                continue
            variable = generator.target.id
            values = _collection(generator.iter, literals)
            template = _name_template(_addvar_metadata(call)[0], variable)
            vtype = _addvar_metadata(call)[1]
            if values is None or template is None or not isinstance(node.value.key, ast.Name) \
                    or node.value.key.id != variable:
                continue
            for value in values:
                result[template.format(value)] = {"local_name": f"{container}[{value!r}]", "vtype": vtype}
    for node in tree.body:
        if not (isinstance(node, ast.For) and isinstance(node.target, ast.Name) and len(node.body) == 1
                and isinstance(node.body[0], ast.Assign)):
            continue
        variable = node.target.id
        values = _collection(node.iter, literals)
        assignment = node.body[0]
        if len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Subscript):
            continue
        target = assignment.targets[0]
        if not (isinstance(target.value, ast.Name) and isinstance(target.slice, ast.Name)
                and target.slice.id == variable and isinstance(assignment.value, ast.Call)
                and isinstance(assignment.value.func, ast.Attribute)
                and assignment.value.func.attr == "addVar"):
            continue
        template = _name_template(_addvar_metadata(assignment.value)[0], variable)
        vtype = _addvar_metadata(assignment.value)[1]
        if values is None or template is None:
            continue
        for value in values:
            result[template.format(value)] = {"local_name": f"{target.value.id}[{value!r}]", "vtype": vtype}
    return result


def observed_contract(solution: dict | None) -> dict:
    if not isinstance(solution, dict) or not isinstance(solution.get("variables"), dict):
        return {}
    types = solution.get("variable_types") if isinstance(solution.get("variable_types"), dict) else {}
    return {name: {"vtype": types.get(name)} for name in solution["variables"]}


def domain_matches(expected: str, actual: str | None) -> bool | None:
    if actual is None:
        return None
    normalized = actual.upper()
    if normalized in {"CONTINUOUS", "C"}:
        actual_domain = "continuous"
    elif normalized in {"INTEGER", "I", "INT"}:
        actual_domain = "integer"
    elif normalized in {"BINARY", "B", "BOOL", "BOOLEAN"}:
        actual_domain = "binary"
    else:
        return False
    if expected == "continuous":
        return actual_domain in {"continuous", "integer", "binary"}
    return expected == actual_domain


def validate_binding(problem_id: int, code: str, aliases: dict,
                     solution: dict | None = None) -> dict:
    contract = semantic_contract(problem_id)
    required = {name for name, spec in contract.items() if spec["required_for_audit"]}
    errors = []
    if not isinstance(aliases, dict):
        aliases = {}
        errors.append("aliases must be an object")
    if any(not isinstance(key, str) or not key or not isinstance(value, str) or not value
           for key, value in aliases.items()):
        errors.append("alias names must be nonempty strings")
    unknown_semantics = sorted(set(aliases.values()) - set(contract))
    if unknown_semantics:
        errors.append("unknown semantic names: " + ", ".join(unknown_semantics))
    destinations = list(aliases.values())
    if len(destinations) != len(set(destinations)):
        errors.append("multiple solver variables map to the same semantic variable")
    missing = sorted(required - set(destinations))
    declarations = declaration_index(code)
    observed = observed_contract(solution)
    unresolved = []
    domain_mismatches = []
    local_aliases = {}
    for solver_name, semantic_name in aliases.items():
        evidence = declarations.get(solver_name) or observed.get(solver_name)
        if evidence is None:
            unresolved.append(solver_name)
            continue
        expected_domain = contract.get(semantic_name, {}).get("domain")
        if expected_domain:
            consistent = domain_matches(expected_domain, evidence.get("vtype"))
            if consistent is False:
                domain_mismatches.append({"solver_name": solver_name,
                                          "semantic_name": semantic_name,
                                          "expected": expected_domain, "actual": evidence.get("vtype")})
        if solver_name in declarations:
            local_aliases[semantic_name] = declarations[solver_name]["local_name"]
    export_error = None
    try:
        instrument_code(code, aliases)
    except (ValueError, TypeError, SyntaxError) as exc:
        export_error = f"{type(exc).__name__}: {exc}"
    if observed and unresolved:
        errors.append("solver names are absent from the observed export: " + ", ".join(unresolved))
    if errors or missing or (observed and unresolved):
        status = "needs_binding_evidence"
    elif export_error or domain_mismatches:
        status = "needs_model_repair"
    else:
        status = "ready"
    return {
        "status": status, "accepted_for_execution": status == "ready",
        "business_correct": False, "aliases": aliases, "repair_aliases": local_aliases,
        "required_semantic_names": sorted(required), "covered_semantic_names": sorted(set(destinations) & required),
        "missing_semantic_names": missing, "unresolved_solver_names": sorted(unresolved),
        "domain_mismatches": domain_mismatches, "export_error": export_error,
        "errors": errors, "runtime_verification_required": True,
        "scope": "name binding and declared domains only; constraints and objective require independent post-solve audit",
    }


def reconcile_binding(problem_id: int, code: str, aliases: dict,
                      solution: dict | None = None) -> dict:
    try:
        declarations = declaration_index(code)
    except SyntaxError as exc:
        return {"status": "error", "accepted_for_execution": False, "business_correct": False,
                "aliases": {}, "repair_aliases": {}, "errors": [f"SyntaxError: {exc}"]}
    observed = observed_contract(solution)
    available = set(declarations) | set(observed)
    rebound = {solver: semantic for solver, semantic in aliases.items() if solver in available}
    canonical = []
    for semantic in semantic_contract(problem_id):
        if semantic in declarations:
            rebound = {solver: target for solver, target in rebound.items() if target != semantic}
            rebound[semantic] = semantic
            canonical.append(semantic)
    gate = validate_binding(problem_id, code, rebound, solution)
    gate["pruned_solver_names"] = sorted(set(aliases) - set(rebound))
    gate["canonical_identity_bindings"] = canonical
    gate["rebinding_required"] = gate["status"] != "ready"
    return gate


def binding_prompt(problem_id: int, question: str, code: str, solution: dict | None = None) -> str:
    contract = semantic_contract(problem_id)
    observed = observed_contract(solution)
    return PROMPT.format(question=question, code=code,
                         contract=json.dumps(contract, ensure_ascii=False, indent=1),
                         observed=json.dumps(observed, ensure_ascii=False, indent=1))


def parse_aliases(payload: dict, question: str, code: str) -> tuple[dict, list[str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("aliases"), list):
        return {}, ["response must contain an aliases list"]
    aliases = {}
    errors = []
    for index, item in enumerate(payload["aliases"]):
        if not isinstance(item, dict):
            errors.append(f"alias {index} is not an object")
            continue
        solver_name = item.get("solver_name")
        semantic_name = item.get("semantic_name")
        evidence = item.get("evidence")
        if not isinstance(solver_name, str) or not solver_name or not isinstance(semantic_name, str) or not semantic_name:
            errors.append(f"alias {index} has invalid names")
            continue
        if solver_name in aliases:
            errors.append(f"duplicate solver_name: {solver_name}")
            continue
        if not isinstance(evidence, str) or not evidence or evidence not in code:
            errors.append(f"evidence is not a verbatim candidate-code span: {solver_name}")
        aliases[solver_name] = semantic_name
    return aliases, errors


def propose_binding(problem_id: int, question: str, code: str, solution: dict | None,
                    cache_path: Path, config=None) -> dict:
    prompt = binding_prompt(problem_id, question, code, solution)
    if cache_path.exists():
        record = json.loads(cache_path.read_text())
        if record.get("prompt_sha256") != digest(prompt):
            raise ValueError("cached semantic binding belongs to a different prompt")
        record["new_llm_calls"] = 0
        record["reused"] = True
        return record
    try:
        response = llm_mod.chat([{"role": "user", "content": prompt}], max_tokens=32768,
                                temperature=0.2, extra={"reasoning_effort": "medium"}, config=config)
        if config is not None and response.get("model") != config.model:
            raise ValueError(f"returned model differs from requested model: {response.get('model')}")
        aliases, parse_errors = parse_aliases(extract_spec(response.get("content") or ""), question, code)
        gate = validate_binding(problem_id, code, aliases, solution)
        gate["errors"] = parse_errors + gate["errors"]
        if gate["errors"]:
            gate["status"] = "needs_binding_evidence"
            gate["accepted_for_execution"] = False
        error = None
    except Exception as exc:
        response = {"request_attempts": getattr(exc, "request_attempts", [])}
        aliases = []
        gate = {"status": "error", "accepted_for_execution": False,
                "business_correct": False, "errors": [f"{type(exc).__name__}: {exc}"]}
        error = gate["errors"][0]
    record = {"problem_id": problem_id, "prompt": prompt, "prompt_sha256": digest(prompt),
              "response": response, "gate": gate, "error": error,
              "new_llm_calls": 1, "reused": False,
              "api_attempts": len(response.get("request_attempts") or [None]),
              "public_answer_in_prompt": False}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(record, ensure_ascii=False, indent=1, allow_nan=False) + "\n")
    return record

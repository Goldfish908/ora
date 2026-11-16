"""Versioned DVSA templates with explicit per-instance bindings."""
from __future__ import annotations

import copy
import hashlib
import json

from ora_agent.dvsa import asset_sha256, run_asset, validate_asset


def load_library(path):
    library = json.loads(path.read_text())
    if not isinstance(library, dict) or not isinstance(library.get("templates"), list):
        raise ValueError("template library must contain a templates list")
    templates = {}
    for asset in library["templates"]:
        validate_asset(asset)
        if asset["asset_id"] in templates:
            raise ValueError(f"duplicate template: {asset['asset_id']}")
        templates[asset["asset_id"]] = asset
    return library, templates


def binding_sha256(template, binding, source):
    value = {"template_id": template["asset_id"],
             "template_sha256": asset_sha256(template),
             "binding": binding, "source": source}
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_binding(binding, source, question, declared_variables=None):
    if not isinstance(binding, dict):
        raise ValueError("binding must be an object")
    json.dumps(binding, allow_nan=False)
    normalize = lambda value: " ".join(value.split()).casefold()
    if not isinstance(source, str) or len(source.strip()) < 8:
        raise ValueError("binding source must be a verbatim span of at least 8 characters")
    if normalize(source) not in normalize(question):
        raise ValueError("binding source is not present in the problem")
    variables = set()
    for key in ("terms", "positive_terms", "negative_terms"):
        for term in binding.get(key, []):
            if isinstance(term, dict) and isinstance(term.get("variable"), str):
                variables.add(term["variable"])
    for key in ("numerator", "variable"):
        if isinstance(binding.get(key), str):
            variables.add(binding[key])
    for key in ("denominator", "incoming", "outgoing"):
        value = binding.get(key, [])
        if isinstance(value, list):
            variables.update(item for item in value if isinstance(item, str))
    if declared_variables is not None:
        unknown = variables - set(declared_variables)
        if unknown:
            raise ValueError(f"binding uses undeclared variables: {sorted(unknown)}")
    return sorted(variables)


def audit_instance(template, binding, source, solution):
    instance = copy.deepcopy(template)
    result = run_asset(instance, binding, solution, domain="bwor.scalar")
    return {**result, "template_id": template["asset_id"],
            "template_sha256": asset_sha256(template),
            "binding_sha256": binding_sha256(template, binding, source),
            "source": source, "binding": binding}

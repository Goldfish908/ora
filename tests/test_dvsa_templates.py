import json
from pathlib import Path

import pytest

from ora_agent.dvsa_templates import (audit_instance, binding_sha256,
                                      load_library, validate_binding)
from scripts.dvsa_template_audit import controlled_mutations

ROOT = Path(__file__).resolve().parents[1]


def template():
    _, templates = load_library(ROOT / "assets/dvsa/bwor_primitives_v0.1.json")
    return templates["bwor.resource_capacity"]


def binding(limit=4):
    return {"terms": [{"variable": "x", "coefficient": 1},
                      {"variable": "y", "coefficient": 1}], "limit": limit}


def test_resource_template_replays_without_code_change():
    asset = template()
    source = "total capacity is four"
    first = audit_instance(asset, binding(), source, {"variables": {"x": 2, "y": 2}})
    second = audit_instance(asset, binding(10), source, {"variables": {"x": 4, "y": 6}})
    assert first["status"] == second["status"] == "SATISFIED"
    assert first["template_sha256"] == second["template_sha256"]
    assert first["binding_sha256"] != second["binding_sha256"]


def test_resource_template_detects_numeric_violation_and_unknown_binding():
    asset = template()
    source = "total capacity is four"
    wrong = audit_instance(asset, binding(), source, {"variables": {"x": 3, "y": 2}})
    unknown = audit_instance(asset, binding(), source, {"variables": {"x": 3}})
    assert wrong["status"] == "VIOLATED"
    assert wrong["violations"][0]["lhs"] == 5
    assert unknown["status"] == "UNKNOWN"


def test_binding_requires_verbatim_source_and_declared_variables():
    with pytest.raises(ValueError, match="not present"):
        validate_binding(binding(), "an invented capacity", "total capacity is four", {"x", "y"})
    with pytest.raises(ValueError, match="undeclared"):
        validate_binding(binding(), "capacity is four", "total capacity is four", {"x"})


def test_binding_hash_covers_template_version_and_values():
    asset = template()
    source = "total capacity is four"
    assert binding_sha256(asset, binding(), source) != binding_sha256(asset, binding(5), source)


def test_controlled_mutations_have_reference_labels_not_template_labels():
    model = {
        "schema_version": "dvsa.model.v0.1", "problem_id": "toy",
        "variables": {"x": {"domain": "real", "lb": 0}, "y": {"domain": "real", "lb": 0}},
        "data": {"limit": 4},
        "constraints": [{"constraint_id": "capacity", "source": "total capacity is four",
                         "relation": "le", "lhs": {"add": [{"var": "x"}, {"var": "y"}]},
                         "rhs": {"path": "data.limit"}}],
        "objective": {"sense": "maximize", "expression": {"add": [{"var": "x"}, {"var": "y"}]}},
    }
    clean = {"variables": {"x": 2, "y": 2}, "objective": 4}
    cells = controlled_mutations(model, clean)
    assert cells[0]["wrong"] is False
    targeted = {cell["expected_rule"]: cell for cell in cells if cell["wrong"]}
    assert targeted["capacity"]["solution"]["variables"] != clean["variables"]
    assert "capacity" in targeted["capacity"]["reference_violations"]
    assert "OBJECTIVE" not in targeted["capacity"]["reference_violations"]
    assert targeted["capacity"]["solution"]["objective"] == sum(
        targeted["capacity"]["solution"]["variables"].values())
    assert targeted["OBJECTIVE"]["solution"]["variables"] == clean["variables"]
    assert targeted["OBJECTIVE"]["solution"]["objective"] > clean["objective"]

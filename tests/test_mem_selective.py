from scripts.mem_selective import select_conventions, select_conventions_with_trace


TEXT = """[SEMANTIC CONVENTIONS]
1. Always keep this universal clause.
[TRIGGER: sub_edges]
2. Apply only when substitution edges exist.
3. Always keep this later universal clause.
[TRIGGER: constraints_moq]
4. This predicate is intentionally unsupported and stays off.
[TRIGGER: moq]
5. Apply only for a positive MOQ.
"""


def test_nested_substitution_trigger_fires_and_unmarked_clauses_stay():
    selected, trace = select_conventions_with_trace(
        TEXT, {"network": {"sub_edges": [["A", "B"]]}})
    assert "2. Apply only when substitution edges exist." in selected
    assert "1. Always keep" in selected
    assert "3. Always keep" in selected
    assert trace[0]["active"] is True
    assert "[TRIGGER:" not in selected


def test_empty_nested_substitution_drops_only_its_clause():
    selected, trace = select_conventions_with_trace(
        TEXT, {"network": {"sub_edges": []}})
    assert "2. Apply only when substitution edges exist." not in selected
    assert "1. Always keep" in selected
    assert "3. Always keep" in selected
    assert trace[0]["active"] is False


def test_nested_moq_and_negation():
    data = {"network": {"sub_edges": []}, "constraints": {"moq": 4}}
    selected, trace = select_conventions_with_trace(TEXT, data)
    assert "5. Apply only for a positive MOQ." in selected
    assert not any(t["predicate"] == "no_substitution" for t in trace)
    assert select_conventions("[TRIGGER: no_substitution]\n1. No-sub only.", data)
    assert not select_conventions("[TRIGGER: not:no_substitution]\n1. Sub only.", data)


def test_zero_moq_does_not_fire():
    selected, trace = select_conventions_with_trace(
        TEXT, {"network": {"sub_edges": []}, "constraints": {"moq": 0}})
    assert "5. Apply only for a positive MOQ." not in selected
    assert next(t for t in trace if t["predicate"] == "moq")["active"] is False

from ora_agent.trigger_memory import CARDS, memory_for, registry_digest


def test_trigger_selects_scoped_positive_and_negative_assets():
    memory = memory_for(20, {"missing_semantic_names": [], "repair_aliases": {}},
                        {"audit_status": "complete", "violations": ["business constraint failed: link_x3_y3"]},
                        "trigger")
    assert "indicator_bidirectional_v1" in memory["asset_ids"]
    assert "regenerate_rebind_v1" in memory["asset_ids"]
    assert "objective_consistency_v1" not in memory["asset_ids"]
    assert memory["read_only"] is True
    assert memory["online_learning"] is False
    assert "independent_upper_bound" in memory["text"]
    assert "en_answer" not in memory["text"]
    assert "11250" not in memory["text"]


def test_full_memory_includes_all_assets_and_objective_counterexample():
    memory = memory_for(48, {"missing_semantic_names": ["x_A"], "repair_aliases": {}},
                        {"audit_status": "complete", "model_objective_consistent": False,
                         "violations": ["reported model objective differs"]}, "full")
    assert set(memory["asset_ids"]) == set(CARDS)
    assert "Goal-programming" in memory["text"]
    assert "must remain rejected" in memory["text"]
    assert memory["memory_sha256"]
    assert registry_digest()


def test_no_memory_mode_has_no_prompt_content():
    memory = memory_for(20, {}, {}, "none")
    assert memory["text"] == ""
    assert memory["asset_ids"] == []
    assert memory["memory_sha256"] is None

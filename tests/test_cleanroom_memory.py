from ora_agent.cleanroom import EvidenceMemory, SpecificationAsset, restore_specifications


def test_specification_round_trip_preserves_text_audit_and_freeze():
    scope = {"dataset": "oragentbench", "domain": "manufacturing"}
    memory = EvidenceMemory()
    memory.register_specification(SpecificationAsset("spec_v1", "use integer production", scope))
    memory.promote_specification("spec_v1", {"independent_replay": True,
                                             "changed_features_covered": True,
                                             "scope_confirmed": True})
    memory.freeze()
    payload = memory.public_state(include_spec_text=True)

    restored = restore_specifications(payload)
    asset = restored.generator_specification(scope)
    assert asset.text == "use integer production"
    assert asset.text_sha256 == payload["specifications"][0]["text_sha256"]
    assert restored.frozen

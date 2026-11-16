from scripts.dvsa_split import SIZES, allocate, build


def test_allocation_is_deterministic_disjoint_and_complete():
    ids = [f"problem_{i}" for i in range(73)]
    first = allocate(ids)
    second = allocate(list(reversed(ids)))
    assert first == second
    assert {name: len(values) for name, values in first.items()} == SIZES
    combined = first["dev"] + first["validation"] + first["frozen"]
    assert len(combined) == len(set(combined)) == 73
    assert set(combined) == set(ids)


def test_bwor_protocol_uses_only_declared_metadata_and_reproduces():
    manifest, files, manifest_bytes = build()
    again_manifest, again_files, again_bytes = build()
    assert manifest == again_manifest
    assert files == again_files
    assert manifest_bytes == again_bytes
    assert manifest["source_release_n"] == 82
    assert manifest["eligible_n"] == 73
    assert manifest["selection"]["problem_type"] == ["LP", "IP", "MIP"]
    assert manifest["excluded_by_metadata"] == {
        "no_optimal:IP": 1, "no_optimal:LP": 1,
        "optimal:NLP": 5, "optimal:goal_programming": 2}
    assert sum(record["n"] for record in manifest["splits"].values()) == 73
    assert manifest["exposed_ids_forced_dev"] == []

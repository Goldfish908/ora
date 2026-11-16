import json

from scripts.procedural_memory_analyze import accepted_precision, load_arm
from scripts.procedural_memory_pilot import (
    PROCEDURE_GUIDANCE,
    TEXT_GUIDANCE,
    build_prompt,
    usage_totals,
)


def test_memory_arms_share_contract_but_not_guidance():
    for arm in ("zero", "text", "procedure", "combined", "procedure_cegis"):
        prompt = build_prompt(arm, "question", '{"variables": {}}')
        assert "question" in prompt
        assert "Output ONLY executable Python code" in prompt
        assert (TEXT_GUIDANCE in prompt) == (arm in ("text", "combined"))
        assert (PROCEDURE_GUIDANCE in prompt) == (
            arm in ("procedure", "combined", "procedure_cegis"))


def test_unknown_arm_is_rejected():
    try:
        build_prompt("unknown", "question", "schema")
        assert False, "unknown arm must fail"
    except ValueError:
        pass


def test_accepted_precision_includes_fail_open_unknown_as_accepted():
    records = [
        {"wrong": False, "fired": False, "status": "ok"},
        {"wrong": True, "fired": False, "status": "unknown"},
        {"wrong": True, "fired": True, "status": "ok"},
    ]
    assert accepted_precision(records) == 0.5


def test_usage_totals_cover_all_attempts():
    usage = usage_totals([
        {"usage": {"prompt_tokens": 10, "completion_tokens": 3}},
        {"usage": {"prompt_tokens": 7, "completion_tokens": 2}},
    ])
    assert usage == {"prompt_tokens": 17, "completion_tokens": 5, "total_tokens": 22}


def test_load_arm_reports_missing_cells_as_unknown(tmp_path):
    run_dir = tmp_path / "runs"
    final_dir = run_dir / "zero" / "p0"
    final_dir.mkdir(parents=True)
    final = {
        "id": "p0",
        "evaluation": {"records": []},
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        "latency_s": 1.5,
    }
    (final_dir / "final.json").write_text(json.dumps(final))
    cells = [{"id": "p0", "key": "p0|0", "wrong": True}]
    loaded = load_arm(run_dir, "zero", cells)
    assert loaded["metrics"]["unknown"] == 1
    assert loaded["metrics"]["usage"]["total_tokens"] == 6
    assert loaded["metrics"]["latency_s"] == 1.5

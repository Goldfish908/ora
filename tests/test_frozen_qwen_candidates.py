import json

from scripts.frozen_qwen_candidates import emit_result, generation_config


def test_emit_result_writes_one_valid_progress_record(capsys):
    emit_result({"problem_id": "BWOR-002", "status": "invalid_candidate",
                 "score": {"business_correct": False}, "wall_s": 1.25})
    output = capsys.readouterr().out
    record = json.loads(output)
    assert record == {"id": "BWOR-002", "status": "invalid_candidate",
                      "business_correct": False, "latency_s": 1.25}


def test_generation_is_frozen_offline_inference_not_training():
    config = generation_config()
    assert config["training"] is False
    assert config["do_sample"] is False
    assert config["enable_thinking"] is False
    assert config["max_new_tokens"] == 4096
    assert config["external_api_calls"] == 0
    assert len(config["ids"]) == 6

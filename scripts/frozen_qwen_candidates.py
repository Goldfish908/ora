#!/usr/bin/env python3
"""One-shot offline Qwen initial candidates for the registered frozen milestone."""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ora_agent.dvsa_model import extract_json, solve_model, validate_model
from ora_agent.dvsa_repair import schema_errors, score_solution
from scripts.dvsa_bwor_reference import load_rows
from scripts.dvsa_candidate import PROMPT, render_prompt
from scripts.dvsa_reference_select import select_reference

IDS = ("BWOR-002", "BWOR-003", "BWOR-005", "BWOR-006", "BWOR-010", "BWOR-012")
MODEL_ID = "Qwen/Qwen3.8-27B"
REVISION = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
SNAPSHOT = Path("/dfs/data/hewj13/.cache/huggingface/hub/models--Qwen--Qwen3.8-27B/snapshots") / REVISION
OUT = ROOT / "work/frozen_scoped_milestone_v0.1"


def generation_config() -> dict:
    return {"model_id": MODEL_ID, "revision": REVISION, "seed": 42,
            "do_sample": False, "enable_thinking": False, "max_new_tokens": 4096,
            "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
            "ids": list(IDS), "external_api_calls": 0, "training": False}


def emit_result(record: dict) -> None:
    print(json.dumps({"id": record["problem_id"], "status": record["status"],
                      "business_correct": record["score"]["business_correct"],
                      "latency_s": round(record["wall_s"], 2)}), flush=True)


def generate() -> None:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    config = generation_config()
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    tokenizer = AutoTokenizer.from_pretrained(SNAPSHOT)
    try:
        model = AutoModelForCausalLM.from_pretrained(
            SNAPSHOT, dtype=torch.bfloat16, device_map="balanced",
            attn_implementation="flash_attention_2", offload_buffers=True)
    except Exception:
        model = AutoModelForCausalLM.from_pretrained(
            SNAPSHOT, dtype=torch.bfloat16, device_map="balanced",
            attn_implementation="sdpa", offload_buffers=True)
    model.eval()
    load_seconds = time.monotonic() - started
    answers = {row["id"]: float(row["answer"]) for row in load_rows("frozen")}
    results = []
    with torch.inference_mode():
        for problem_id in IDS:
            target = OUT / problem_id / "initial"
            target.mkdir(parents=True, exist_ok=True)
            result_path = target / "result.json"
            signature = {**config, "problem_id": problem_id}
            if result_path.exists():
                previous = json.loads(result_path.read_text())
                if previous.get("generator") != signature:
                    raise ValueError(f"existing generator result differs: {problem_id}")
                results.append(previous)
                continue
            reference = select_reference("frozen", problem_id)
            schema = json.dumps(reference["model"]["variables"], ensure_ascii=False, indent=2)
            prompt = render_prompt(problem_id, reference["question"], schema)
            (target / "prompt.txt").write_text(prompt)
            inputs = tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}], tokenize=True,
                add_generation_prompt=True, enable_thinking=False,
                return_tensors="pt", return_dict=True).to(model.device)
            torch.manual_seed(42)
            began = time.monotonic()
            output = model.generate(**inputs, max_new_tokens=4096, do_sample=False)
            text = tokenizer.decode(output[0, inputs["input_ids"].shape[1]:],
                                    skip_special_tokens=True)
            latency = time.monotonic() - began
            response = {"content": text,
                        "usage": {"prompt_tokens": int(inputs["input_ids"].numel()),
                                  "completion_tokens": int(output.shape[1] - inputs["input_ids"].shape[1]),
                                  "total_tokens": int(output.shape[1])},
                        "latency_s": latency}
            (target / "response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
            record = {"problem_id": problem_id, "split": "frozen", "generator": signature,
                      "reference_schema_revision": reference["revision"], "llm_calls": 1,
                      "usage": response["usage"], "llm_latency_s": latency,
                      "public_answer_hidden_from_prompt": True}
            candidate = None
            try:
                candidate = extract_json(text)
                if candidate.get("problem_id") != problem_id:
                    raise ValueError("problem_id mismatch")
                validate_model(candidate)
                (target / "candidate.json").write_text(
                    json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")
                errors = schema_errors(candidate, reference["model"]["variables"])
                if errors:
                    record["status"] = "invalid_shared_schema"
                    record["schema_errors"] = errors
                    record["score"] = score_solution(reference, None, answers[problem_id])
                else:
                    solved = solve_model(candidate, time_limit=60.0)
                    record["solve"] = solved
                    if solved["status"] == "optimal":
                        (target / "solution.json").write_text(
                            json.dumps(solved["solution"], ensure_ascii=False, indent=2) + "\n")
                    record["score"] = score_solution(
                        reference, solved.get("solution") if solved["status"] == "optimal" else None,
                        answers[problem_id])
                    record["status"] = "initial_scored" if solved["status"] == "optimal" else "initial_solve_failed"
            except (ValueError, TypeError, AttributeError) as exc:
                record["status"] = "invalid_candidate"
                record["error"] = str(exc)
                record["score"] = score_solution(reference, None, answers[problem_id])
            record["wall_s"] = latency
            result_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
            results.append(record)
            emit_result(record)
    manifest = {"config": config, "model_load_seconds": load_seconds,
                "results": [{"id": row["problem_id"], "status": row["status"],
                             "business_correct": row["score"]["business_correct"],
                             "usage": row["usage"], "llm_latency_s": row["llm_latency_s"]}
                            for row in results],
                "total_input_tokens": sum(row["usage"]["prompt_tokens"] for row in results),
                "total_completion_tokens": sum(row["usage"]["completion_tokens"] for row in results),
                "total_generation_seconds": sum(row["llm_latency_s"] for row in results),
                "initial_business_correct": sum(row["score"]["business_correct"] for row in results)}
    (OUT / "generation_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    generate()

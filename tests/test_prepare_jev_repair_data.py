from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.prepare_jev_repair_data import (  # noqa: E402
    CHOSEN_TARGET,
    DataConflictError,
    DataLeakageError,
    OPTIONS,
    OUTPUT_FIELDS,
    QUESTION,
    REJECTED_TARGET,
    SOURCE_URL,
    TARGET_BASIS,
    generate_dataset,
    prepare_records,
    scenario_bucket,
)

INPUT_HASH = "a" * 64


def make_pair(scenario_id: str, *, mutant: str = "drop_constraint",
              split: str = "train", prompt: str | None = None,
              chosen: str | None = None, rejected: str | None = None,
              source: str = "factory_pass") -> dict:
    return {
        "scenario_id": scenario_id,
        "mutant": mutant,
        "prompt": prompt or (
            f"[SCENARIO]\nScenario ID: {scenario_id}\nTask for {scenario_id}\n"
            f"Problem marker: {hashlib.sha256(scenario_id.encode()).hexdigest()[:12]}"
        ),
        "chosen": chosen or f"# chosen {mutant} {scenario_id}\nprint('ok')",
        "rejected": rejected or f"# rejected {mutant} {scenario_id}\nprint('bad')",
        "source": source,
        "split": split,
    }


def model_text(record: dict) -> str:
    return json.dumps(
        {key: record[key] for key in ("state", "question", "kind", "options")},
        ensure_ascii=False,
    )


class PrepareJevRepairDataTest(unittest.TestCase):
    def test_schema_pair_targets_provenance_and_redaction(self):
        scenario_id = "retail_f1_dev_v0"
        row = make_pair(
            scenario_id,
            split="dev",
            chosen=f"print('{scenario_id}')",
            rejected="print('factory_pass')",
        )
        prepared = prepare_records([row], INPUT_HASH)
        self.assertEqual(len(prepared.records), 2)
        chosen, rejected = prepared.records
        for record, candidate, target in (
            (chosen, row["chosen"], list(CHOSEN_TARGET)),
            (rejected, row["rejected"], list(REJECTED_TARGET)),
        ):
            self.assertEqual(set(record), OUTPUT_FIELDS)
            self.assertEqual(record["group_id"], scenario_id)
            self.assertEqual(record["split"], "test")
            self.assertEqual(record["question"], QUESTION)
            self.assertEqual(record["kind"], "noul")
            self.assertEqual(record["options"], OPTIONS)
            self.assertEqual(record["target"], target)
            self.assertEqual(set(record["state"]), {"prompt", "candidate_code"})
            self.assertNotIn("Scenario ID:", record["state"]["prompt"])
            self.assertNotIn(scenario_id, model_text(record))
            self.assertNotIn(row["source"], model_text(record))
            self.assertNotIn(candidate, record["state"]["candidate_code"])
            metadata = record["metadata"]
            self.assertEqual(metadata["target_basis"], TARGET_BASIS)
            self.assertIs(metadata["historical_development"], True)
            provenance = metadata["provenance"]
            self.assertEqual(provenance["type"], "import")
            self.assertEqual(provenance["input_sha256"], INPUT_HASH)
            self.assertEqual(provenance["source_url"], SOURCE_URL)
            self.assertEqual(provenance["license"], "unspecified")
            self.assertEqual(provenance["original_split"], "dev")
            self.assertTrue(provenance["split_policy"])
            self.assertTrue(provenance["original_id"])
        self.assertNotEqual(chosen["id"], rejected["id"])
        self.assertEqual(
            chosen["metadata"]["provenance"]["original_id"],
            rejected["metadata"]["provenance"]["original_id"],
        )

    def test_scenario_coherent_ood_and_official_style_hash_split(self):
        wrong_constant_scenario = "retail_f1_wrong_constant_v0"
        train_scenario = "retail_f1_jit_logic_v1"
        calibration_scenario = "retail_f2_circular_sub_v3"
        dev_scenario = "retail_f1_dev_v1"
        self.assertEqual(scenario_bucket(train_scenario), 2277)
        self.assertEqual(scenario_bucket(calibration_scenario), 9507)
        rows = [
            make_pair(wrong_constant_scenario, mutant="wrong_constant"),
            make_pair(wrong_constant_scenario, mutant="drop_constraint"),
            make_pair(train_scenario),
            make_pair(calibration_scenario),
            make_pair(dev_scenario, mutant="wrong_constant", split="dev"),
        ]
        prepared = prepare_records(rows, INPUT_HASH)
        split_by_group = {
            record["group_id"]: record["split"] for record in prepared.records
        }
        self.assertEqual(split_by_group[wrong_constant_scenario], "ood")
        self.assertEqual(split_by_group[train_scenario], "train")
        self.assertEqual(split_by_group[calibration_scenario], "calibration")
        self.assertEqual(split_by_group[dev_scenario], "test")
        self.assertEqual(sum(record["split"] == "ood" for record in prepared.records), 4)
        train_mutants = {
            record["metadata"]["provenance"]["original_mutant"]
            for record in prepared.records if record["split"] == "train"
        }
        self.assertNotIn("wrong_constant", train_mutants)

    def test_exact_duplicate_pair_is_removed_and_audited(self):
        row = make_pair("retail_f1_duplicate_v0", split="dev")
        prepared = prepare_records([row, dict(row)], INPUT_HASH)
        self.assertEqual(len(prepared.records), 2)
        duplicates = prepared.report["exact_duplicates"]
        self.assertEqual(duplicates["removed_pairs"], 1)
        self.assertEqual(duplicates["removed_candidate_records"], 2)
        self.assertEqual(duplicates["duplicates"], [{
            "kept_input_line": 1,
            "duplicate_input_line": 2,
            "scenario_id": row["scenario_id"],
            "mutant": row["mutant"],
        }])

    def test_label_conflict_drops_every_implicated_pair(self):
        scenario_id = "retail_f2_conflict_v0"
        rows = [
            make_pair(scenario_id, split="dev", prompt="shared", chosen="A", rejected="B"),
            make_pair(scenario_id, split="dev", prompt="shared", chosen="C", rejected="A"),
            make_pair("retail_f2_unaffected_v0", split="dev", prompt="other", chosen="D", rejected="E"),
        ]
        with self.assertRaises(DataConflictError):
            prepare_records(rows, INPUT_HASH, conflict_policy="error")
        prepared = prepare_records(rows, INPUT_HASH, conflict_policy="drop")
        self.assertEqual(len(prepared.records), 2)
        self.assertEqual(prepared.records[0]["group_id"], "retail_f2_unaffected_v0")
        conflicts = prepared.report["label_conflicts"]
        self.assertEqual(conflicts["conflicting_inputs"], 1)
        self.assertEqual(conflicts["removed_pairs"], 2)
        self.assertEqual(conflicts["removed_candidate_records"], 4)
        self.assertEqual(conflicts["removed_input_lines"], [1, 2])

    def test_same_label_candidate_duplicate_drops_later_whole_pair(self):
        rows = [
            make_pair("retail_f2_duplicate_v0", split="dev", prompt="shared", chosen="A", rejected="B"),
            make_pair("retail_f2_duplicate_v0", split="dev", prompt="shared", chosen="C", rejected="B"),
            make_pair("retail_f2_unaffected_v1", split="dev", prompt="other", chosen="D", rejected="E"),
        ]
        prepared = prepare_records(rows, INPUT_HASH)
        self.assertEqual(len(prepared.records), 4)
        self.assertEqual(prepared.report["label_conflicts"]["removed_pairs"], 0)
        duplicates = prepared.report["candidate_input_duplicates"]
        self.assertEqual(duplicates["duplicate_inputs"], 1)
        self.assertEqual(duplicates["removed_pairs"], 1)
        self.assertEqual(duplicates["removed_candidate_records"], 2)
        self.assertEqual(duplicates["removed_input_lines"], [2])
        self.assertEqual(duplicates["removals"][0]["kept_input_lines"], [1])

    def test_original_group_split_conflict_is_rejected(self):
        scenario_id = "retail_f3_leaky_group_v0"
        rows = [
            make_pair(scenario_id, split="train"),
            make_pair(scenario_id, split="dev"),
        ]
        with self.assertRaises(DataLeakageError):
            prepare_records(rows, INPUT_HASH)

    def test_redacted_prompt_context_leakage_is_rejected(self):
        first = "retail_f3_context_v0"
        second = "retail_f1_jit_logic_v1"
        rows = [
            make_pair(first, split="dev", prompt=f"Scenario ID: {first}\nidentical context", chosen="A", rejected="B"),
            make_pair(second, split="train", prompt=f"Scenario ID: {second}\nidentical context", chosen="C", rejected="D"),
        ]
        with self.assertRaises(DataLeakageError):
            prepare_records(rows, INPUT_HASH)

    def test_generate_dataset_writes_four_splits_and_verifiable_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "dpo.jsonl"
            input_path.write_text(
                json.dumps(make_pair("retail_f4_dev_v0", split="dev")) + "\n",
                encoding="utf-8",
            )
            output = root / "output"
            manifest = generate_dataset(input_path, output)
            self.assertEqual(manifest["summary"]["records"], 2)
            self.assertEqual(manifest["summary"]["pairs"], 1)
            self.assertEqual(manifest["splits"]["test"]["scenarios"], 1)
            for split in ("train", "calibration", "test", "ood"):
                path = output / f"{split}.jsonl"
                self.assertTrue(path.is_file())
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    manifest["files_sha256"][path.name],
                )
            first_hashes = dict(manifest["files_sha256"])
            first_manifest_bytes = (output / "manifest.json").read_bytes()
            second_manifest = generate_dataset(input_path, output)
            self.assertEqual(second_manifest["files_sha256"], first_hashes)
            self.assertEqual((output / "manifest.json").read_bytes(), first_manifest_bytes)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Run the preregistered candidate-blind replay with no model calls."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.bwor_saved_contract_replay import run_cohort

IDS = ("BWOR-013", "BWOR-018", "BWOR-019", "BWOR-021", "BWOR-024", "BWOR-025")


def main() -> None:
    run_cohort(
        ROOT / "work/dvsa/bwor_repair/frozen", IDS,
        ROOT / "work/bwor_candidate_blind_replay_v0.1",
        ROOT / "docs/paper/bwor_candidate_blind_protocol_v0.1.md",
        "bwor.candidate_blind_replay.v0.1",
        "candidate_blind_historical_replay_not_new_generation_or_frozen")


if __name__ == "__main__":
    main()

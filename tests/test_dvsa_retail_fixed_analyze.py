from pathlib import Path

from scripts.dvsa_retail_core import load_assets
from scripts.dvsa_retail_fixed_analyze import deterministic_cells
from scripts.dvsa_retail_llm_judge import eligible_artifacts

ROOT = Path(__file__).resolve().parents[1]


def test_deterministic_retail_fixed_arms_cover_all_reference_qualified_cases():
    artifacts = eligible_artifacts(
        ROOT / "work/mem_evo/replay_gen1/m1_pilot_schema_sol_gen1.jsonl",
        ROOT / "work/mem_evo/replay_gen1/sandbox")
    assets, _ = load_assets()
    cells = deterministic_cells(artifacts, assets)
    for arm in ("dvsa", "direct_legacy_witness"):
        assert sum(row["detected"] for row in cells[arm] if row["wrong"]) == 10
        assert sum(row["false_positive"] for row in cells[arm]) == 0
        assert sum(row["unknown"] for row in cells[arm]) == 0

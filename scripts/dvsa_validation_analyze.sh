#!/bin/bash
set -euo pipefail
cd /home/hewj13/wm/ora
PY=/home/hewj13/planbb/miniforge3/envs/rl/bin/python3.9
IDS=$($PY - <<'PY'
import json
r=json.load(open('work/dvsa/bwor_reference/validation/summary.json'))
print(' '.join(r['summary']['eligible_ids']))
PY
)
$PY scripts/dvsa_fixed_arm_analyze.py --split validation --ids $IDS \
  --judge-root work/dvsa/bwor_llm_judge/validation \
  --dedup-root work/dvsa/bwor_llm_judge/validation \
  --out work/dvsa/bwor_fixed_arms_validation \
  --figure /home/hewj13/paper_icml2027/figures/dvsa_bwor_validation_fixed_arms.png
$PY scripts/dvsa_repair_analyze.py --split validation --ids $IDS \
  --run-dir work/dvsa/bwor_repair/validation \
  --out work/dvsa/bwor_repair_validation_analysis \
  --label 'validation frozen registry_v0.6' \
  --figure /home/hewj13/paper_icml2027/figures/dvsa_bwor_validation_repair.png
$PY scripts/dvsa_coverage_report.py --split validation \
  --fixed work/dvsa/bwor_fixed_arms_validation/analysis.json \
  --repair work/dvsa/bwor_repair_validation_analysis/analysis.json \
  --out work/dvsa/bwor_validation_coverage \
  --figure /home/hewj13/paper_icml2027/figures/dvsa_bwor_validation_coverage.png

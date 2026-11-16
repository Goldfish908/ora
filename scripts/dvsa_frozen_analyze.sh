#!/bin/bash
set -euo pipefail
cd /home/hewj13/wm/ora
PY=/home/hewj13/planbb/miniforge3/envs/rl/bin/python3.9
IDS=$($PY - <<'PY'
import json
r=json.load(open('work/dvsa/bwor_reference/frozen/summary.json'))
print(' '.join(r['summary']['eligible_ids']))
PY
)
$PY scripts/dvsa_fixed_arm_analyze.py --split frozen --ids $IDS \
  --judge-root work/dvsa/bwor_llm_judge/frozen \
  --dedup-root work/dvsa/bwor_llm_judge/frozen \
  --out work/dvsa/bwor_fixed_arms_frozen \
  --figure /home/hewj13/paper_icml2027/figures/dvsa_bwor_frozen_fixed_arms.png
$PY scripts/dvsa_repair_analyze.py --split frozen --ids $IDS \
  --run-dir work/dvsa/bwor_repair/frozen \
  --out work/dvsa/bwor_repair_frozen_analysis \
  --label 'frozen final registry_v0.7' \
  --figure /home/hewj13/paper_icml2027/figures/dvsa_bwor_frozen_repair.png
$PY scripts/dvsa_coverage_report.py --split frozen \
  --fixed work/dvsa/bwor_fixed_arms_frozen/analysis.json \
  --repair work/dvsa/bwor_repair_frozen_analysis/analysis.json \
  --out work/dvsa/bwor_frozen_coverage \
  --figure /home/hewj13/paper_icml2027/figures/dvsa_bwor_frozen_coverage.png

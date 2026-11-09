#!/bin/bash
set -u
cd /home/hewj13/wm/ora
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
python3 scripts/sac_opt.py --scenarios-file data/m1_retailopt/dev40_f1f4.jsonl \
  --out-dir runs/sac_opt --out-tag _dev40 > runs/sac_opt/dev40.log 2>&1
echo "sacopt dev40 done rc=$?"

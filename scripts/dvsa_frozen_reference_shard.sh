#!/bin/bash
set -euo pipefail
cd /home/hewj13/wm/ora
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
if [ "$#" -ne 2 ]; then
  echo "usage: $0 INDEX COUNT" >&2
  exit 2
fi
INDEX="$1"
COUNT="$2"
PY=/home/hewj13/planbb/miniforge3/envs/rl/bin/python3.9
IDS=$($PY - "$INDEX" "$COUNT" <<'PY'
import sys
index,count=map(int,sys.argv[1:])
ids=open('data/dvsa/bwor/frozen.txt').read().splitlines()
if not 0 <= index < count:
    raise SystemExit('shard requires 0 <= index < count')
print(' '.join(ids[index::count]))
PY
)
echo "frozen reference shard $INDEX/$COUNT: $IDS"
$PY scripts/dvsa_bwor_reference.py --split frozen --ids $IDS --solve --resume
$PY scripts/dvsa_bwor_reference_repair.py --split frozen --ids $IDS

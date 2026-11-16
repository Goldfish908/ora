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
import json,sys
index,count=map(int,sys.argv[1:])
r=json.load(open('work/dvsa/bwor_reference/validation/summary.json'))
ids=r['summary']['eligible_ids']
if not 0 <= index < count:
    raise SystemExit('shard requires 0 <= index < count')
print(' '.join(ids[index::count]))
PY
)
if [ -z "$IDS" ]; then
  echo "no eligible IDs in shard $INDEX/$COUNT" >&2
  exit 2
fi
echo "validation shard $INDEX/$COUNT: $IDS"
$PY scripts/dvsa_binding_author.py --split validation --ids $IDS --resume
$PY scripts/dvsa_binding_eval.py --split validation --ids $IDS
$PY scripts/dvsa_candidate.py --split validation --ids $IDS --resume
$PY scripts/dvsa_repair.py --split validation --ids $IDS --resume
$PY scripts/dvsa_llm_judge.py --split validation --ids $IDS --resume

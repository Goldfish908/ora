#!/bin/bash
# Launch the 5-shard online arm-B experiment (pre-solve gated loop, on-mode).
# Arm A = existing F12 runs (runs/m1_feedback/m1_feedback_v*.jsonl).
# Usage: bash scripts/run_presolve_shards.sh
set -u
cd "$(dirname "$0")/.."
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
for v in v0 v1 v2 v3 v4; do
  python3 scripts/m1_presolve_loop.py --variant "$v" --modes on --out-tag "_$v" \
    > "runs/m1_presolve/shard_$v.log" 2>&1 &
  echo "launched $v pid=$!"
done
wait
echo "all shards done"

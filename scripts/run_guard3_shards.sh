#!/bin/bash
# Arm B'': crash guard v0.3 + pre-solve gate, 5 shards, on-mode, max 3 rounds.
# Same budget as B' (--guard-turns 1); only the guard rule set differs
# (v0.1 -> v0.3: G2 dataflow, G6, G7, G8, narrowed G4/G6 ternary).
# Output: runs/m1_presolve/m1_presolve_guard3_v{0..4}.jsonl
# Usage: bash scripts/run_guard3_shards.sh
set -u
cd "$(dirname "$0")/.."
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
for v in v0 v1 v2 v3 v4; do
  python3 scripts/m1_presolve_loop.py --variant "$v" --modes on \
    --out-tag "_guard3_$v" \
    > "runs/m1_presolve/shard_guard3_$v.log" 2>&1 &
  echo "launched guard3 $v pid=$!"
done
wait
echo "all guard3 shards done"

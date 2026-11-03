#!/bin/bash
# Arm P3: generation-side gen-2 semantic memory — v0.3 conventions
# (v0.2 tool knowledge + scaffold + semantic_priors_v0.1 demand/substitution
# conventions). Zero-shot schema_sol pilot rerun.
# Output: runs/m1_pilot_priors3/m1_pilot_schema_sol_p3_v{0..4}.jsonl
set -u
cd "$(dirname "$0")/.."
mkdir -p runs/m1_pilot_priors3
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
OUT=/home/hewj13/wm/ora/runs/m1_pilot_priors3
for v in v0 v1 v2 v3 v4; do
  python3 scripts/m1_pilot.py --variant "$v" --modes on \
    --prompt-mode schema_sol \
    --conventions-file configs/conventions_priors_v0.3.txt \
    --out-dir "$OUT" --out-tag "_p3_$v" \
    > "$OUT/shard_p3_$v.log" 2>&1 &
  echo "launched p3 $v pid=$!"
done
wait
echo "all p3 pilot shards done"

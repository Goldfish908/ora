#!/bin/bash
# Arm P2: generation-side upgrade — v0.2 priors (G1-G10 tool knowledge)
# + generic modeling procedure scaffold. Zero-shot schema_sol pilot rerun.
# Output: runs/m1_pilot_priors2/m1_pilot_schema_sol_p2_v{0..4}.jsonl
set -u
cd "$(dirname "$0")/.."
mkdir -p runs/m1_pilot_priors2
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
OUT=/home/hewj13/wm/ora/runs/m1_pilot_priors2
for v in v0 v1 v2 v3 v4; do
  python3 scripts/m1_pilot.py --variant "$v" --modes on \
    --prompt-mode schema_sol \
    --conventions-file configs/conventions_priors_v0.2.txt \
    --out-dir "$OUT" --out-tag "_p2_$v" \
    > "$OUT/shard_p2_$v.log" 2>&1 &
  echo "launched p2 $v pid=$!"
done
wait
echo "all p2 pilot shards done"

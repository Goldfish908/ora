#!/bin/bash
# Combo arm: P2 generation (v0.2 priors + scaffold) round-1 + guard v0.4
# + pre-solve gate + witness feedback loop, max 3 rounds, on-mode.
# Round-1 records/sandboxes come from runs/m1_pilot_priors2 (P2 pilot).
# Output: runs/m1_presolve/m1_presolve_combo_v{0..4}.jsonl
set -u
cd "$(dirname "$0")/.."
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
for v in v0 v1 v2 v3 v4; do
  python3 scripts/m1_presolve_loop.py --variant "$v" --modes on \
    --out-tag "_combo_$v" \
    --conventions-file configs/conventions_priors_v0.2.txt \
    --pilot-dir runs/m1_pilot_priors2 \
    --pilot-glob "m1_pilot_schema_sol_p2_$v.jsonl" \
    > "runs/m1_presolve/shard_combo_$v.log" 2>&1 &
  echo "launched combo $v pid=$!"
done
wait
echo "all combo shards done"

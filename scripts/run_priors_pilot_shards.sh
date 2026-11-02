#!/bin/bash
# Arm P: prior-injection pilot — memory-level self-evolution, generation 1.
# Reruns zero-shot schema_sol pilot with distilled conventions
# (configs/conventions_priors_v0.1.txt) prepended to the prompt.
# Isolated out dir keeps runs/m1_pilot globs and sandboxes untouched.
# Output: runs/m1_pilot_priors/m1_pilot_schema_sol_priors_v{0..4}.jsonl
# Usage: bash scripts/run_priors_pilot_shards.sh
set -u
cd "$(dirname "$0")/.."
mkdir -p runs/m1_pilot_priors
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
for v in v0 v1 v2 v3 v4; do
  python3 scripts/m1_pilot.py --variant "$v" --modes on \
    --prompt-mode schema_sol \
    --conventions-file configs/conventions_priors_v0.1.txt \
    --out-dir runs/m1_pilot_priors --out-tag "_priors_$v" \
    > "runs/m1_pilot_priors/shard_priors_$v.log" 2>&1 &
  echo "launched priors $v pid=$!"
done
wait
echo "all priors pilot shards done"

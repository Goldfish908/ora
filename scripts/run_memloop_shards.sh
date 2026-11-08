#!/bin/bash
# Arm C: B'' full loop (pre-solve gate + crash guard v0.3 whitelist) with the
# round-1 pilot REPLACED by the P3 semantic-memory pilot (generation-side
# memory injected). Tests whether memory and the loop are complementary.
# Comparability measures vs B'':
#   - --guard-rules G0..G8  (B'' ran guard v0.3; repo guard_check.py is v0.4)
#   - --r1-checks code_checks_p3.jsonl (offline gate verdicts over P3 round-1
#     code, so round-2 feedback policy matches B'' for round-1 BLOCK cells)
# Round-1 records/sandboxes come from runs/m1_pilot_priors3 (zero LLM cost).
# Output: runs/m1_presolve/m1_presolve_memloop_v{0..4}.jsonl
# Usage: bash scripts/run_memloop_shards.sh
set -u
cd "$(dirname "$0")/.."
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
for v in v0 v1 v2 v3 v4; do
  python3 scripts/m1_presolve_loop.py --variant "$v" --modes on \
    --conventions-file configs/conventions_priors_v0.3.txt \
    --pilot-dir runs/m1_pilot_priors3 \
    --pilot-glob "m1_pilot_schema_sol_p3_v*.jsonl" \
    --guard-rules G0,G1,G2,G3,G4,G5,G6,G7,G8 \
    --r1-checks runs/presolve/code_checks_p3.jsonl \
    --out-tag "_memloop_$v" \
    > "runs/m1_presolve/shard_memloop_$v.log" 2>&1 &
  echo "launched memloop $v pid=$!"
done
wait
echo "all memloop shards done"

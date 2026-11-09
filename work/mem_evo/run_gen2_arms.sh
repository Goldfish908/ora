#!/bin/bash
set -u
cd /home/hewj13/wm/ora
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
BASE=/home/hewj13/wm/ora/work/mem_evo
for uid in memory_clause-002 memory_clause-003 memory_clause-004; do
  for rep in 1 2 3; do
    OUT=$BASE/replay_gen2_${uid}_${rep}
    mkdir -p "$OUT"
    /home/hewj13/planbb/miniforge3/envs/rl/bin/python scripts/m1_pilot.py --modes on --prompt-mode schema_sol \
      --conventions-file "$BASE/conv_${uid}.txt" \
      --scenarios-file work/mem_evo/replay_gen1.jsonl \
      --out-dir "$OUT" --out-tag "_g2${uid}r${rep}" > "$OUT/run.log" 2>&1 &
  done
done
wait
echo "gen2 three-arm replays done"

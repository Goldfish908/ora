#!/bin/bash
set -u
cd /home/hewj13/wm/ora
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
BASE=/home/hewj13/wm/ora/work/mem_evo
for mode in full trigger embed; do
  for rep in 1 2 3; do
    OUT=$BASE/replay_memmode_${mode}_${rep}
    mkdir -p "$OUT"
    /home/hewj13/planbb/miniforge3/envs/rl/bin/python scripts/m1_pilot.py --modes on --prompt-mode schema_sol \
      --conventions-file configs/conventions_priors_v0.3.txt --memory-mode $mode \
      --scenarios-file work/mem_evo/replay_gen1.jsonl \
      --out-dir "$OUT" --out-tag "_mm${mode}r${rep}" > "$OUT/run.log" 2>&1 &
  done
done
wait
echo "memory-mode three-arm replays done"

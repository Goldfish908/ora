#!/bin/bash
set -u
cd /home/hewj13/wm/ora
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
OUT=/home/hewj13/wm/ora/work/mem_evo/replay_gen1_ctrl
python3 scripts/m1_pilot.py --modes on --prompt-mode schema_sol \
  --conventions-file configs/conventions_priors_v0.3.txt \
  --scenarios-file work/mem_evo/replay_gen1.jsonl \
  --out-dir "$OUT" --out-tag "_gen1ctrl" > "$OUT/run.log" 2>&1
echo "replay gen1 ctrl done rc=$?"

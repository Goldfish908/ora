#!/bin/bash
# Evolution generations 1..3 orchestrator: for each gen N run
#   eval (dev40 fitness) -> champion (gapcheck60 overfit gate) -> next (mutate)
# Champion of gen 3 additionally runs the full-190 eval separately (B8).
set -u
cd "$(dirname "$0")/.."
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
PY=/home/hewj13/planbb/miniforge3/envs/rl/bin/python
for g in 1 2 3; do
  echo "=== gen $g eval ==="
  $PY scripts/evo_driver.py eval --gen "$g" || exit 1
  echo "=== gen $g champion ==="
  $PY scripts/evo_driver.py champion --gen "$g" || exit 1
  if [ "$g" -lt 3 ]; then
    echo "=== gen $g -> spawn $((g+1)) ==="
    $PY scripts/evo_driver.py next --gen "$g" || exit 1
  fi
done
echo "all generations done"
$PY scripts/evo_driver.py status

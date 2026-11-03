#!/bin/bash
# Resume evolution after LLM-gateway outage: wait for endpoint health
# (smoke call, retry up to 8h), then run next --gen 1 and generations 2-3.
# gen1 eval+champion are already scored in the ledger; do NOT rerun them
# (champion would double-append a gapcheck60 row).
set -u
cd "$(dirname "$0")/.."
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1
PY=/home/hewj13/planbb/miniforge3/envs/rl/bin/python

smoke() {
  $PY - <<'EOF'
import sys
from ora_agent import llm
try:
    r = llm.chat([{"role": "user", "content": "ping, reply with one word"}],
                 max_tokens=16, temperature=0.0,
                 extra={"chat_template_kwargs": {"enable_thinking": False}})
    sys.exit(0 if (r.get("content") or "").strip() else 1)
except Exception:
    sys.exit(1)
EOF
}

for i in $(seq 1 96); do
  if smoke; then echo "endpoint healthy (try $i)"; break; fi
  echo "$(date +%H:%M) try $i: endpoint down, sleep 300s"
  sleep 300
done
smoke || { echo "endpoint still down after 8h, giving up"; exit 1; }

echo "=== resume: next --gen 1 (spawn gen2) ==="
$PY scripts/evo_driver.py next --gen 1 || exit 1
for g in 2 3; do
  echo "=== gen $g eval ==="
  $PY scripts/evo_driver.py eval --gen "$g" || exit 1
  echo "=== gen $g champion ==="
  $PY scripts/evo_driver.py champion --gen "$g" || exit 1
  if [ "$g" -lt 3 ]; then
    echo "=== gen $g -> spawn $((g+1)) ==="
    $PY scripts/evo_driver.py next --gen "$g" || exit 1
  fi
done
echo "resume run done"
$PY scripts/evo_driver.py status

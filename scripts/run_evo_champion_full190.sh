#!/bin/bash
# B8: run an evolution champion genome on the full RetailOpt-190 (5 variant
# shards in parallel), then score into the evo ledger as kind "full190".
# Usage: bash scripts/run_evo_champion_full190.sh <gid> <gen>
# Env:   sources ~/.leagent_env; exports ORA_LLM_* for the intranet Qwen.
set -u
GID="${1:?usage: run_evo_champion_full190.sh <gid> <gen>}"
GEN="${2:?usage: run_evo_champion_full190.sh <gid> <gen>}"
cd "$(dirname "$0")/.."
PY=/home/hewj13/planbb/miniforge3/envs/rl/bin/python
source ~/.leagent_env
export ORA_LLM_BASE_URL="$QWEN27B_BASE_URL" ORA_LLM_API_KEY="$QWEN27B_API_KEY" \
       ORA_LLM_MODEL="Qwen3_8-27B" ORA_LLM_INSECURE=1

# materialize combined conventions (code + semantic) for this genome
$PY - "$GID" <<'EOF'
import sys
sys.path.insert(0, "scripts")
from evo_driver import combined_file
print("combined:", combined_file(sys.argv[1]))
EOF

OUT=/home/hewj13/wm/ora/runs/evo/gen${GEN}_full190
mkdir -p "$OUT"
for v in v0 v1 v2 v3 v4; do
  $PY scripts/m1_pilot.py --variant "$v" --modes on \
    --prompt-mode schema_sol \
    --conventions-file "evo/genomes/${GID}/combined.txt" \
    --out-dir "$OUT" --out-tag "_full190_${GID}_${v}" \
    > "$OUT/shard_${GID}_${v}.log" 2>&1 &
  echo "launched $GID $v pid=$!"
done
wait
echo "all full190 shards done for $GID"

$PY - "$GID" "$GEN" <<'EOF'
import sys
sys.path.insert(0, "scripts")
from pathlib import Path
from evo_driver import ROOT, score_files, ledger_add
gid, gen = sys.argv[1], int(sys.argv[2])
fps = sorted((ROOT / f"runs/evo/gen{gen}_full190").glob(
    f"m1_pilot_schema_sol_full190_{gid}_v*.jsonl"))
assert len(fps) == 5, f"expected 5 shard files, got {len(fps)}"
s = score_files(fps)
ledger_add({"kind": "full190", "gen": gen, "gid": gid, **s})
print(f"full190 {gid}: {s['success']}/{s['n']} "
      f"({s['success']/s['n']:.1%}) ph={s['phantom']}")
EOF

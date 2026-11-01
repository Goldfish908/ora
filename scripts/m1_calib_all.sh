#!/bin/bash
# Calibrate generalized reference solver against reference_objective for
# one instance (v0) of each of the 38 archetypes. Parallel with xargs.
cd /home/hewj13/wm/ora
OUT=runs/m1_witness_ref_all
mkdir -p "$OUT"
python3 - <<'EOF' > /tmp/arch_list.txt
import json
rows=[json.loads(l) for l in open("data/m1_retailopt/retailopt_190.jsonl") if l.strip()]
seen=set()
for r in rows:
    fam=r["scenario_id"].rsplit("_v",1)[0]
    if fam not in seen:
        seen.add(fam); print(r["scenario_id"])
EOF
export OUT
cat /tmp/arch_list.txt | xargs -P 4 -I{} sh -c \
  '/home/hewj13/planbb/miniforge3/envs/rl/bin/python scripts/m1_reference.py {} --tl 120 --out "$OUT" > "$OUT/{}.log" 2>&1; echo "{} done rc=$?"'
echo "=== SUMMARY ==="
grep -H -E "rel_gap|status:" "$OUT"/*.log | sed "s|$OUT/||" | sort

#!/bin/bash
# J1.1 auto-eval: wait for train_v2 done, pick best adapter by epoch_auc,
# run test (gen) + train sanity (no-gen) evals, write status file.
# Self-completing on remote; safe to re-run (idempotent-ish: overwrites its own outputs).
cd /dfs/data/hewj13/j1_judge
STATUS=logs/v2_pipeline_status.txt
echo "$(date '+%F %T') auto_eval_v2 started" >> $STATUS

LOGF=logs/train_v2_metrics.jsonl
# --- wait for training done (poll 60s, stall detect 25min, cap 13h) ---
last_size=0; last_change=$(date +%s); start=$(date +%s)
while true; do
  if grep -q '"event": "done"' $LOGF 2>/dev/null; then echo "$(date '+%F %T') train done detected" >> $STATUS; break; fi
  sz=$(stat -c %s $LOGF 2>/dev/null || echo 0)
  now=$(date +%s)
  if [ "$size" != "$last_size" ] 2>/dev/null; then :; fi
  if [ "$sz" != "$last_size" ]; then last_size=$sz; last_change=$now; fi
  if [ $((now - last_change)) -gt 1500 ]; then echo "$(date '+%F %T') TRAIN_STALLED size=$sz" >> $STATUS; exit 1; fi
  if [ $((now - start)) -gt 46800 ]; then echo "$(date '+%F %T') TIMEOUT waiting train" >> $STATUS; exit 1; fi
  sleep 60
done

# --- pick adapter: earliest epoch with auc>=0.985, else max auc ---
ADAPTER=$(python3 - <<'EOF'
import json
evs = [json.loads(l) for l in open('logs/train_v2_metrics.jsonl')]
aucs = [(e['epoch'], e['auc']) for e in evs if e.get('event') == 'epoch_auc' and e.get('auc') is not None]
pick = None
for ep, a in aucs:
    if a >= 0.985:
        pick = ep
        break
if pick is None and aucs:
    pick = max(aucs, key=lambda x: (x[1], x[0]))[0]
print(f"adapter_v2_ep{pick}" if pick else "")
EOF
)
if [ -z "$ADAPTER" ]; then echo "$(date '+%F %T') NO_ADAPTER_PICKED" >> $STATUS; exit 1; fi
echo "$(date '+%F %T') picked $ADAPTER" >> $STATUS
echo "$ADAPTER" > logs/v2_picked_adapter.txt

# --- evals ---
python3 eval_j1.py --adapter $ADAPTER --data test.jsonl --out logs/eval_v2_test >> logs/eval_v2_run.out 2>&1
echo "$(date '+%F %T') test eval rc=$?" >> $STATUS
python3 eval_j1.py --adapter $ADAPTER --data train_eval_v2.jsonl --out logs/eval_v2_train --no-gen >> logs/eval_v2_run.out 2>&1
echo "$(date '+%F %T') train eval rc=$?" >> $STATUS
echo "$(date '+%F %T') ALL_DONE adapter=$ADAPTER" >> $STATUS

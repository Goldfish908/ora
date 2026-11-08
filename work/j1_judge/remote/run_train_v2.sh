#!/bin/bash
cd /dfs/data/hewj13/j1_judge
mv logs/train_v2_metrics.jsonl logs/train_v2_smoke_metrics.jsonl 2>/dev/null
EPOCHS=3 MIN_EPOCHS=2 AUC_STOP=0.985 VTOK_W=40 SELFEVAL_N=128 nohup python3 train_j1_v2.py > logs/train_v2_full.out 2>&1 &
echo LAUNCHED

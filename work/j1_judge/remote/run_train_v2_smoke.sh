#!/bin/bash
cd /dfs/data/hewj13/j1_judge
LIMIT=8 SMOKE_EVAL=8 EPOCHS=1 nohup python3 train_j1_v2.py > logs/train_v2_smoke.out 2>&1 &
echo LAUNCHED

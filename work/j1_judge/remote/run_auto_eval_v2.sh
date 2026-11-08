#!/bin/bash
cd /dfs/data/hewj13/j1_judge
nohup bash auto_eval_v2.sh > logs/auto_eval_v2.out 2>&1 &
echo LAUNCHED_AUTO_EVAL

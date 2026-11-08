#!/bin/bash
cd /dfs/data/hewj13/j1_judge
nohup bash -c 'python3 eval_j1.py --adapter adapter_ep1 --data test.jsonl --out logs/eval_test_ep1 && python3 eval_j1.py --adapter adapter_ep1 --data train_eval.jsonl --out logs/eval_train_ep1 --no-gen' > logs/eval_run.out 2>&1 &
echo LAUNCHED

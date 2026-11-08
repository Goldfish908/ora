#!/bin/bash
{
  echo "pgrep eval_j1: $(pgrep -fc eval_j1.py || true)"
  echo "pgrep train_j1: $(pgrep -fc train_j1.py || true)"
  nvidia-smi --query-gpu=index,memory.used --format=csv,noheader
  ls -la /dfs/data/hewj13/j1_judge/ /dfs/data/hewj13/j1_judge/logs/ /dfs/data/hewj13/j1_judge/adapter_ep1/
} > /dfs/data/hewj13/j1_judge/logs/final_check.txt 2>&1
echo DONE

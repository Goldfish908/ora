#!/bin/bash
# v4 训练 + eval_chain 监视器（修复版）
# 判定全部基于 marker 分节提取,绝不对全输出做裸 grep
PY=/home/hewj13/planbb/miniforge3/envs/rl/bin/python
FAILS=0
while true; do
  sleep 900
  OUT=$(cd /home/hewj13/mf_tools && MF_TERM=3 $PY mf_exec.py "echo M_S; pgrep -c -f train_j1_v4.py; echo M_STEP; tail -1 /dfs/data/hewj13/j4_judge/logs/train_v4.out | cut -c1-220; echo M_EC; pgrep -c -f VLLM::EngineCore; echo M_OOM; grep -c oom_skip /dfs/data/hewj13/j4_judge/logs/train_v4.out; echo M_CHAIN; tail -2 /dfs/data/hewj13/j4_judge/logs/eval_chain.log 2>/dev/null | cut -c1-200; echo M_IORF; ls /dfs/data/hewj13/j4_judge/logs/v4_eval_ior.jsonl 2>/dev/null || echo NO_IOR_FILE; echo M_E" 90 2>/dev/null)
  if [ -z "$OUT" ]; then FAILS=$((FAILS+1)); echo "[$(date '+%m-%d %H:%M')] mf_exec empty (fails=$FAILS)"; [ $FAILS -ge 6 ] && { echo "MONITOR_ALERT: mf_exec 连续失败 6 次"; break; }; continue; fi
  TRAIN_N=$(printf '%s\n' "$OUT" | sed -n '/^M_S$/,/^M_STEP$/p' | grep -xE '[0-9]+' | head -1)
  STEP_L=$(printf '%s\n' "$OUT" | sed -n '/^M_STEP$/,/^M_EC$/p' | grep '"event"' | tail -1)
  EC_N=$(printf '%s\n' "$OUT" | sed -n '/^M_EC$/,/^M_OOM$/p' | grep -xE '[0-9]+' | head -1)
  OOM_N=$(printf '%s\n' "$OUT" | sed -n '/^M_OOM$/,/^M_CHAIN$/p' | grep -xE '[0-9]+' | head -1)
  CHAIN=$(printf '%s\n' "$OUT" | sed -n '/^M_CHAIN$/,/^M_IORF$/p' | grep -v '^M_' | tail -1)
  IORF=$(printf '%s\n' "$OUT" | sed -n '/^M_IORF$/,/^M_E$/p' | grep -v '^M_' | tail -1)
  echo "[$(date '+%m-%d %H:%M')] train_procs=${TRAIN_N:-?} ec=${EC_N:-?} oom_skip=${OOM_N:-?} | ${STEP_L:0:150}"
  # 完成:IndustryOR 终验文件出现
  if printf '%s' "$IORF" | grep -q 'v4_eval_ior.jsonl'; then echo "V4_IOR_DONE: $IORF"; break; fi
  if printf '%s' "$CHAIN" | grep -q 'ior eval.*exit=0'; then echo "V4_IOR_DONE(chain): $CHAIN"; break; fi
  # 训练进程消失且没有终验文件 = 真异常
  if [ "$TRAIN_N" = "0" ]; then
    echo "TRAIN_PROC_GONE 确认(进程数=0 且无 ior 终验文件)。最近日志: ${STEP_L:0:200}"
    break
  fi
  # EngineCore 重复世代告警(>2)
  if [ -n "$EC_N" ] && [ "$EC_N" -gt 2 ] 2>/dev/null; then echo "WARN: EngineCore=$EC_N (>2, 疑似协作方栈重建)"; fi
  # oom_skip 风暴
  if [ -n "$OOM_N" ] && [ "$OOM_N" -gt 60 ] 2>/dev/null; then echo "WARN: oom_skip=$OOM_N (>60)"; fi
  FAILS=0
done
echo "MONITOR_EXIT $(date '+%m-%d %H:%M')"

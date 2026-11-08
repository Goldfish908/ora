#!/usr/bin/env bash
# P20: one-shot finalizer for the v4 judge chain.
# Runs after remote chain completes (or partially, for the v3 milestone):
#   1. fetch remote artifacts (p18)
#   2. five-arm IndustryOR comparison + F5-F8 epoch recap (p12)
#   3. rebuild comparison figure with all arms (p19)
#   4. print the pre-registered verdict inputs (report §14)
set -u
cd "$(dirname "$0")/.."
PY=/home/hewj13/planbb/miniforge3/envs/rl/bin/python

echo "=== [1/3] fetch remote artifacts (p18) ==="
$PY scripts/p18_fetch_remote_results.py

echo "=== [2/3] comparison table (p12) ==="
$PY scripts/p12_compare_judges_ior.py

echo "=== [3/3] rebuild figure (p19) ==="
$PY scripts/p19_make_active_judge_fig.py

cat << 'EOF'

=== pre-registered verdict rule (report §14) ===
IndustryOR (v4 arm, n=237):
  PASS     : detection >= 31.1% (zero-shot direct) AND FP <= 10%
  PARTIAL  : 19.7% < detection < 31.1%
  FAIL     : detection <= 19.7% OR FP > 10%
F5-F8 (reference only): detection should not regress much below 44.1%, FP <= 10%.
EOF

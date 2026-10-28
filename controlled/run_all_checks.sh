#!/usr/bin/env bash
# Runs every reference solver, artifact and witness under controlled/ and
# prints a PASS/FAIL summary table against the expectations in labels.json.
# Usage: bash run_all_checks.sh
set -u
cd "$(dirname "$0")"

PY=/home/hewj13/planbb/miniforge3/envs/rl/bin/python

overall=0
printf '%-16s %-8s %-10s %-14s %-14s %-8s %s\n' PROBLEM ARTIFACT KIND EXPECTED ACTUAL OBJECTIVE CHECK
for prob in tiny_assign tiny_transport tiny_sched; do
    ref_out=$($PY "$prob/reference.py" 2>&1)
    ref_val=$(echo "$ref_out" | grep -oP 'REFERENCE\s+\K[0-9.eE+-]+')
    corr_obj=$(cd "$prob/correct" && $PY solve.py 2>/dev/null | grep -oP 'OBJECTIVE\s+\K[0-9.eE+-]+')
    match=$($PY - "$ref_val" "$corr_obj" <<'EOF'
import sys
print("OK" if abs(float(sys.argv[1]) - float(sys.argv[2])) <= 1e-6 else "MISMATCH")
EOF
)
    printf '%-16s %-8s %-10s %-14s %-14s %-8s %s\n' "$prob" "-" "reference" "ref==correct" "$match" "$ref_val" "reference=$ref_val correct=$corr_obj"
    [ "$match" = "OK" ] || overall=1

    aids=$($PY - "$prob/labels.json" <<'EOF'
import json, sys
labels = json.load(open(sys.argv[1]))
for aid, meta in labels["artifacts"].items():
    print(aid, meta["kind"], meta["expected_witness"])
EOF
)
    while read -r aid kind expected; do
        out=$($PY "$prob/witness/$aid.py" 2>&1)
        code=$?
        obj=$(echo "$out" | grep -oP 'OBJECTIVE\s+\K[0-9.eE+-]+' | tail -1)
        if [ $code -eq 0 ]; then actual=PASS; else actual=FAIL; fi
        if [ "$actual" = "$expected" ]; then check=OK; else check=UNEXPECTED; overall=1; fi
        reason=$(echo "$out" | grep -oP 'WITNESS FAIL: \K.*' | head -c 60)
        printf '%-16s %-8s %-10s %-14s %-14s %-8s %s\n' "$prob" "$aid" "$kind" "$expected" "$actual" "${obj:--}" "$check $reason"
    done <<< "$aids"
done

echo
if [ $overall -eq 0 ]; then
    echo "ALL CHECKS OK"
else
    echo "SOME CHECKS FAILED"
fi
exit $overall

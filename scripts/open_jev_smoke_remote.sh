#!/bin/bash
set -euo pipefail

OPEN_JEV_ROOT=${OPEN_JEV_ROOT:-/dfs/data/hewj13/Open-Jev}
DATA_DIR=${DATA_DIR:-/dfs/data/hewj13/ora_small_jev/data/jev_repair_v0.1}
WORK_DIR=${WORK_DIR:-/dfs/data/hewj13/ora_small_jev}
BASE_DIR=${BASE_DIR:-/dfs/data/hewj13/models/Qwen3.5-2B}
CHECKPOINT_DIR=${CHECKPOINT_DIR:-/dfs/data/hewj13/models/Open-Jev-2B/package/checkpoint}
HF_HOME=${HF_HOME:-/dfs/data/hewj13/.cache/huggingface}
REVISION=15852e8c16360a2fea060d615a32b45270f8a8fc
MAX_LENGTH=16384
export HF_HOME HF_HUB_OFFLINE=1

if [[ -n "${WAIT_PID:-}" ]]; then
  while kill -0 "$WAIT_PID" 2>/dev/null; do sleep 30; done
fi

python3 - <<'PY'
import json
from pathlib import Path
from safetensors import safe_open
base = Path('/dfs/data/hewj13/models/Qwen3.5-2B')
checkpoint = Path('/dfs/data/hewj13/models/Open-Jev-2B/package/checkpoint')
index = json.loads((base / 'model.safetensors.index.json').read_text())
files = sorted(set(index['weight_map'].values()))
assert all((base / name).is_file() for name in files), 'missing base weight shard'
actual = sum((base / name).stat().st_size for name in files)
expected = index['metadata']['total_size']
assert actual >= expected, (actual, expected)
for name in files:
    with safe_open(base / name, framework='pt') as handle:
        expected_keys = {key for key, shard in index['weight_map'].items() if shard == name}
        assert set(handle.keys()) == expected_keys, f'safetensors key mismatch: {name}'
for name in ('adapter/adapter_model.safetensors', 'adapter/adapter_config.json', 'head.pt', 'model.json'):
    assert (checkpoint / name).is_file(), f'missing checkpoint file: {name}'
print('WEIGHTS_COMPLETE', actual, 'tensor_bytes', expected, 'checkpoint_files_ok')
PY

if [[ -e "$WORK_DIR/runs/smoke_v0.1" ]]; then
  echo "output already exists: $WORK_DIR/runs/smoke_v0.1" >&2
  exit 2
fi
mkdir -p "$WORK_DIR/runs" "$WORK_DIR/logs"
python3 - <<'PY'
import hashlib
import json
import shutil
from pathlib import Path
source = Path('/dfs/data/hewj13/models/Open-Jev-2B/package/checkpoint')
target = Path('/dfs/data/hewj13/ora_small_jev/derived_checkpoint_16k')
if target.exists():
    raise SystemExit('derived checkpoint already exists; use a new run configuration')
shutil.copytree(source, target)
config_path = target / 'model.json'
config = json.loads(config_path.read_text())
config['max_length'] = 16384
config_path.write_text(json.dumps(config, indent=1) + '\n')
record = {
    'source_checkpoint': str(source),
    'runtime_only_change': {'max_length': 16384},
    'weights_changed': False,
    'reason': 'all 612 inputs exceed 4096; maximum measured input is 14738 tokens',
    'model_json_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest(),
}
Path('/dfs/data/hewj13/ora_small_jev/derived_checkpoint_16k.json').write_text(json.dumps(record, indent=1) + '\n')
PY

mkdir -p "$HF_HOME/hub/models--Qwen--Qwen3.5-2B/snapshots"
if [[ ! -e "$HF_HOME/hub/models--Qwen--Qwen3.5-2B/snapshots/$REVISION" ]]; then
  ln -s "$BASE_DIR" "$HF_HOME/hub/models--Qwen--Qwen3.5-2B/snapshots/$REVISION"
fi
python3 - <<'PY'
from huggingface_hub import snapshot_download
path = snapshot_download('Qwen/Qwen3.5-2B',
                         revision='15852e8c16360a2fea060d615a32b45270f8a8fc',
                         local_files_only=True)
print('OFFLINE_SNAPSHOT_OK', path)
PY

cd "$OPEN_JEV_ROOT"
PYTHONPATH=. python3 -m jev.data validate "$DATA_DIR" > "$WORK_DIR/logs/data_validation.log"
set +e
PYTHONPATH=. CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-1} \
  python3 -m jev.train \
  --model Qwen/Qwen3.5-2B \
  --revision "$REVISION" \
  --data "$DATA_DIR" \
  --output "$WORK_DIR/runs/smoke_v0.1" \
  --steps 10 \
  --train-rows 50 \
  --calibration-rows 6 \
  --eval-rows 56 \
  --max-length "$MAX_LENGTH" \
  --lora-rank 8 \
  --accumulation 1 \
  --lr 5e-5 \
  --head-lr 1e-4 \
  --brier-weight 0.1 \
  --seed 42 \
  --training-sampling shuffled \
  --checkpoint-every 0 \
  --initial-checkpoint "$WORK_DIR/derived_checkpoint_16k" \
  --defer-heldout > "$WORK_DIR/logs/smoke_v0.1.log" 2>&1
status=$?
set -e
tail -80 "$WORK_DIR/logs/smoke_v0.1.log"
if [[ $status -ne 0 ]]; then
  exit "$status"
fi
python3 - <<'PY'
import json
from pathlib import Path
summary = json.loads(Path('/dfs/data/hewj13/ora_small_jev/runs/smoke_v0.1/summary.json').read_text())
print(json.dumps({key: summary.get(key) for key in (
    'status', 'model', 'steps', 'checkpoint_reload_max_error',
    'heldout_evaluation', 'elapsed_seconds', 'phase_metrics')}, indent=1))
PY

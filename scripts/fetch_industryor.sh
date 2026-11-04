#!/bin/bash
# Fetch IndustryOR-100 (CC-BY-NC-4.0, research use only) from HuggingFace and
# verify integrity. Data file itself is gitignored; this script + the pinned
# sha256 are the reproducible record.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/industryor
curl -sL -o data/industryor/IndustryOR.json \
  "https://huggingface.co/datasets/CardinalOperations/IndustryOR/resolve/main/IndustryOR.json"
echo "5b889e49d9aa64ae5b368bc80a05ee71a1daf20d126f54efc6207c98f9095f36  data/industryor/IndustryOR.json" \
  | sha256sum -c -

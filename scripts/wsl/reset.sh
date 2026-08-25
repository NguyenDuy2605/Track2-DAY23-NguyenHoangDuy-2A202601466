#!/usr/bin/env bash
# [WIN HELPER] Reset moi truong ve trang thai dau lab: clean -> seed -> up stack.
# Tuong duong: make clean && make seed && bash scripts/up_bare.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
export PATH="$HOME/.venvs/lab23/bin:$PATH"   # dam bao dung python cua venv lab23

bash scripts/down_bare.sh 2>/dev/null || true
pkill -f "uvicorn serving.app" 2>/dev/null || true
pkill -f "uvicorn edge.proxy" 2>/dev/null || true
sleep 1

rm -rf state/region-a state/region-b state/_replica run
rm -f reports/*.jsonl reports/*.json chaos/chaos-events.jsonl reports/_test-health.jsonl
mkdir -p run reports chaos
printf a > edge/active_region

python3 state/seed_vectors.py --region a --docs 200
python3 state/seed_vectors.py --region b --docs 0 --weights-mb 0

bash scripts/up_bare.sh
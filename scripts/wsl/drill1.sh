#!/usr/bin/env bash
# [WIN HELPER] Drill 1 — baseline KHONG co DR. Dung dung lenh GUIDE.md Step 2.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
export PATH="$HOME/.venvs/lab23/bin:$PATH"   # dam bao dung python cua venv lab23

python3 loadgen/traffic.py --duration 40 --rps 2 --out reports/drill-1-nodr.jsonl &
TP=$!
sleep 8
python3 chaos/kill_region.py --region a --mode netblock --mock
wait $TP

echo "== RESTORE region a =="
python3 chaos/kill_region.py restore --region a --backend bare

echo "== MEASURE DRILL 1 (ky vong: NO_RECOVERY) =="
python3 tools/measure_rto.py --loadgen reports/drill-1-nodr.jsonl \
  --target-rto 300 | tee reports/measure-drill-1.json
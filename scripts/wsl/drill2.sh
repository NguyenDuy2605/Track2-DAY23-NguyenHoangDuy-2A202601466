#!/usr/bin/env bash
# [WIN HELPER] Drill 2 — replay attack VOI day enough DR automation. GUIDE.md Step 4.
# Thu tu: ingest + replicate TRUOC -> traffic + health_checker -> kill -> runbook auto.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
export PATH="$HOME/.venvs/lab23/bin:$PATH"   # dam bao dung python cua venv lab23
mkdir -p run

python3 state/ingest.py --region a --rate 0.5 --duration 150 > run/ingest.log 2>&1 &
I=$!
python3 state/replicate.py --every 30 --duration 150 --backend fs > run/replicate.log 2>&1 &
R=$!
sleep 5   # cho chu ky replication dau tien hoan thanh truoc khi attack

python3 loadgen/traffic.py --duration 100 --rps 2 --out reports/drill-2-withdr.jsonl > run/traffic2.log 2>&1 &
T=$!
python3 dr/health_checker.py --interval 1 --threshold 3 --duration 100 --out reports/health-events.jsonl > run/health.log 2>&1 &
H=$!
sleep 12
python3 chaos/kill_region.py --region a --mode netblock --mock
python3 dr/runbook.py --primary a --target b --backend fs --auto

wait $T; wait $H
kill $I $R 2>/dev/null

echo "== MEASURE DRILL 2 (ky vong: valid=true, PASS) =="
python3 tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl \
  --target-rto 300 | tee reports/measure-drill-2.json
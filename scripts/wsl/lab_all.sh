#!/usr/bin/env bash
# [WIN HELPER] Chay TOAN BO pipeline trong MOT phien WSL duy nhat de cac service
# nen khong bi kill khi phien ket thuc: unit-test -> reset -> drill1 -> restart
# -> drill2 -> day du pytest. Tong thoi luong ~5 phut.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
export PATH="$HOME/.venvs/lab23/bin:$PATH"
export PYTHONUNBUFFERED=1
cd "$REPO" || exit 1

# Chan chay double-instance: khoa doc-ghi bang flock (tu dong nha khi thoat)
mkdir -p run
exec 9>run/lab_all.lock
if ! flock -n 9; then
  echo "LAB-ALL ALREADY RUNNING -> khong chay them"; exit 1
fi

echo "=== PHASE 0: UNIT TESTS (dr/) ==="
python3 -m pytest tests/test_failover.py -v

echo "=== PHASE 1: RESET + UP STACK ==="
bash scripts/wsl/reset.sh

echo "=== PHASE 2: DRILL 1 — baseline KHONG DR ==="
bash scripts/wsl/drill1.sh

echo "=== PHASE 3: RESTART STACK (region a song lai, state giu nguyen) ==="
bash scripts/wsl/restart.sh

echo "=== PHASE 4: DRILL 2 — attack lai VOI DR automation ==="
bash scripts/wsl/drill2.sh

echo "=== PHASE 5: FULL TEST SUITE ==="
python3 -m pytest tests/ -v

echo "ALL-PHASES-DONE"
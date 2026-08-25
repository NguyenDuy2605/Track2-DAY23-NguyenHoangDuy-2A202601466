#!/usr/bin/env bash
# [WIN HELPER] Restart lai stack (giu nguyen state da seed) — dung giua 2 drill.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
export PATH="$HOME/.venvs/lab23/bin:$PATH"   # dam bao dung python cua venv lab23

bash scripts/down_bare.sh 2>/dev/null || true
pkill -f "uvicorn serving.app" 2>/dev/null || true
pkill -f "uvicorn edge.proxy" 2>/dev/null || true
sleep 1

# Truoc drill 2, edge phai tro ve region a nhu ban dau
printf a > edge/active_region
bash scripts/up_bare.sh

echo "== CHECKPOINT =="
curl -s localhost:8001/readyz | head -c 300; echo
curl -s localhost:8002/readyz | head -c 300; echo
curl -s localhost:8080/edge/state; echo
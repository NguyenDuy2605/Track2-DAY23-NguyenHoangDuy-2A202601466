#!/usr/bin/env bash
# [WIN HELPER] Chay 1 lenh bat ky ben trong repo, voi venv lab23 duoc activate.
# Dung: wsl -d Ubuntu -- bash /mnt/d/<repo>/scripts/wsl/exec.sh <command> [args...]
set -euo pipefail
REPO=/mnt/d/Track2-DAY23-NguyenHoangDuy-2A202601466
export PATH="$HOME/.venvs/lab23/bin:$PATH"
cd "$REPO"
exec "$@"
#!/usr/bin/env bash
# [WIN HELPER] Tao venv trong WSL home + cai dependencies cho lab Day23.
set -euo pipefail
REPO=/mnt/d/Track2-DAY23-NguyenHoangDuy-2A202601466
VENV="$HOME/.venvs/lab23"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -q -r "$REPO/requirements.txt"
"$VENV/bin/python" - <<'EOF'
import fastapi, uvicorn, httpx, pytest
print("fastapi", fastapi.__version__)
print("uvicorn", uvicorn.__version__)
print("httpx", httpx.__version__)
print("pytest", pytest.__version__)
import signal
print("SIGSTOP", signal.SIGSTOP, "SIGKILL", signal.SIGKILL)
EOF
echo "SETUP-OK"
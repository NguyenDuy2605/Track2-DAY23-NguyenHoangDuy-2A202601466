#!/usr/bin/env bash
# [WIN HELPER] Kiem tra moi truong WSL cho lab Day23. Khong anh huong code cham diem.
set -u
echo "== os =="; head -2 /etc/os-release
echo "== python3 =="; command -v python3 && python3 --version
echo "== pip3 =="; command -v pip3 && pip3 --version || echo "no pip3"
echo "== venv module =="; python3 -c "import venv; print('venv ok')" 2>&1
echo "== ensurepip =="; python3 -m ensurepip --version 2>&1 | head -1
echo "== deps global =="; python3 - <<'EOF' 2>&1
mods = ["fastapi", "uvicorn", "httpx", "pytest"]
for m in mods:
    try:
        mod = __import__(m)
        print(m, "OK", getattr(mod, "__version__", "?"))
    except Exception as e:
        print(m, "MISSING", type(e).__name__)
EOF
echo "== access repo =="; ls /mnt/d/Track2-DAY23-NguyenHoangDuy-2A202601466 | head -5
echo "== done =="
#!/usr/bin/env bash
# [WIN HELPER] Kiem dinh CUOI CUNG: moi citation trong rto-evidence.md phai khop
# noi dung dong log that; tung gate rubric chay rieng le; ASCII; moitruong sach.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
export PATH="$HOME/.venvs/lab23/bin:$PATH"   # dam bao dung python cua venv lab23

echo "===== [1] COMPILE ALL PY ====="
python3 -m py_compile dr/health_checker.py dr/failover.py dr/runbook.py \
  tools/measure_rto.py state/snapshot.py chaos/kill_region.py && echo COMPILE-OK

echo "===== [2] CITATION CONTENT CHECK (rto-evidence.md) ====="
python3 - <<'EOF'
import re, pathlib
t = pathlib.Path("reports/rto-evidence.md").read_text()
refs = re.findall(r"`([\w./-]+\.(?:jsonl|json|md|log|py))(?::(\d+))?`", t)
seen = set()
ok = True
for path, line in refs:
    key = (path, line)
    if key in seen:
        continue
    seen.add(key)
    p = pathlib.Path(path)
    if not p.exists():
        print(f"MISSING FILE: {path}"); ok = False; continue
    content = "<whole file>"
    if line:
        lines = p.read_text().splitlines()
        if int(line) > len(lines):
            print(f"LINE OUT OF RANGE: {path}:{line} (file has {len(lines)})"); ok = False; continue
        content = lines[int(line) - 1][:200]
    print(f"OK {path}:{line or '-'}")
    print(f"     -> {content}")
print("CITATIONS:", len(refs), "unique:", len(seen), "ALL-OK" if ok else "HAS-ERRORS")

# Kiem tra tu khoa cam
bad = []
if "TEMPLATE" in t: bad.append("TEMPLATE")
if "__" in t: bad.append("__")
print("FORBIDDEN-STRINGS:", bad if bad else "none")
EOF

echo "===== [3] ASCII CHECK 3 REPORTS ====="
for f in reports/rto-evidence.md reports/postmortem.md reports/runbook.md; do
  n=$(grep -cP '[^\x00-\x7F]' "$f" || true)
  echo "$f non-ascii-lines=$n"
done

echo "===== [4] CHAOS EVENTS INTEGRITY ====="
python3 - <<'EOF'
import json, pathlib
for i, line in enumerate(pathlib.Path("chaos/chaos-events.jsonl").read_text().splitlines(), 1):
    e = json.loads(line)
    print(f"L{i}: action={e.get('action')} region={e.get('region')} "
          f"other_alive={e.get('other_alive')} forced_both={e.get('forced_both')}")
EOF

echo "===== [5] RUBRIC GATES (chay rieng le) ====="
for t in \
  "tests/test_rto_evidence.py::test_drill1_ton_tai_va_khong_phuc_hoi" \
  "tests/test_failover.py::test_health_checker_can_threshold_lien_tiep" \
  "tests/test_failover.py::test_failover_khong_cutover_khi_target_chua_ready" \
  "tests/test_rto_evidence.py::test_drill2_hop_le" \
  "tests/test_rto_evidence.py::test_rto_do_duoc_bang_timestamp" \
  "tests/test_failover.py::test_rpo_dem_dung_so_doc_bi_mat" \
  "tests/test_rto_evidence.py::test_rpo_duoc_do_chu_khong_uoc_luong" \
  "tests/test_rto_evidence.py::test_evidence_table_tro_vao_file_that" \
  "tests/test_rto_evidence.py::test_evidence_table_da_dien_that" \
  "tests/test_rto_evidence.py::test_so_trong_bang_khop_voi_so_trong_log" \
  "tests/test_rto_evidence.py::test_health_check_interval_duoc_ghi_lai" \
  "tests/test_rto_evidence.py::test_postmortem_co_gap_analysis" \
  "tests/test_rto_evidence.py::test_chaos_khong_giet_ca_hai_region"; do
  r=$(python3 -m pytest "$t" -q 2>&1 | tail -1)
  echo "$(basename $t): $r"
done

echo "===== [6] RUBRIC CLI CMD 1 (drill-1) ====="
python3 tools/measure_rto.py --loadgen reports/drill-1-nodr.jsonl --target-rto 300 | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print('valid:',d['valid'],'| verdict:',d['rto_verdict'],'| failed:',d['requests_failed'])"

echo "===== [7] RUBRIC CLI CMD 2 (drill-2) ====="
python3 tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300 | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print('valid:',d['valid'],'| warnings:',d['warnings'],'| verdict:',d['rto_verdict'],'| rto:',d['rto_measured_s'],'| rpo:',d['rpo_at_restore_s'],'| docs_lost:',d['docs_lost'],'| recovered_by:',d['recovered_by_region'])"

echo "===== [8] ENV CLEANLINESS ====="
ps -eo args | grep -E 'uvicorn|traffic\.py|health_checker' | grep -v grep | head -3 || echo "no stray lab processes"
echo "edge/active_region = $(cat edge/active_region)"
echo "FINAL-CHECK-DONE"
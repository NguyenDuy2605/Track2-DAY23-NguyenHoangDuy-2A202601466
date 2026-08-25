#!/usr/bin/env bash
# [WIN HELPER] Trich xuat bang bang chung: so dong cua cac su kien chot trong log.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
python3 - <<'EOF'
import json, pathlib

def rows(p):
    out = []
    for i, line in enumerate(pathlib.Path(p).read_text().splitlines(), 1):
        if line.strip():
            try:
                out.append((i, json.loads(line)))
            except json.JSONDecodeError:
                pass
    return out

def show(p, pred, label):
    print(f"--- {label} ({p}) ---")
    for i, e in rows(p):
        try:
            if pred(e):
                keys = {k: e[k] for k in ("ts","iso","step","region","to","action","seq",
                                          "status","ok","served_by","error","latency_ms",
                                          "rpo_seconds","docs_lost","waited_s","name")
                        if k in e}
                print(f"L{i}: {json.dumps(keys, ensure_ascii=False)}")
        except Exception as ex:
            print(f"L{i}: ERR {ex}")

k2 = None  # ts kill drill-2
for i, e in rows("chaos/chaos-events.jsonl"):
    if e.get("action") == "kill" and e["ts"] > 1787653800:  # lan chay moi nhat
        k2 = e["ts"]

show("chaos/chaos-events.jsonl", lambda e: True, "CHAOS EVENTS (tat ca)")
print(f"==> t_outage drill-2 = {k2}")

d1 = rows("reports/drill-1-nodr.jsonl")
t0d1 = [e for i, e in rows("chaos/chaos-events.jsonl") if e.get("action")=="kill"][0]["ts"]
first_fail_d1 = next(((i,e) for i,e in d1 if not e.get("ok") and e["ts"] >= t0d1), None)
n1 = len(d1)
print(f"--- DRILL1 loadgen: total={n1} lines, first_fail_after_kill=L{first_fail_d1[0] if first_fail_d1 else None}")

d2 = rows("reports/drill-2-withdr.jsonl")
after = [(i,e) for i,e in d2 if e["ts"] >= k2]
ff = next(((i,e) for i,e in after if not e.get("ok")), None)
rec = next(((i,e) for i,e in after if e.get("ok") and ff and e["ts"] > ff[1]["ts"]), None)
print(f"--- DRILL2 loadgen: total={len(d2)} lines")
if ff:   print(f"first_fail : L{ff[0]} iso? seq={ff[1].get('seq')} status={ff[1].get('status')} err={ff[1].get('error')} lat={ff[1].get('latency_ms')}")
if rec:  print(f"recovered  : L{rec[0]} seq={rec[1].get('seq')} served_by={rec[1].get('served_by')} lat={rec[1].get('latency_ms')}")

show("reports/health-events.jsonl", lambda e: True, "HEALTH EVENTS")
show("reports/failover-events.jsonl", lambda e: e.get("ts",0) >= k2 - 30, "FAILOVER EVENTS (drill-2)")
show("reports/runbook-run.jsonl", lambda e: True, "RUNBOOK RUN")

rep = rows("reports/replication.jsonl")
print(f"--- REPLICATION: {len(rep)} puts; last put ts={rep[-1][1]['snapshot_at']:.2f} L{rep[-1][0]}" if rep else "--- REPLICATION: none")
EOF
echo EVIDENCE-DUMP-DONE
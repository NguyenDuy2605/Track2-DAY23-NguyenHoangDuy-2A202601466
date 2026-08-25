# RTO/RPO Evidence -- Lab 23 (Track2-DAY23)

Quy tac: moi con so duoi day tro ve **mot dong log that** sinh ra boi drill chay tren may
(WSL Ubuntu 24.04, bare mode `--mock`, hai FastAPI region + edge proxy tren 127.0.0.1).
Cong cu tinh toan: `tools/measure_rto.py`; ket qua tho luu tai
`reports/measure-drill-1.json` va `reports/measure-drill-2.json`.

## 1. Drill 1 -- khong co DR (baseline, 2026-08-25T10:31:39Z)

| Chi so | Gia tri | Cach do | Evidence |
|---|---|---|---|
| t_outage | 10:31:39 UTC | `action:"kill", mode:"netblock"` (SIGSTOP) | `chaos/chaos-events.jsonl:1` |
| Request fail dau tien | +0.0s | dong `ok:false` dau tien sau t_outage, treo ~2017ms roi 503 | `reports/drill-1-nodr.jsonl:17` |
| Tong request / so fail | 32 / 16 | dem cac dong `ok:false` sau t_outage | `reports/measure-drill-1.json` |
| Request thanh cong sau do | khong co | khong co dong `ok:true` nao sau t_outage | `reports/measure-drill-1.json` |
| RTO | NO_RECOVERY | truong `rto_verdict` cua `tools/measure_rto.py` | `reports/measure-drill-1.json` |

Ket luan drill 1: khong co health check, region B trong (0 vector, thieu weights,
pool warm), edge cu tro mai vao region chet => 16 request lien tiep treo toi timeout
va khong bao gio phuc hoi.

## 2. Drill 2 -- co DR automation (t_outage 2026-08-25T10:32:32Z)

Chuoi su kien do `dr/runbook.py --auto` dieu phoi; nam buoc con nam trong
`reports/failover-events.jsonl` theo dung thu tu
`1_verify_target -> 2_restore_snapshot -> 3_scale_pool -> 4_wait_ready -> 5_dns_cutover`.

| Moc | +giay tu t_outage | Gia tri trong log | Evidence |
|---|---:|---|---|
| t_outage (moc 0) | 0 | `action:"kill", other_alive:true` | `chaos/chaos-events.jsonl:3` |
| User thay loi dau tien | +2.0 | seq 25; status 503; error "ReadTimeout"; latency_ms 2040.5 | `reports/drill-2-withdr.jsonl:26` |
| Health check phat hien | +7.1 | region "a", to "UNHEALTHY", consecutive_fails 3, reason "ReadTimeout" | `reports/health-events.jsonl:2` |
| Operator mo incident | +7.5 | `notify_delay_s:7.48` | `reports/runbook-run.jsonl:2` |
| Snapshot restore xong | +7.7 | step "2_restore_snapshot"; rpo_seconds 24.01; docs_lost 12 | `reports/failover-events.jsonl:2` |
| Region phu ready | +13.9 | step "4_wait_ready"; waited_s 6.15 | `reports/failover-events.jsonl:4` |
| DNS cutover | +14.0 | step "5_dns_cutover"; from "a", to "b" | `reports/failover-events.jsonl:5` |
| **Request OK dau tien tu B** | **+16.3** | seq 32; status 200; served_by "b"; latency_ms 65.6 | `reports/drill-2-withdr.jsonl:33` |

### Ket qua tong hop

| Chi so | Do duoc | Muc tieu (slide Sec 1) | Verdict |
|---|---|---|---|
| RTO -- Inference API | 16.3s | 300s (5 phut) | PASS -- `rto_verdict:"PASS"`, valid=true, warnings=[] |
| RPO -- Vector DB | 24.01s / 12 doc | 300s (5 phut) | PASS |

Nguon so: `reports/measure-drill-2.json` -- `valid:true`, `invalid_reasons:[]`,
`warnings:[]`, `killed_region:"a"`, `recovered_by_region:"b"`, `requests_failed:7`.
Health check ghi du cau hinh vao tung dong state_change: `interval_s:1.0, threshold:3`
=> detect floor ly thuyet `1x3 = 3.0s` (`reports/health-events.jsonl:2`). Chu ky
snapshot 30s cua `state/replicate.py` giai thich RPO: lan `put` cuoi truoc outage luc
10:32:14 (`reports/replication.jsonl:1`), outage 10:32:32, nen 12 doc ingest trong
khoang do (nhip 0.5 doc/s => moi doc cach nhau 2s => be rong du lieu mat ~24.01s)
khong co mat trong ban restore o region B.

## 3. RTO cua toi gom nhung gi (bat buoc)

Bon thanh phan cong dung bang RTO do duoc: 7.1 + 0.7 + 6.2 + 2.3 = 16.3.

| Thanh phan | Giay | No den tu dau | Giam duoc bang cach nao |
|---|---:|---|---|
| Health-check phat hien (ben trong co detect floor `1x3 = 3.0s`) | 7.1 | hieu `ts(UNHEALTHY,a) - ts(kill)` tai `reports/health-events.jsonl:2`; floor ghi trong `reports/measure-drill-2.json` | Ha interval duoi 1s (doi lai gap doi so probe va nguy co flapping Sec 4); probe 2 region song song thay vi tuan tu |
| Xac nhan outage + restore snapshot | 0.7 | runbook step 1-2 (`reports/runbook-run.jsonl:2`) toi `2_restore_snapshot` xong (`reports/failover-events.jsonl:2`) | Pre-restore standby nen dinh ky -- danh doi chi phi storage/compute luon san |
| GPU pool warm-up (warm -> full khi dang chay) | 6.2 | `waited_s:6.15` tai `reports/failover-events.jsonl:4` | Giu standby pool o `full` thuong truc (ton GPU nan roi) hoac ha WARMUP_SECONDS |
| DNS/LB TTL cache + nhip request cua loadgen | 2.3 | hieu giua cutover `reports/failover-events.jsonl:5` va dong OK dau `reports/drill-2-withdr.jsonl:33` | Giam EDGE_TTL_SECONDS 5->2s (doi lai doc file "DNS" day hon) |

Diem kiem chung automation: cutover (+14.0) xay ra SAU khi health check phat hien
(+7.1) nen `reports/measure-drill-2.json` khong co warning `t_cutover < t_detect`;
thu tu 5 buoc failover duoc doi chieu truc tiep tai `reports/failover-events.jsonl:1`.

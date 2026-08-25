# Postmortem -- DR Drill Lab 23 | Region-A outage 2026-08-25

Viet theo tinh than blameless (Sec 4): cau hoi la "he thong/process nao cho phep chuyen
nay xay ra", khong phai "ai lam sai". Toan bo moc thoi gian lay tu log that cua drill,
moi dong co evidence `path:line`.

## 1. Timeline (moi dong co evidence path:line)

| ISO time (UTC) | Su kien | Evidence |
|---|---|---|
| 10:31:39 | Drill 1: region A bi SIGSTOP khi dang phuc hoi traffic -> outage bat dau | `chaos/chaos-events.jsonl:1` |
| 10:31:39 | User dau tien bi anh huong (request treo toi timeout, +0.0s) | `reports/drill-1-nodr.jsonl:17` |
| 10:31:39->10:32:12 | Khong co co che nao phat hien; 16 request fail lien tiep; RTO = NO_RECOVERY | `reports/measure-drill-1.json` |
| 10:32:12 | Restore region A bang tay (`restore --region a --backend bare`) -- het drill 1 | `chaos/chaos-events.jsonl:2` |
| 10:32:32 | Drill 2: region A bi SIGSTOP lan hai (t_outage, moc 0 cua RTO clock) | `chaos/chaos-events.jsonl:3` |
| 10:32:34 | User dau tien bi anh huong (+2.0s) | `reports/drill-2-withdr.jsonl:26` |
| 10:32:39 | Health check alert: region A UNHEALTHY sau 3 fail lien tiep (+7.1s) | `reports/health-events.jsonl:2` |
| 10:32:39 | Operator biet tin / mo incident (+7.48s) | `reports/runbook-run.jsonl:2` |
| 10:32:39 | Operator confirm cutover -- runbook goi `failover()` dung mot lan | `reports/runbook-run.jsonl:3` |
| 10:32:39 | Snapshot restore xong o region B (rpo_seconds=24.01, docs_lost=12) | `reports/failover-events.jsonl:2` |
| 10:32:46 | Region B ready (warm-up 6.15s) va DNS cutover a->b | `reports/failover-events.jsonl:4` |
| 10:32:47 | Golden signals OK: p95=103.9ms, error rate=0.0 tren 10 request | `reports/runbook-run.jsonl:6` |
| 10:32:48 | Resolved: request OK dau tien duoc serve boi region B (+16.3s) | `reports/drill-2-withdr.jsonl:33` |

## 2. RTO/RPO do duoc vs muc tieu -- gap o buoc nao?

- RTO muc tieu: 300s | do duoc: **16.3s** | gap: **-283.7s** (tot hon muc tieu)
- RPO muc tieu: 300s | do duoc: **24.01s** (12 doc mat) | gap: **-275.99s**
- Nguon so: `reports/measure-drill-2.json` (valid=true, warnings=[], verdict PASS)
- **Buoc ton nhieu giay nhat:** health-check detection 7.1s (43.6% RTO) vi kill roi
  lech pha giua cac chu ky poll va moi probe chet cho het timeout 2s/lan; ke den la
  GPU pool warm-up 6.2s (38%) tai `reports/failover-events.jsonl:4`.
  Phan ra day du (cong dung 16.3): xem bang Sec 3 cua `reports/rto-evidence.md`.

## 3. Root cause (5 whys)

Khong phai "vi toi chay chaos script". Neu day la outage that:

1. Vi sao user chiu loi? -- Edge tro co dinh vao region A dang chet.
2. Vi sao edge khong chuyen? -- O baseline chua co health check nao doc `/readyz`;
   "process con song" (`/healthz`) bi luong tuong la "vung con serve duoc".
3. Vi sao khong chuyen tay duoc ngay? -- Region B trong: 0 vector, thieu weights,
   pool chi `warm`; cutover voi se doi 503 tu mot region thanh 503 tu ca hai
   (bay da ne trong `dr/failover.py`: buoc 4 timeout thi ABORT, khong cutover).
4. Vi sao B trong? -- Chua tung chay replication; snapshot chi ton tai khi
   `state/replicate.py` hoat dong, nen RPO phu thuoc chu ky 30s cua no.
5. He thong can gi de tu song sot? -- Bo ba khep kin: detection dua tren readiness
   (anti-flap threshold), standby duoc restore + scale truoc khi nhan traffic, va
   DNS cutover la buoc CUOI cung -- tat ca do bang timestamp, khong bang cam giac.

## 4. Action items (co owner + deadline)

| # | Action | Owner | Deadline | Giam RTO/RPO bao nhieu |
|---|---|---|---|---|
| 1 | Giu standby pool `full` thuong truc (pre-warmed) thay vi `warm` | Platform team | Tuan sau | -6.2s warm-up khoi RTO |
| 2 | Rut chu ky replicate 30s -> 10s (`state/replicate.py`) | Data team | Tuan sau | RPO ~24s -> ~8-10s |
| 3 | Giam EDGE_TTL_SECONDS 5->2; can nhac health-check o edge | Edge team | Tuan sau | -1 den -3s phan TTL |
| 4 | Them circuit breaker roi mo auto-failover khi ban-tu dong on dinh >=5 drill | SRE on-call | Cuoi thang | Bo 7.5s tre "operator biet tin" |
| 5 | Backfill du lieu tu B ve A truoc khi failback | Data team | Theo item 2 | Bao ve RPO chieu nguoc |

## 5. Ba cau hoi bat buoc tra loi

1. **`interval x threshold` la bao nhieu? Chiem bao nhieu % RTO?**
   `interval_s=1.0 x threshold=3` => detect floor ly thuyet **3.0s**, chiem **18.4%**
   RTO 16.3s. Thuc te detection mat 7.1s (43.6%) vi kill roi lech pha giua cac chu ky
   poll cong voi moi probe chet cho het timeout 2s (`reports/health-events.jsonl:2`).
2. **Ha interval nua thi RTO giam may giay -- tra gia gi (Sec 4 flapping)?**
   Interval 0.5s dua floor 3.0->1.5s nhung phan chi phoi thuc te la pha poll + timeout,
   nen RTO chi giam toi da ~1-1.5s (<9%). Gia phai tra: gap doi so probe len CA HAI
   region va cua so chong nhieu hep di -- Sec 4 canh bao full-auto khong circuit breaker
   gay failover hai chieu lien tuc. Diem can bang chon: 1s x 3-fail-lien-tiep.
3. **Outage 6 gio, region chinh mat du lieu vinh vien -- `docs_lost` nghia gi?**
   `docs_lost=12` luc restore = 12 ticket gan nhat (~24.01s du lieu) bien mat khoi
   ket qua tim kiem sau cutover. Trong outage 6 gio voi replicate 30s, day se la
   hang nghin doc: khach hoi "ticket cui toi dau?" va ho tro khong tra duoc -- mat
   doanh thu va niem tin, khong chi mot so lieu. Vi the RPO phai bao bang CA giay
   VA so document (`reports/failover-events.jsonl:2`).

## 6. Tra loi cau hoi bat buoc ghi trong docstring `dr/health_checker.py`

- interval=5s, threshold=3 => som nhat phat hien outage la **15s** (floor), chua ke
  timeout tung probe; con so do nam TRUC TIEP trong RTO.
- Voi muc tieu RTO 300s: floor phai nho hon xa 300s. Threshold=3 cho phep interval
  toi da ~95s ve ly thuyet, nhung khi do chap nhan phat hien muon gan 5 phut -- vo
  nghia thuc te. Chung toi chon interval=1s: floor 3s, hop mang LAN, van giu nguong
  chong flapping 3-fail-lien-tiep.
- Health checker KHONG import bat cu thu gi tu `serving/` -- chi goi HTTP `/readyz`.
  Neu chay chung process voi API duoc giam sat thi process chet dong nghia checker
  chet: khong ai bat coi. Tach process/may la dieu kien bat buoc de detection doc lap.

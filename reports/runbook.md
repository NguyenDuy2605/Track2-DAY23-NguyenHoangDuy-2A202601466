# Runbook 1 trang -- Region chinh down (da dien theo drill that 2026-08-25)

Nguoi chay: on-call truc ca. Moi truong mac dinh cua lab la **bare mode** (uvicorn chay
truc tiep, khong Docker). Moi lenh chay tu thu muc goc repo. So lieu tham chieu tu drill
that: RTO 16.3s, RPO 24.01s / 12 doc (`reports/measure-drill-2.json`).

| # | Buoc | Lenh | Biet la xong khi | Ai lam |
|---|---|---|---|---|
| 1 | Xac nhan outage (3 lan lien tiep, dung tin 1 lan fail) | `python chaos/kill_region.py status` va `curl -m 2 localhost:8001/readyz` (lap 3 lan) | `a.ready=false` 3 lan lien tiep, region B van `alive=true` | on-call |
| 2 | Mo incident + bam gio RTO clock (t_outage = ts dong kill moi nhat trong log) | `tail -n 5 chaos/chaos-events.jsonl`; kenh bao dong: #incidents | Co ts t_outage; dong `2_thong_bao_incident` xuat hien trong `reports/runbook-run.jsonl` voi `notify_delay_s` nho | on-call |
| 3 | Chay runbook ban-tu dong: xac nhan -> restore snapshot -> scale pool -> cho ready -> cutover (7 buoc goi trong 1 lenh; hoi y/N o buoc confirm) | `python dr/runbook.py --primary a --target b --backend fs` | Log co du step 1->7; buoc 3 ghi `failover_ok:true`, `waited_s~=6`; KHONG co `aborted_at` | on-call (tra loi `y`) |
| 4 | Kiem tra state da restore o region phu (vector + weights + pool) | `curl -s localhost:8002/v1/state` | `count >= 200`, `weights:true`, `pool_state:"full"` | on-call |
| 5 | Xac nhan DNS/LB da cat sang B | `cat edge/active_region` va `curl -s localhost:8080/edge/state` | File chua `b`; `active_region:"b"`; `curl localhost:8080/v1/infer` tra `"region":"b"` | on-call |
| 6 | Verify golden signals tren region moi | `python loadgen/traffic.py --duration 10 --rps 2 --out reports/golden-check.jsonl` | error rate < 5%, p95 < 500ms (drill that: p95=103.9ms, err=0.0 -- `reports/runbook-run.jsonl:6`) | on-call |
| 7 | Do RTO/RPO chinh thuc + mo postmortem | `python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` | JSON in ra co `"valid":true, "rto_verdict":"PASS"`; dien so vao `reports/postmortem.md` | on-call + IC |

**Luu y khi dung lenh khac mode:**
- Neu outage la SIGKILL (`--mode stop`) hoac process da chet han: sau drill phai
  `bash scripts/up_bare.sh` de dung lai region A (restore se bao `need_manual_start`).
- Neu outage la netblock (SIGSTOP): region A chi bi tam dung -- nho
  `python chaos/kill_region.py restore --region a --backend bare` truoc khi failback.
- Khong co snapshot nao: chay `python state/replicate.py --every 30 --duration N --backend fs`
  va cho it nhat 1 chu ky `put` xong truoc khi goi failover, neu khong se chet o buoc
  `2_restore_snapshot`.

**Rollback (failover nguoc ve A):**
- Dieu kien tra traffic ve A: A tra 200 o `/readyz` on dinh >= 5 phut lien tuc, du lieu
  da duoc dong bo nguoc (hoac IC chap nhan mat khoang du lieu chua replicate), va khong
  con canh bao loi nao tu golden signals o A.
- Ai quyet dinh: Incident Commander (IC) phe duyet; on-call thuc thi. Khong ai tu y
  failback khi chua co IC.
- Lenh rollback: sua `edge/active_region` thanh `a`
  (`printf a > edge/active_region`), roi xac nhan
  `curl -s localhost:8080/edge/state` cho `active_region:"a"` va
  `curl localhost:8080/v1/infer` tra `"region":"a"`.
- Circuit breaker (Sec 4 Anti-Patterns): cam failover/failback tu dong hai chieu -- moi lan
  chuyen traffic phai qua confirm cua nguoi (runbook mac dinh hoi y/N, chi `--auto` khi
  CI/cham diem); neu phat hien flapping (cutover 2 lan trong 10 phut), dong bang region
  hien tai va leo thang len IC.

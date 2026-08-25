"""BƯỚC 3c — SINH VIÊN VIẾT. Tự động hoá runbook §4 "Runbook: Region Chính Down".

7 bước trên slide, mỗi bước 1 dòng log có ts. Log này CHÍNH LÀ timeline của postmortem.
  1 xac_nhan_outage          — probe cả 2 region, đừng tin 1 lần fail (dùng nhiều lần
                              hoặc gọi health_checker.probe nếu đã viết xong 3a)
  2 thong_bao_incident       — ts của dòng này là mốc "operator biết tin", LUÔN LUÔN
                              SAU t_outage trong chaos-events (không thể trùng — operator
                              không thể biết ngay giây outage xảy ra). Ghi cả 2 ts vào
                              log để postmortem tính được "độ trễ thông báo".
  3 scale_gpu_pool           — gọi HÀM `failover.failover(...)` MỘT LẦN DUY NHẤT. Hàm
                              đó tự làm đủ 5 bước con (verify/restore/scale/wait/cutover)
                              và tự ghi log riêng vào reports/failover-events.jsonl.
  4 verify_state_replica     — KHÔNG gọi lại failover — chỉ ĐỌC kết quả (vector count +
                              weights ở region phụ) từ dict mà bước 3 trả về, để log vào
                              runbook-run.jsonl cho postmortem đọc 1 chỗ duy nhất.
  5 dns_cutover              — cũng chỉ đọc lại: kết quả cutover có ok hay không.
  6 verify_golden_signals    — 10 request thật vào region phụ: p95 latency + error rate
  7 post_incident            — elapsed_s + lệnh đo RTO

BÁN TỰ ĐỘNG, KHÔNG FULL-AUTO (§4: "failover đầu tiên nên là bán tự động — alert +
1-click confirm — tránh flapping gây failover 2 chiều liên tục"). Mặc định phải hỏi
người vận hành confirm; --auto chỉ dùng trong CI/khi chấm điểm.

Chạy:  python dr/runbook.py --primary a --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from dr import failover as fo  # noqa: E402

LOG = pathlib.Path("reports/runbook-run.jsonl")
URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def step(n, name, **kw):
    """Ghi 1 dòng {ts, iso, step, name, ...} vào LOG."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.time(),
           "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
           "step": n, "name": name, **kw}
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"RUNBOOK step {n}/7 {name}", json.dumps(rec), flush=True)
    return rec


def confirm(auto: bool, msg: str) -> bool:
    """auto=True -> True; ngược lại hỏi y/N. Bán tự động — không full-auto."""
    if auto:
        return True
    try:
        ans = input(f"{msg} [y/N]: ").strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


def _last_kill_ts():
    """ts của sự kiện kill MỚI NHẤT trong chaos-events (= t_outage drill này)."""
    p = pathlib.Path("chaos/chaos-events.jsonl")
    if not p.exists():
        return None
    kills = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("action") == "kill":
            kills.append(e)
    return kills[-1]["ts"] if kills else None


def _p95(lat_ms):
    xs = sorted(lat_ms)
    if not xs:
        return None
    i = max(0, min(len(xs) - 1, int(round(0.95 * (len(xs) - 1)))))
    return round(xs[i], 1)


def run(primary: str, target: str, backend: str, auto: bool) -> dict:
    """7 bước runbook. Gọi failover.failover(...) ĐÚNG MỘT LẦN ở bước 3."""
    from dr import health_checker as hc  # dùng lại probe của bước 3a

    summary: dict = {"primary": primary, "target": target,
                     "backend": backend, "ok": False}

    # ---- 1 xac_nhan_outage: probe cả 2 region, đừng tin 1 lần fail -------------
    samples, primary_fails = [], 0
    for i in range(3):
        pr = hc.probe(primary, 2.0)
        tg = hc.probe(target, 2.0)
        samples.append({"n": i + 1,
                        "primary": {"ready": pr[0], "reason": pr[1]},
                        "target": {"ready": tg[0], "reason": tg[1]}})
        if not pr[0]:
            primary_fails += 1
        time.sleep(0.3)
    confirmed = primary_fails >= 3
    step(1, "xac_nhan_outage", primary=primary, target=target,
         primary_down_probes=primary_fails, confirmed=confirmed, samples=samples)
    if not confirmed:
        summary["error"] = ("khong xac nhan duoc outage "
                            f"(region-{primary} van ready) -> KHONG failover")
        return summary

    # ---- 2 thong_bao_incident: mốc "operator biết tin", luôn SAU t_outage ------
    t_outage = _last_kill_ts()
    notify_delay_s = None if t_outage is None else round(time.time() - t_outage, 2)
    step(2, "thong_bao_incident", t_outage=t_outage,
         notify_delay_s=notify_delay_s,
         msg=f"incident mo: region-{primary} khong ready {primary_fails}/3 lan probe")

    if not confirm(auto, f"XAC NHAN failover sang region-{target}?"):
        summary["error"] = "operator tu choi failover"
        return summary

    # ---- 3 scale_gpu_pool: gọi HÀM failover ĐÚNG MỘT LẦN ----------------------
    fo_result = fo.failover(target=target, backend=backend, wait=90)
    restored = fo_result.get("restored") or {}
    st_after = fo_result.get("verified_after") or {}
    cut = fo_result.get("cutover") or {}
    step(3, "scale_gpu_pool", called_failover_once=True,
         failover_ok=bool(fo_result.get("ok")),
         aborted_at=fo_result.get("aborted_at"),
         waited_s=fo_result.get("waited_s"), error=fo_result.get("error"))

    # ---- 4 verify_state_replica: chỉ ĐỌC kết quả từ dict bước 3 trả về ---------
    step(4, "verify_state_replica",
         rpo_seconds=restored.get("rpo_seconds"),
         docs_lost=restored.get("docs_lost"),
         embed_model_version=restored.get("embed_model_version"),
         snapshot_at=restored.get("snapshot_at"),
         vector_count=st_after.get("count"), weights=st_after.get("weights"))

    # ---- 5 dns_cutover: cũng chỉ đọc lại kết quả cutover -----------------------
    cutover_done = bool(cut.get("to"))
    step(5, "dns_cutover", ok=cutover_done, **cut)
    if not fo_result.get("ok"):
        summary["error"] = ("failover abort/that bai -> KHONG co cutover. "
                            "Xem reports/failover-events.jsonl")
        return summary

    # ---- 6 verify_golden_signals: 10 request thật vào region phụ ---------------
    latencies, errors = [], 0
    for i in range(10):
        t0 = time.time()
        try:
            r = httpx.get(f"{URL[target]}/v1/infer",
                          params={"q": f"golden check #{i}"}, timeout=3.0)
            body_ok = False
            try:
                body_ok = r.status_code == 200 and bool(r.json().get("answer"))
            except Exception:
                pass
            latencies.append((time.time() - t0) * 1000)
            if not body_ok:
                errors += 1
        except Exception:
            errors += 1
        time.sleep(0.05)
    p95_ms, error_rate = _p95(latencies), round(errors / 10, 2)
    step(6, "verify_golden_signals", requests=10, p95_ms=p95_ms,
         error_rate=error_rate, verdict="OK" if error_rate == 0 else "DEGRADED")

    # ---- 7 post_incident --------------------------------------------------------
    elapsed_s = None if t_outage is None else round(time.time() - t_outage, 2)
    measure_cmd = ("python3 tools/measure_rto.py "
                   "--loadgen reports/drill-2-withdr.jsonl --target-rto 300")
    step(7, "post_incident", elapsed_s=elapsed_s, measure_cmd=measure_cmd,
         note="chay lenh tren de cong bo RTO/RPO tu log")

    summary.update(ok=True, t_outage=t_outage, elapsed_s=elapsed_s,
                   p95_ms=p95_ms, error_rate=error_rate,
                   rpo_seconds=restored.get("rpo_seconds"),
                   docs_lost=restored.get("docs_lost"))
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--primary", default="a")
    p.add_argument("--target", default="b")
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--auto", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(a.primary, a.target, a.backend, a.auto), indent=2))

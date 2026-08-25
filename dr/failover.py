"""BƯỚC 3b — SINH VIÊN VIẾT. Cutover sang region phụ.

5 bước, THỨ TỰ QUAN TRỌNG (§2 Kiến Trúc Tham Chiếu: DNS/LB, compute, state là 3 lớp riêng):
  1_verify_target    — /v1/state của region phụ: weights? vector count? pool_state?
  2_restore_snapshot — gọi state/snapshot.py get + state/snapshot.py rpo()
                       Log BẮT BUỘC: rpo_seconds, docs_lost, embed_model_version.
                       (§3: "backup index nhưng quên backup embedding model version
                        -> index không tương thích khi restore")
  3_scale_pool       — ghi "full" vào state/region-<t>/pool_state (warm -> full)
  4_wait_ready       — POLL /readyz tới khi 200. Region phụ có WARMUP_SECONDS —
                       đây là GPU pool warm-up của §4, nó nằm trong RTO của bạn.
  5_dns_cutover      — ghi region đích vào edge/active_region

BẪY: nếu bạn đổi edge/active_region TRƯỚC bước 4, user sẽ nhận 503 từ CẢ HAI region
và RTO của bạn dài hơn, không ngắn hơn. Nếu bước 4 timeout -> ABORT, KHÔNG cutover.

Mỗi bước ghi 1 dòng vào reports/failover-events.jsonl với ts + step.
Không có dòng 5_dns_cutover = tools/measure_rto.py không tìm được t_cutover = mất điểm.

Chạy:  python dr/failover.py --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from state import snapshot  # noqa: E402

URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}
LOG = pathlib.Path("reports/failover-events.jsonl")
ACTIVE_FILE = pathlib.Path("edge/active_region")


def emit(**kw):
    """Append 1 dòng JSONL có ts + iso vào LOG, và print ra stdout."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.time(),
           "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), **kw}
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print("FAILOVER", json.dumps(rec), flush=True)
    return rec


def state_of(region: str) -> dict:
    """Helper nội bộ: đọc /v1/state của 1 region (weights? vector count? pool_state?)."""
    r = httpx.get(f"{URL[region]}/v1/state", timeout=5.0)
    r.raise_for_status()
    return r.json()


def _restore_with_retry(target: str, backend: str, tries: int = 4):
    """snapshot.get copy đè vectors.sqlite mà serving có thể đang mở mode ro ->
    thỉnh thoảng PermissionError trên Windows/9p: thử lại vài lần rồi mới bỏ."""
    last = None
    for _ in range(tries):
        try:
            return snapshot.get(target, backend), None
        except PermissionError as e:
            last = e
            time.sleep(0.4)
        except SystemExit as e:  # chưa từng có `put` nào -> hết cứu, abort sạch sẽ
            return None, str(e)
    return None, f"restore failed sau {tries} lần: {last}"


def failover(target: str, backend: str, wait: float) -> dict:
    """5 bước ở trên, đúng thứ tự. Bước 4 timeout -> ABORT, KHÔNG bao giờ cutover."""
    primary = "a" if target == "b" else "b"
    result: dict = {"ok": False, "primary": primary, "target": target, "backend": backend}

    # ---- 1_verify_target: region phụ đang ở trạng thái nào? -------------------
    try:
        st = state_of(target)
    except Exception as e:
        st = {"region": target, "error": type(e).__name__}
    emit(step="1_verify_target", region=target, pool_state=st.get("pool_state"),
         vectors=st.get("count"), weights=bool(st.get("weights")),
         error=st.get("error"))
    result["verified_before"] = st

    # ---- 2_restore_snapshot: restore + đo RPO THẬT từ timestamp --------------
    meta, err = _restore_with_retry(target, backend)
    if meta is None:
        emit(step="2_restore_snapshot", ok=False, error=err)
        result["error"] = err
        result["aborted_at"] = "2_restore_snapshot"
        return result  # không có snapshot thì KHÔNG ĐƯỢC cutover
    rpo = snapshot.rpo(pathlib.Path(f"state/region-{primary}/vectors.sqlite"),
                       pathlib.Path(f"state/region-{target}/vectors.sqlite"))
    emit(step="2_restore_snapshot", ok=True, region=target, backend=backend,
         snapshot_at=meta.get("snapshot_at"),
         embed_model_version=meta.get("embed_model_version"),
         rpo_seconds=rpo.get("rpo_seconds"), docs_lost=rpo.get("docs_lost"),
         primary_latest_doc_ts=rpo.get("primary_latest_doc_ts"),
         restored_latest_doc_ts=rpo.get("restored_latest_doc_ts"))
    result["restored"] = {**meta, **rpo}

    # ---- 3_scale_pool: warm -> full (GPU pool warm-up bắt đầu tính từ đây) ----
    pool_file = pathlib.Path(f"state/region-{target}") / "pool_state"
    pool_file.parent.mkdir(parents=True, exist_ok=True)
    prev_pool = pool_file.read_text().strip() if pool_file.exists() else "cold"
    pool_file.write_text("full")
    emit(step="3_scale_pool", region=target, from_pool=prev_pool, to_pool="full")

    # ---- 4_wait_ready: POLL /readyz tới khi 200 hoặc hết `wait` giây ----------
    deadline, t_start, ready, last_reasons = time.time() + wait, time.time(), False, []
    while time.time() < deadline:
        try:
            r = httpx.get(f"{URL[target]}/readyz", timeout=2.0)
            if r.status_code == 200:
                ready = True
                break
            try:
                last_reasons = r.json().get("reasons", [])
            except Exception:
                last_reasons = [f"http_{r.status_code}"]
        except Exception as e:
            last_reasons = [type(e).__name__]
        time.sleep(0.5)
    waited_s = round(time.time() - t_start, 2)
    emit(step="4_wait_ready", ready=ready, waited_s=waited_s, reasons=last_reasons)
    if not ready:
        # BẪY: đổi DNS lúc này => user nhận 503 từ CẢ HAI region => RTO dài hơn.
        result["aborted_at"] = "4_wait_ready"
        result["error"] = f"target-{target} khong ready sau {wait}s: {last_reasons}"
        return result

    # Xác minh lại state SAU restore để runbook/postmortem đọc 1 chỗ duy nhất.
    try:
        st_after = state_of(target)
    except Exception as e:
        st_after = {"region": target, "error": type(e).__name__}

    # ---- 5_dns_cutover: CHỈ GIỜ mới ghi region đích vào edge/active_region ---
    try:
        from_region = (ACTIVE_FILE.read_text().strip() if ACTIVE_FILE.exists() else "a")
    except Exception:
        from_region = "a"
    ACTIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_FILE.write_text(target)
    emit(step="5_dns_cutover", from_region=from_region, to=target)

    result.update(ok=True, waited_s=waited_s, cutover={"from": from_region, "to": target},
                  verified_after=st_after)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="b", choices=["a", "b"])
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--wait", type=float, default=60)
    a = p.parse_args()
    print(json.dumps(failover(a.target, a.backend, a.wait), indent=2))

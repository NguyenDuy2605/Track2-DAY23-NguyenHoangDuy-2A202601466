"""BƯỚC 3a — SINH VIÊN VIẾT. Health checker cho 2 region.

Yêu cầu (đọc §4 "Kiến Trúc Health-Check-Based Failover" + §2 "DNS Failover"):
  1. Poll /readyz của CẢ HAI region mỗi `interval` giây (mặc định 5s).
     Dùng /readyz, KHÔNG dùng /healthz. /healthz chỉ nói "process còn sống" —
     region có process sống nhưng vector DB rỗng thì vẫn không serve được.
  2. Chỉ đổi trạng thái sau `threshold` lần fail LIÊN TIẾP (mặc định 3).
     Một lần fail không phải outage. Đây là chống flapping (§4 Anti-Patterns).
  3. Ghi 1 dòng JSONL MỖI LẦN ĐỔI TRẠNG THÁI (không ghi mỗi lần poll — log sẽ ngập).
     Dòng bắt buộc có: ts, region, to (HEALTHY|UNHEALTHY), reason,
     interval_s, threshold. Thiếu interval_s/threshold thì tools/measure_rto.py
     không tính được detect floor -> mất điểm.

Chạy:  python dr/health_checker.py --interval 5 --threshold 3 --duration 300 \
              --out reports/health-events.jsonl

CÂU HỎI PHẢI TRẢ LỜI TRƯỚC KHI VIẾT (ghi câu trả lời vào reports/postmortem.md):
  interval=5s, threshold=3 -> sớm nhất bạn có thể phát hiện outage là bao nhiêu giây?
  Con số đó nằm TRONG RTO của bạn. Muốn RTO 5 phút thì được phép chọn interval bao nhiêu?
"""
import argparse
import json
import pathlib
import time

import httpx

URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def probe(region: str, timeout: float) -> tuple[bool, str]:
    """Trả về (ready, reason). Timeout PHẢI có — netblock làm request treo mãi."""
    try:
        r = httpx.get(f"{URL[region]}/readyz", timeout=timeout)
    except Exception as e:
        # Process chết  -> ConnectError (fail nhanh).
        # netblock/SIGSTOP -> ReadTimeout/ConnectTimeout (request treo tới timeout).
        return False, type(e).__name__
    if r.status_code == 200:
        return True, "ready"
    try:
        reasons = ";".join(r.json().get("reasons", []))
    except Exception:
        reasons = ""
    return False, reasons or f"http_{r.status_code}"


def run(interval: float, timeout: float, threshold: int, duration: float, out: pathlib.Path):
    """Vòng lặp poll + phát hiện transition + ghi JSONL (chỉ ghi khi ĐỔI trạng thái).

    Detect floor = interval * threshold: với interval=5, threshold=3 thì sớm nhất
    phát hiện outage là ~15s (nằm TRONG RTO). Ghi log kèm interval_s/threshold để
    tools/measure_rto.py tính được detect floor — thiếu là mất điểm.
    """
    end = time.time() + duration
    regions = ("a", "b")
    state = {r: "HEALTHY" for r in regions}      # khởi đầu: giả định đang healthy
    consec_fail = {r: 0 for r in regions}
    consec_ok = {r: 0 for r in regions}
    out.parent.mkdir(parents=True, exist_ok=True)

    def write(rec: dict) -> None:
        with out.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        print("HEALTH", json.dumps(rec), flush=True)

    out.touch(exist_ok=True)  # đảm bảo file log tồn tại ngay cả khi không có transition

    while time.time() < end:
        cycle = time.time()
        for region in regions:
            ready, reason = probe(region, timeout)
            if ready:
                consec_fail[region] = 0
                consec_ok[region] += 1
                if state[region] != "HEALTHY" and consec_ok[region] >= threshold:
                    state[region] = "HEALTHY"
                    rec = {"ts": time.time(),
                           "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                           "event": "state_change", "region": region,
                           "from": "UNHEALTHY", "to": "HEALTHY", "reason": reason,
                           "consecutive_oks": consec_ok[region],
                           "interval_s": interval, "threshold": threshold}
                    write(rec)
            else:
                consec_ok[region] = 0
                consec_fail[region] += 1
                # Một lần fail KHÔNG phải outage: chỉ flip sau `threshold` fail LIÊN TIẾP.
                if consec_fail[region] >= threshold and state[region] != "UNHEALTHY":
                    state[region] = "UNHEALTHY"
                    rec = {"ts": time.time(),
                           "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                           "event": "state_change", "region": region,
                           "from": "HEALTHY", "to": "UNHEALTHY", "reason": reason,
                           "consecutive_fails": consec_fail[region],
                           "interval_s": interval, "threshold": threshold}
                    write(rec)
        # Ngủ phần còn lại của chu kỳ để chu kỳ đều nhau ~interval giây.
        time.sleep(max(0.0, interval - (time.time() - cycle)))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--threshold", type=int, default=3)
    p.add_argument("--duration", type=float, default=300)
    p.add_argument("--out", default="reports/health-events.jsonl")
    a = p.parse_args()
    run(a.interval, a.timeout, a.threshold, a.duration, pathlib.Path(a.out))

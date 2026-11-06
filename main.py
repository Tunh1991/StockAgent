"""
main.py - Vòng quét Watchlist và CLI cho hệ thống multi-agent
  Tầng 1 (Rule Engine, Python): quét Watchlist trong phiên, tính chỉ báo, lọc tín hiệu.
  Tầng 2 (Multi-Agent): Analyst (LLM) -> Validator (Python) -> Critic (LLM, khi MUA GOM),
                        Python ra quyết định cuối (xem orchestrator.py).

Cách chạy:
  python main.py                 # quét liên tục 9h00-14h45 (mỗi SCAN_INTERVAL_MIN phút)
  python main.py --once          # quét 1 lượt rồi thoát
  python main.py --once --dry-run --symbols HPG FPT   # không gọi Gemini, chỉ in tín hiệu
  python main.py --once --force --symbols HPG          # bỏ qua bộ lọc, gọi Gemini để kiểm thử
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import llm  # đọc .env khi import
from data_loader import get_stock_history
from indicators import (
    MIN_BARS,
    check_breakout_trigger,
    compute_technical_indicators,
    price_levels,
    rsi_state,
    session_progress,
)
from fundamentals import store
from fundamentals.ratios import valuation
from orchestrator import run_pipeline

BASE_DIR = Path(__file__).resolve().parent
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
logger = logging.getLogger("stock_agent")

WATCHLIST = [s.strip().upper() for s in os.getenv(
    "WATCHLIST", "HPG,SSI,FPT,VCB,TCB,MWG,VNM,DXG").split(",") if s.strip()]
SCAN_INTERVAL_MIN = float(os.getenv("SCAN_INTERVAL_MIN", "4"))
DATA_MIN_INTERVAL_SEC = float(os.getenv("DATA_MIN_INTERVAL_SEC", "0.5"))
HISTORY_BARS = 160  # đủ cho HIGH_120
MAX_DAILY_FAILURES = int(os.getenv("MAX_DAILY_FAILURES", "3"))  # số lần Analyst lỗi tối đa/mã/ngày
SIGNALS_FILE = BASE_DIR / "signals.jsonl"

data_limiter = llm.RateLimiter(DATA_MIN_INTERVAL_SEC)


def now_vn() -> datetime:
    return datetime.now(VN_TZ)


def is_trading_time(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return (9 * 60 <= hm < 11 * 60 + 30) or (13 * 60 <= hm <= 14 * 60 + 45)


def latest_metrics(df) -> dict:
    """Số liệu phiên mới nhất, dùng cho --force (bỏ qua bộ lọc)."""
    last = df.iloc[-1]
    return {
        "date": str(last["date"]), "close": float(last["close"]),
        "volume": int(last["volume"]), "vol_projected": int(last["VOL_PROJECTED"]),
        "vol_ma20": int(last["VOL_MA20"]), "vol_spike_ratio": round(float(last["VOL_SPIKE_RATIO"]), 2),
        "ma20": round(float(last["MA20"]), 2), "ma50": round(float(last["MA50"]), 2),
        "ema20": round(float(last["EMA20"]), 2), "rsi": round(float(last["RSI"]), 2),
        "rsi_state": rsi_state(float(last["RSI"])),
        "macd": round(float(last["MACD"]), 4), "macd_signal": round(float(last["MACD_SIGNAL"]), 4),
        "macd_hist": round(float(last["MACD_HIST"]), 4),
        "support": round(float(last["SUPPORT"]), 2), "resistance": round(float(last["RESISTANCE"]), 2),
        "trigger_reasons": [],
    }


def scan_symbol(symbol: str, now: datetime, force: bool = False):
    """Trả về (metrics, levels) nếu có tín hiệu (hoặc force), ngược lại None."""
    data_limiter.wait()
    df = get_stock_history(symbol, count=HISTORY_BARS)
    if len(df) < MIN_BARS:
        logger.warning("%s: chỉ có %d phiên, cần tối thiểu %d", symbol, len(df), MIN_BARS)
        return None

    # Nến cuối là phiên hôm nay và chưa đóng -> quy đổi khối lượng theo thời gian đã giao dịch
    fraction = 1.0
    if df["date"].iloc[-1] == now.date():
        fraction = max(session_progress(now), 0.05)  # tránh nhân quá lớn ở vài phút đầu phiên

    ind = compute_technical_indicators(df, session_fraction=fraction)
    metrics = check_breakout_trigger(ind)
    if metrics is None and force:
        metrics = latest_metrics(ind)
    if metrics is None:
        return None
    return metrics, price_levels(ind)


def load_fundamentals(symbol: str, close: float) -> dict | None:
    """Chỉ số cơ bản đã lưu (fundamentals_job.py) + P/E, P/B theo giá hiện tại. None nếu chưa có."""
    try:
        rec = store.load(symbol)
    except Exception:
        logger.exception("%s: lỗi khi đọc dữ liệu cơ bản", symbol)
        return None
    if not rec or not rec.get("ratios"):
        return None
    return {**rec["ratios"], **valuation(rec["ratios"], close),
            "period": rec.get("period"), "period_end": rec.get("period_end"),
            "rejected_period": rec.get("rejected_period")}


def save_signal(record: dict) -> None:
    with SIGNALS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_scan(symbols: list[str], analyzed_today: set, dry_run: bool, force: bool,
             failures: dict | None = None) -> None:
    failures = {} if failures is None else failures
    now = now_vn()
    logger.info("Quét %d mã lúc %s", len(symbols), now.strftime("%H:%M"))
    for symbol in symbols:
        key = (symbol, now.date())
        if key in analyzed_today and not force:
            continue  # mỗi mã chỉ phân tích 1 lần/ngày để tiết kiệm hạn ngạch
        if failures.get(key, 0) >= MAX_DAILY_FAILURES and not force:
            continue  # Gemini lỗi liên tục: ngừng thử mã này trong hôm nay để giữ hạn ngạch
        try:
            scanned = scan_symbol(symbol, now, force)
        except Exception:
            logger.exception("%s: lỗi khi tính chỉ báo", symbol)
            continue
        if scanned is None:
            logger.info("%s: không có tín hiệu", symbol)
            continue

        metrics, levels = scanned
        logger.info("%s: TÍN HIỆU %s | %s", symbol, metrics["trigger_reasons"],
                    json.dumps(metrics, ensure_ascii=False))
        if dry_run:
            continue

        fundamentals = load_fundamentals(symbol, metrics["close"])
        record = run_pipeline(symbol, metrics, levels, llm.generate, fundamentals=fundamentals)
        if record["status"] == "ANALYST_FAILED":
            failures[key] = failures.get(key, 0) + 1
            logger.error("%s: Analyst lỗi (%d/%d lần hôm nay)", symbol, failures[key], MAX_DAILY_FAILURES)
            continue

        analyzed_today.add(key)
        save_signal({"time": now.isoformat(), **record})
        print(json.dumps({"status": record["status"], **record["final"]}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Agent Stock Analysis - Vietnam Market")
    parser.add_argument("--once", action="store_true", help="Quét 1 lượt rồi thoát")
    parser.add_argument("--dry-run", action="store_true", help="Không gọi Gemini")
    parser.add_argument("--force", action="store_true", help="Bỏ qua bộ lọc Tầng 1 (để kiểm thử)")
    parser.add_argument("--symbols", nargs="+", help="Danh sách mã (mặc định: WATCHLIST trong .env)")
    args = parser.parse_args()

    # Console Windows mặc định cp1252 -> in tiếng Việt sẽ lỗi UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Ẩn log chi tiết từng HTTP request của SDK
    for noisy in ("httpx", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    symbols = [s.upper() for s in args.symbols] if args.symbols else WATCHLIST
    analyzed_today: set = set()
    failures: dict = {}

    if args.once:
        run_scan(symbols, analyzed_today, args.dry_run, args.force, failures)
        return

    logger.info("Bắt đầu quét liên tục: %s (mỗi %.0f phút, 9h00-14h45)", ", ".join(symbols), SCAN_INTERVAL_MIN)
    try:
        while True:
            if is_trading_time(now_vn()):
                run_scan(symbols, analyzed_today, args.dry_run, args.force, failures)
                time.sleep(SCAN_INTERVAL_MIN * 60)
            else:
                time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Đã dừng.")


if __name__ == "__main__":
    main()

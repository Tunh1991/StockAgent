"""
indicators.py - Module tính toán kỹ thuật thuần Pandas (Zero Dependency)
Không phụ thuộc vào thư viện ngoài, tương thích hoàn toàn Python 3.11+.
"""
import math
from dataclasses import dataclass
from datetime import datetime, time as dtime

import numpy as np
import pandas as pd

# Số phiên tối thiểu để mọi chỉ báo (MA50 lớn nhất) có giá trị
MIN_BARS = 51
VOLUME_SPIKE_THRESHOLD = 1.5
MAX_CHASE = 1.02  # vùng vào lệnh tối đa = giá hiện tại × 1.02 (chống mua đuổi)

# Khung giờ khớp lệnh HOSE/HNX (giờ Việt Nam): sáng 9h00-11h30, chiều 13h00-14h45
_SESSIONS = [(dtime(9, 0), dtime(11, 30)), (dtime(13, 0), dtime(14, 45))]


def _minutes(t: dtime) -> int:
    return t.hour * 60 + t.minute


_TOTAL_SESSION_MINUTES = sum(_minutes(e) - _minutes(s) for s, e in _SESSIONS)


def session_progress(now: datetime) -> float:
    """
    Tỷ lệ thời gian khớp lệnh đã trôi qua trong ngày (0.0 -> 1.0), theo giờ Việt Nam.
    Dùng để quy đổi khối lượng trong phiên về khối lượng ước tính cả ngày.
    """
    m = now.hour * 60 + now.minute
    elapsed = 0
    for start, end in _SESSIONS:
        s, e = _minutes(start), _minutes(end)
        elapsed += max(0, min(m, e) - s)
    return min(1.0, elapsed / _TOTAL_SESSION_MINUTES)


def compute_technical_indicators(df: pd.DataFrame, session_fraction: float = 1.0) -> pd.DataFrame:
    """
    Nhận DataFrame nến chuẩn (yêu cầu các cột: 'close', 'high', 'low', 'volume')
    và tính toán toàn bộ chỉ báo kỹ thuật phục vụ Rule Engine.

    - session_fraction: tỷ lệ phiên đã trôi qua của nến cuối cùng (1.0 = nến đã đóng).
      Khi quét trong phiên, khối lượng nến cuối được quy đổi ra cả ngày
      (VOL_PROJECTED) trước khi so với VOL_MA20.
    """
    df = df.copy()

    # 1. Đường xu hướng trung bình động (Trend Indicators)
    df["MA20"] = df["close"].rolling(window=20).mean()
    df["MA50"] = df["close"].rolling(window=50).mean()
    df["EMA20"] = df["close"].ewm(span=20, adjust=False).mean()

    # 2. Thanh khoản & Đột biến khối lượng (Volume Spike Trigger)
    # VOL_MA20 chỉ lấy 20 phiên TRƯỚC đó, để phiên đột biến không tự kéo trung bình lên.
    df["VOL_MA20"] = df["volume"].shift(1).rolling(window=20).mean()
    df["VOL_PROJECTED"] = df["volume"].astype(float)
    if 0 < session_fraction < 1.0:
        df.loc[df.index[-1], "VOL_PROJECTED"] = df["volume"].iloc[-1] / session_fraction
    df["VOL_SPIKE_RATIO"] = df["VOL_PROJECTED"] / df["VOL_MA20"].replace(0, np.nan)

    # 3. Chỉ báo xung lực RSI (14 chu kỳ - chuẩn Wilder)
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    # 4. Chỉ báo MACD (12, 26, 9)
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_HIST"] = df["MACD"] - df["MACD_SIGNAL"]

    # 5. Vùng hỗ trợ & Kháng cự ngắn hạn (Đáy/Đỉnh của 20 phiên TRƯỚC phiên hiện tại)
    # Phải shift(1): nếu tính cả phiên hiện tại thì close luôn <= RESISTANCE, không bao giờ breakout được.
    df["SUPPORT"] = df["low"].shift(1).rolling(window=20).min()
    df["RESISTANCE"] = df["high"].shift(1).rolling(window=20).max()
    df["HIGH_60"] = df["high"].shift(1).rolling(window=60).max()
    df["HIGH_120"] = df["high"].shift(1).rolling(window=120).max()

    # 6. ATR(14) chuẩn Wilder
    prev_close = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()

    return df


@dataclass(frozen=True)
class PriceLevel:
    """Mốc giá được phép dùng trong kế hoạch giao dịch (do Python tính, không do LLM)."""
    name: str
    price: float
    groups: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"name": self.name, "price": self.price, "groups": list(self.groups)}


_ENTRY_CANDIDATES = ("CLOSE", "MA20", "EMA20", "MA50", "SUPPORT_20", "RESISTANCE_20")
_STOP_CANDIDATES = ("SUPPORT_20", "MA20", "EMA20", "MA50", "ATR_STOP")
_TARGET_CANDIDATES = ("RESISTANCE_20", "HIGH_60", "HIGH_120", "ATR_T2", "ATR_T3", "MEASURED_MOVE")


def price_levels(df: pd.DataFrame) -> list[PriceLevel]:
    """Danh sách mốc giá (entry/stop/target) từ hàng cuối của DataFrame đã tính chỉ báo."""
    last = df.iloc[-1]
    c = float(last["close"])

    def val(col):
        v = last.get(col)
        return None if v is None or pd.isna(v) else float(v)

    atr, r, s = val("ATR"), val("RESISTANCE"), val("SUPPORT")
    raw = {
        "CLOSE": c, "MA20": val("MA20"), "EMA20": val("EMA20"), "MA50": val("MA50"),
        "SUPPORT_20": s, "RESISTANCE_20": r, "HIGH_60": val("HIGH_60"), "HIGH_120": val("HIGH_120"),
        "ATR_STOP": c - 1.5 * atr if atr is not None else None,
        "ATR_T2": c + 2 * atr if atr is not None else None,
        "ATR_T3": c + 3 * atr if atr is not None else None,
        "MEASURED_MOVE": r + (r - s) if r is not None and s is not None else None,
    }

    levels = []
    for name, price in raw.items():
        if price is None or math.isnan(price):
            continue
        price = round(price, 2)
        groups = []
        if name in _ENTRY_CANDIDATES and price <= c * MAX_CHASE:
            groups.append("entry")
        if name in _STOP_CANDIDATES and price < c:
            groups.append("stop")
        if name in _TARGET_CANDIDATES and price > c:
            groups.append("target")
        if groups:
            levels.append(PriceLevel(name, price, tuple(groups)))
    return levels


def rsi_state(rsi: float) -> str:
    if rsi > 70:
        return "QUA MUA"
    if rsi < 30:
        return "QUA BAN"
    return "TRUNG TINH"


def check_breakout_trigger(df: pd.DataFrame) -> dict | None:
    """
    Kiểm tra tiêu chí kích hoạt tầng Deep Analysis (FR-01):
    - Volume Spike: Khối lượng phiên hiện tại (đã quy đổi nếu đang trong phiên) >= 150% VOL_MA20
    - VÀ Price Action: Giá cắt lên MA20 HOẶC vượt đỉnh kháng cự 20 phiên
    Trả về dict số liệu đầy đủ (FR-02) hoặc None.
    """
    if len(df) < MIN_BARS:
        return None

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    required = ["close", "MA20", "MA50", "EMA20", "RSI", "VOL_SPIKE_RATIO",
                "MACD", "MACD_SIGNAL", "MACD_HIST", "SUPPORT", "RESISTANCE"]
    if latest[required].isna().any() or pd.isna(prev["MA20"]):
        return None

    is_volume_spike = latest["VOL_SPIKE_RATIO"] >= VOLUME_SPIKE_THRESHOLD
    is_ma20_cross = latest["close"] > latest["MA20"] and prev["close"] <= prev["MA20"]
    is_resistance_break = latest["close"] > latest["RESISTANCE"]

    if not (is_volume_spike and (is_ma20_cross or is_resistance_break)):
        return None

    reasons = []
    if is_ma20_cross:
        reasons.append("Giá cắt lên MA20")
    if is_resistance_break:
        reasons.append("Vượt đỉnh kháng cự 20 phiên")

    def r(x, n=2):
        v = float(x)
        return None if math.isnan(v) else round(v, n)

    return {
        "date": str(latest["date"]) if "date" in df.columns else None,
        "close": r(latest["close"]),
        "volume": int(latest["volume"]),
        "vol_projected": int(latest["VOL_PROJECTED"]),
        "vol_ma20": int(latest["VOL_MA20"]),
        "vol_spike_ratio": r(latest["VOL_SPIKE_RATIO"]),
        "ma20": r(latest["MA20"]),
        "ma50": r(latest["MA50"]),
        "ema20": r(latest["EMA20"]),
        "rsi": r(latest["RSI"]),
        "rsi_state": rsi_state(float(latest["RSI"])),
        "macd": r(latest["MACD"], 4),
        "macd_signal": r(latest["MACD_SIGNAL"], 4),
        "macd_hist": r(latest["MACD_HIST"], 4),
        "support": r(latest["SUPPORT"]),
        "resistance": r(latest["RESISTANCE"]),
        "trigger_reasons": reasons,
    }

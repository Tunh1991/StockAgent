"""
data_loader.py - Lấy dữ liệu nến (OHLCV) trực tiếp qua DNSE/Entrade API
Chuẩn TradingView, không cần token, hoàn toàn miễn phí.
Lưu ý: giá cổ phiếu trả về theo đơn vị NGHÌN ĐỒNG (VD: 21.2 = 21.200 VNĐ); chỉ số tính theo điểm.
"""
import logging
import time

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://services.entrade.com.vn/chart-api/v2/ohlcs"
API_URL = f"{BASE_URL}/stock"
INDEX_URL = f"{BASE_URL}/index"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _fetch(url: str, symbol: str, count: int) -> pd.DataFrame:
    to_time = int(time.time())
    # Lùi thời gian gấp đôi số phiên (tối thiểu thêm 30 ngày) để bù cuối tuần và kỳ nghỉ Tết dài
    days_back = max(count * 2, count + 30)
    params = {"symbol": symbol, "from": to_time - days_back * 86400, "to": to_time, "resolution": "1D"}
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as e:
        logger.error("Lỗi khi tải dữ liệu mã %s: %s", symbol, e)
        return pd.DataFrame()
    return _to_frame(data, count, symbol)


def _to_frame(data: dict, count: int, symbol: str = "") -> pd.DataFrame:
    """Chuẩn hóa JSON TradingView (t, o, h, l, c, v) sang DataFrame theo ngày giờ Việt Nam."""
    keys = ("t", "o", "h", "l", "c", "v")
    if not isinstance(data, dict) or not all(data.get(k) for k in keys):
        logger.warning("Không có dữ liệu cho mã %s", symbol)
        return pd.DataFrame()

    df = pd.DataFrame({
        "date": pd.to_datetime(data["t"], unit="s"),
        "open": data["o"],
        "high": data["h"],
        "low": data["l"],
        "close": data["c"],
        "volume": data["v"],
    })
    df["date"] = df["date"].dt.tz_localize("UTC").dt.tz_convert("Asia/Ho_Chi_Minh").dt.date
    df = df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    return df.tail(count).reset_index(drop=True)


def get_stock_history(symbol: str, count: int = 100) -> pd.DataFrame:
    """
    Lấy dữ liệu nến ngày (OHLCV) của một mã cổ phiếu.
    - symbol: Mã cổ phiếu (VD: 'HPG', 'SSI', 'FPT')
    - count: Số phiên cần lấy
    """
    return _fetch(API_URL, symbol.strip().upper(), count)


def get_index_history(symbol: str = "VNINDEX", count: int = 300) -> pd.DataFrame:
    """Lấy dữ liệu nến ngày của chỉ số (mặc định VN-Index). Lỗi thì trả DataFrame rỗng."""
    return _fetch(INDEX_URL, symbol.strip().upper(), count)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df_hpg = get_stock_history("HPG", count=10)
    print("Dữ liệu 10 phiên gần nhất của HPG:")
    print(df_hpg)

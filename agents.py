"""
agents.py - Schema đầu ra và prompt cho các agent LLM.
  Analyst: lập kế hoạch giao dịch, chỉ được chọn mốc giá trong bảng do Python tính.
  Critic:  phản biện tín hiệu MUA GOM, chỉ được giảm độ tin cậy hoặc hạ cấp.
"""
import json
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field

NO_FUNDAMENTALS = "Chưa có dữ liệu cơ bản - cần kiểm tra BCTC"


class Signal(str, Enum):
    MUA_GOM = "MUA GOM"
    QUAN_SAT = "QUAN SAT"
    BO_QUA = "BO QUA"


class Verdict(str, Enum):
    GIU_NGUYEN = "GIU_NGUYEN"
    GIAM_TIN_CAY = "GIAM_TIN_CAY"
    HA_CAP = "HA_CAP"


class PriceRef(BaseModel):
    level: str = Field(description="Tên mốc giá lấy đúng từ bảng mốc giá")
    price: float = Field(description="Giá của mốc, đúng như trong bảng (nghìn đồng)")


class TradePlan(BaseModel):
    entry_low: PriceRef
    entry_high: PriceRef
    stop_loss: PriceRef
    target_1: PriceRef
    target_2: PriceRef | None = None
    t_plus_risk: str = Field(description="Rủi ro khi hàng về tài khoản (chiều T+2) sau phiên nổ thanh khoản")


class AnalystResult(BaseModel):
    symbol: str
    signal: Signal
    confidence_score: float = Field(ge=1.0, le=10.0, description="Điểm tin cậy từ 1.0 đến 10.0")
    orderflow_analysis: str
    fundamental_analysis: str
    red_flags: list[str]
    plan: TradePlan


class CriticResult(BaseModel):
    verdict: Verdict
    confidence_adjustment: float = Field(ge=-5.0, le=0.0, description="Điều chỉnh độ tin cậy, từ -5.0 đến 0")
    counter_arguments: list[str]
    reason: str


def _metrics_block(symbol: str, m: dict) -> str:
    return f"""DỮ LIỆU KỸ THUẬT (phiên {m.get('date')}):
- Mã cổ phiếu: {symbol}
- Lý do kích hoạt: {', '.join(m.get('trigger_reasons') or []) or 'Kiểm thử thủ công'}
- Giá hiện tại: {m['close']}
- MA20: {m['ma20']} | MA50: {m['ma50']} | EMA20: {m['ema20']}
- RSI(14): {m['rsi']} ({m.get('rsi_state', '')})
- MACD: {m['macd']} | Signal: {m['macd_signal']} | Histogram: {m['macd_hist']}
- Khối lượng: {m['volume']} (ước tính cả phiên: {m['vol_projected']}), VOL_MA20: {m['vol_ma20']}
- Tỷ lệ khối lượng so với MA20: {m['vol_spike_ratio']}x
- Hỗ trợ (đáy 20 phiên trước): {m['support']} | Kháng cự (đỉnh 20 phiên trước): {m['resistance']}"""


def _levels_block(levels) -> str:
    lines = ["BẢNG MỐC GIÁ ĐƯỢC PHÉP (nghìn đồng):"]
    for group, label in (("entry", "Vùng vào lệnh (entry_low, entry_high)"),
                         ("stop", "Cắt lỗ (stop_loss)"),
                         ("target", "Mục tiêu (target_1, target_2)")):
        items = ", ".join(f"{lv.name}={lv.price}" for lv in levels if group in lv.groups) or "(không có)"
        lines.append(f"- Nhóm {group} - {label}: {items}")
    return "\n".join(lines)


STALE_DAYS = 200

# Nhãn và cách hiển thị chỉ số cơ bản: "pct" = %, "x" = lần, "bn" = tỷ đồng, "vnd" = đồng, "days" = ngày
_FUND_FIELDS = [
    ("pe", "P/E", "x"), ("pb", "P/B", "x"), ("eps_ttm", "EPS 4 quý", "vnd"), ("bvps", "Giá trị sổ sách/cp", "vnd"),
    ("roe_ttm", "ROE 4 quý", "pct"), ("roa_ttm", "ROA 4 quý", "pct"),
    ("revenue_ttm", "Doanh thu thuần 4 quý", "bn"), ("npat_parent_ttm", "LNST cổ đông mẹ 4 quý", "bn"),
    ("gross_margin_q", "Biên LN gộp quý", "pct"), ("gross_margin_q_prior", "Biên LN gộp cùng quý năm trước", "pct"),
    ("net_margin_q", "Biên LN ròng quý", "pct"), ("revenue_yoy_q", "Tăng trưởng doanh thu quý YoY", "pct"),
    ("npat_parent_yoy_q", "Tăng trưởng LNST cổ đông mẹ quý YoY", "pct"),
    ("debt_to_equity", "Nợ vay/VCSH", "x"), ("current_ratio", "Thanh toán hiện hành", "x"),
    ("interest_coverage", "Khả năng trả lãi", "x"), ("ocf_to_npat_ytd", "Dòng tiền KD/LNST lũy kế", "x"),
    ("customer_advances_to_equity", "Người mua trả trước/VCSH", "x"),
    ("customer_advances_change", "Biến động người mua trả trước so với đầu năm", "pct"),
    ("inventory_to_assets", "Tồn kho/Tổng tài sản", "pct"), ("inventory_days", "Số ngày tồn kho", "days"),
    ("gross_margin_change_yoy", "Thay đổi biên LN gộp so với cùng kỳ (điểm %)", "pct"),
]


def _fmt(value: float, kind: str) -> str:
    if kind == "pct":
        return f"{value * 100:.2f}%"
    if kind == "bn":
        return f"{value / 1e9:.1f} tỷ đồng"
    if kind == "vnd":
        return f"{value:.0f} đồng"
    if kind == "days":
        return f"{value:.1f} ngày"
    return f"{value} lần"


def format_fundamentals_block(f: dict | None, today: date) -> str:
    if not f:
        return f"DỮ LIỆU CƠ BẢN: {NO_FUNDAMENTALS}"
    lines = [f"DỮ LIỆU CƠ BẢN (kỳ {f.get('period')}, kết thúc {f.get('period_end')}, BCTC hợp nhất):"]
    try:
        age = (today - date.fromisoformat(f.get("period_end", ""))).days
        if age > STALE_DAYS:
            lines.append(f"⚠ Dữ liệu cơ bản đã cũ (kỳ {f.get('period')}, {age} ngày trước)")
    except ValueError:
        pass
    if f.get("rejected_period"):
        lines.append(f"⚠ BCTC kỳ {f['rejected_period']} bị loại khi kiểm tra tự động; "
                     f"đang dùng số liệu kỳ {f.get('period')}")
    for key, label, kind in _FUND_FIELDS:
        value = f.get(key)
        if isinstance(value, (int, float)):
            lines.append(f"- {label}: {_fmt(value, kind)}")
    if f.get("pe_note"):
        lines.append(f"- P/E: {f['pe_note']}")
    return "\n".join(lines)


def _fundamental_rule(fundamentals: dict | None) -> str:
    if not fundamentals:
        return (f'- Không có dữ liệu cơ bản (BCTC). Trường fundamental_analysis phải ghi "{NO_FUNDAMENTALS}"\n'
                "  và chỉ nêu các chỉ số ngành cần kiểm tra, không đưa ra con số.")
    return ("- fundamental_analysis chỉ được dùng các con số trong khối DỮ LIỆU CƠ BẢN, viết đúng như trong khối\n"
            "  (cùng đơn vị %, lần, tỷ đồng), không tự tính chỉ số mới. Nếu dữ liệu đã cũ, phải nói rõ.")


def _skills_section(blocks: list[str] | None) -> str:
    return "\n\n".join(blocks) + "\n" if blocks else ""


def build_analyst_prompt(symbol: str, metrics: dict, levels, fundamentals: dict | None = None,
                         today: date | None = None, skill_blocks: list[str] | None = None) -> str:
    today = today or date.today()
    return f"""Bạn là chuyên gia phân tích kỹ thuật và dòng tiền thị trường chứng khoán Việt Nam (HOSE/HNX/UPCOM).
Đánh giá tín hiệu kỹ thuật sau và lập kế hoạch giao dịch T+.

QUY TẮC BẮT BUỘC:
- Chỉ sử dụng các số liệu được cung cấp bên dưới. KHÔNG tự tính lại, KHÔNG bịa mốc giá hay số liệu tài chính.
- Đơn vị giá: nghìn đồng (VD: 21.2 = 21.200 VNĐ).
- Khi trích số liệu vào phần chữ, viết đúng như dữ liệu đầu vào, không dùng dấu phân cách nghìn
  (viết 31627400 hoặc 31.63 triệu, không viết 31.627.400). Không tự tính số mới (%, chênh lệch).
- Mỗi mốc trong plan (entry_low, entry_high, stop_loss, target_1, target_2) chỉ được chọn mốc trong bảng:
  ghi đúng tên mốc vào "level" và đúng giá vào "price". Mốc phải thuộc đúng nhóm.
- Thứ tự bắt buộc: stop_loss < entry_low <= entry_high < target_1 < target_2. target_2 có thể để null.
- Với MUA GOM: tỷ lệ (target_1 - entry_high) / (entry_high - stop_loss) phải >= 1.5.
{_fundamental_rule(fundamentals)}
- signal chỉ được là: MUA GOM, QUAN SAT, BO QUA. confidence_score từ 1.0 đến 10.0.
- t_plus_risk: đánh giá rủi ro hàng về tài khoản chiều T+2 sau phiên nổ thanh khoản, cảnh báo mua đuổi đầu phiên.

{_metrics_block(symbol, metrics)}

{_levels_block(levels)}

{format_fundamentals_block(fundamentals, today)}
{_skills_section(skill_blocks)}
"""


def build_fix_prompt(base_prompt: str, previous: dict | None, errors: list[str]) -> str:
    prev = json.dumps(previous, ensure_ascii=False) if previous is not None else "(JSON không hợp lệ)"
    err_lines = "\n".join(f"- {e}" for e in errors)
    return f"""{base_prompt}

KẾT QUẢ LẦN TRƯỚC CỦA BẠN:
{prev}

KẾT QUẢ TRÊN VI PHẠM CÁC LỖI SAU, HÃY SỬA VÀ TRẢ LẠI TOÀN BỘ JSON:
{err_lines}
"""


def build_critic_prompt(symbol: str, metrics: dict, levels, analyst: dict, warnings: list[str],
                        fundamentals: dict | None = None, today: date | None = None,
                        skill_blocks: list[str] | None = None) -> str:
    today = today or date.today()
    warn_lines = "\n".join(f"- {w}" for w in warnings) or "- (không có)"
    return f"""Bạn là chuyên gia quản trị rủi ro, đóng vai người phản biện một khuyến nghị MUA GOM
trên thị trường chứng khoán Việt Nam. Nhiệm vụ: tìm các lý do KHÔNG nên mua.

QUY TẮC:
- Chỉ sử dụng số liệu được cung cấp bên dưới, không bịa số liệu, không tự tính số mới (%, chênh lệch),
  không dùng dấu phân cách nghìn.
- Bạn chỉ được GIỮ NGUYÊN, GIẢM độ tin cậy hoặc HẠ CẤP; không được tăng.
  confidence_adjustment từ -5.0 đến 0. verdict: GIU_NGUYEN, GIAM_TIN_CAY hoặc HA_CAP
  (HA_CAP = chuyển khuyến nghị xuống QUAN SAT).
- Chú ý: mua đuổi sau phiên nổ khối lượng, rủi ro hàng về T+2, RSI cao, giá sát kháng cự, tín hiệu chỉ dựa trên 1 phiên.

{_metrics_block(symbol, metrics)}

{_levels_block(levels)}

{format_fundamentals_block(fundamentals, today)}
{_skills_section(skill_blocks)}

CẢNH BÁO TỪ BỘ KIỂM TRA TỰ ĐỘNG:
{warn_lines}

KHUYẾN NGHỊ CỦA ANALYST:
{json.dumps(analyst, ensure_ascii=False)}
"""

"""
validator.py - Kiểm tra kế hoạch giao dịch của Analyst bằng code thuần (không gọi LLM).

Luật CHẶN (errors, cần Analyst sửa):
  H1 mốc giá tồn tại và giá khớp (±0.5%)    H2 thứ tự stop < entry_low <= entry_high < target_1 < target_2
  H3 mốc đúng nhóm entry/stop/target          H4 R:R >= 1.5 (MUA GOM)      H5 chống mua đuổi (MUA GOM)
Luật CẢNH BÁO (warnings, ghi vào red_flags):
  S1 RSI quá mua mà MUA GOM    S2 cắt lỗ quá xa    S3 số liệu trong phần chữ không có trong dữ liệu đầu vào
"""
import re
from dataclasses import dataclass, field

PRICE_TOLERANCE = 0.005
MIN_RR = 1.5
MAX_CHASE = 1.02
MAX_STOP_PCT = 0.07
RSI_OVERBOUGHT = 75

BUY = "MUA GOM"
_PLAN_FIELDS = {"entry_low": "entry", "entry_high": "entry", "stop_loss": "stop",
                "target_1": "target", "target_2": "target"}
_NUMBER_RE = re.compile(r"[-−]?\d+[.,]\d+")


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors


def _close_enough(a: float, b: float) -> bool:
    return b != 0 and abs(a - b) <= PRICE_TOLERANCE * abs(b)


def _fmt_group(levels, group: str) -> str:
    return ", ".join(f"{lv.name}={lv.price}" for lv in levels if group in lv.groups) or "(không có)"


def _reference_values(metrics: dict, levels, extra: dict | None = None) -> list[float]:
    values = []
    for source in (metrics, extra or {}):
        for v in source.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                values.append(float(v))
    # Số liệu cơ bản có thể được viết dạng % (×100) hoặc tỷ đồng (÷1e9)
    for v in (extra or {}).values():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            values += [v * 100, v / 1e9]
    values += [lv.price for lv in levels]
    for key in ("volume", "vol_projected", "vol_ma20"):
        v = metrics.get(key)
        if isinstance(v, (int, float)):
            values += [v / 1e6, v / 1e3]
    return [v for v in values if v != 0]


def _check_text_numbers(texts: list[str], refs: list[float]) -> list[str]:
    warnings, seen = [], set()
    for text in texts:
        for raw in _NUMBER_RE.findall(text or ""):
            num = float(raw.replace(",", ".").replace("−", "-"))
            if raw in seen or any(_close_enough(num, r) for r in refs):
                continue
            seen.add(raw)
            warnings.append(f"S3: Số liệu không có trong dữ liệu đầu vào: {raw}")
    return warnings


def validate(analysis: dict, levels, metrics: dict, fundamentals: dict | None = None) -> ValidationResult:
    result = ValidationResult()
    errors, warnings = result.errors, result.warnings
    by_name = {lv.name: lv for lv in levels}
    plan = analysis.get("plan") or {}
    is_buy = analysis.get("signal") == BUY
    close = float(metrics["close"])

    # H1 + H3: từng mốc trong kế hoạch
    prices: dict[str, float] = {}
    for key, group in _PLAN_FIELDS.items():
        ref = plan.get(key)
        if ref is None:
            if key != "target_2":
                errors.append(f"H1: {key}: thiếu mốc giá. Các mốc {group} hợp lệ: {_fmt_group(levels, group)}")
            continue
        name = str(ref.get("level", "")).strip().upper()
        price = float(ref.get("price"))
        prices[key] = price
        lv = by_name.get(name)
        if lv is None:
            errors.append(f"H1: {key}: mốc '{name}' không tồn tại. "
                          f"Các mốc {group} hợp lệ: {_fmt_group(levels, group)}")
            continue
        if not _close_enough(price, lv.price):
            errors.append(f"H1: {key}: giá {price} lệch quá 0.5% so với mốc {lv.name}={lv.price}")
        if group not in lv.groups:
            errors.append(f"H3: {key}: mốc {lv.name} không thuộc nhóm {group}. "
                          f"Các mốc {group} hợp lệ: {_fmt_group(levels, group)}")

    # H2: thứ tự giá
    order_ok = False
    sl, el, eh, t1 = (prices.get(k) for k in ("stop_loss", "entry_low", "entry_high", "target_1"))
    if None not in (sl, el, eh, t1):
        t2 = prices.get("target_2")
        order_ok = sl < el <= eh < t1 and (t2 is None or t1 < t2)
        if not order_ok:
            errors.append(f"H2: thứ tự giá sai, cần stop_loss < entry_low <= entry_high < target_1 < target_2 "
                          f"(hiện tại: {sl}, {el}, {eh}, {t1}, {t2})")

    if is_buy:
        # H4: chỉ tính R:R khi thứ tự giá hợp lệ (tránh chia cho 0)
        if order_ok:
            rr = (t1 - eh) / (eh - sl)
            if rr < MIN_RR:
                errors.append(f"H4: tỷ lệ lời/lỗ R:R = {rr:.2f} < {MIN_RR}. Chọn mục tiêu xa hơn hoặc cắt lỗ gần hơn")
        # H5: chống mua đuổi
        if eh is not None and eh > close * MAX_CHASE:
            errors.append(f"H5: mua đuổi: entry_high {eh} > giá hiện tại × {MAX_CHASE} ({close * MAX_CHASE:.2f})")
        # S1
        rsi = metrics.get("rsi")
        if isinstance(rsi, (int, float)) and rsi > RSI_OVERBOUGHT:
            warnings.append(f"S1: RSI quá mua ({rsi}) nhưng khuyến nghị MUA GOM")

    # S2: khoảng cắt lỗ
    if eh and sl is not None and sl < eh:
        stop_pct = (eh - sl) / eh
        if stop_pct > MAX_STOP_PCT:
            warnings.append(f"S2: Khoảng cắt lỗ {stop_pct:.1%} lớn hơn một phiên giảm sàn HOSE (7%)")

    # S3: số liệu trong phần chữ
    texts = ([analysis.get("orderflow_analysis", ""), analysis.get("fundamental_analysis", "")]
             + list(analysis.get("red_flags") or []))
    warnings.extend(check_text_numbers(texts, metrics, levels, fundamentals))
    return result


def check_text_numbers(texts: list[str], metrics: dict, levels, fundamentals: dict | None = None) -> list[str]:
    """S3 cho một danh sách đoạn văn bất kỳ (dùng cả cho counter_arguments của Critic)."""
    return _check_text_numbers(texts, _reference_values(metrics, levels, fundamentals))

"""
checks.py - Kiểm tra bản trích xuất BCTC bằng code thuần.
  F1 so sánh 2 lần trích    F3 mã bắt buộc    F4 đẳng thức kế toán
  F5 số cổ phiếu hợp lý     F6 kỳ báo cáo khớp tên file
"""
from fundamentals.schema import (ABS_CODES, COLUMNS, IDENTITIES, PERIOD_END, REQUIRED, UNIT_SCALE, CODES,
                                 Extraction, LineItem, Unit)

TOL = 0.001
PAR_VALUE = 10_000
SHARES_MIN, SHARES_MAX = 1e6, 2e10


def values_match(a: float, b: float) -> bool:
    return abs(a - b) <= max(TOL * max(abs(a), abs(b)), 1)


def compare_runs(a: Extraction, b: Extraction) -> list[str]:
    errors = []
    if a.unit != b.unit:
        errors.append(f"F1: đơn vị khác nhau giữa 2 lần trích: {a.unit.value} ≠ {b.unit.value}")
    if a.period_end != b.period_end:
        errors.append(f"F1: kỳ báo cáo khác nhau giữa 2 lần trích: {a.period_end} ≠ {b.period_end}")
    codes_a, codes_b = {i.code for i in a.items}, {i.code for i in b.items}
    for code in sorted(codes_a ^ codes_b):
        errors.append(f"F1: {code} chỉ có ở một trong 2 lần trích")
    for code in sorted(codes_a & codes_b):
        ia, ib = a.get(code), b.get(code)
        for col in COLUMNS:
            va, vb = getattr(ia, col), getattr(ib, col)
            if (va is None) != (vb is None) or (va is not None and not values_match(va, vb)):
                errors.append(f"F1: {code} cột {col} lệch giữa 2 lần trích: {va} ≠ {vb}")
    return errors


def normalize_units(ex: Extraction) -> Extraction:
    scale = UNIT_SCALE[ex.unit]
    items = []
    for item in ex.items:
        cols = {}
        for col in COLUMNS:
            v = getattr(item, col)
            if v is not None:
                v = v * scale
                if item.code in ABS_CODES:
                    v = abs(v)
            cols[col] = v
        items.append(LineItem(code=item.code, page=item.page, **cols))
    return Extraction(unit=Unit.DONG, period_end=ex.period_end, consolidated=ex.consolidated, items=items)


def check_required(ex: Extraction) -> tuple[Extraction, list[str]]:
    present = {i.code for i in ex.items}
    errors = [f"F3: thiếu mã bắt buộc {c} ({CODES[c]})" for c in sorted(REQUIRED - present)]
    filled = list(ex.items) + [LineItem(code=c, page=0, **{col: 0.0 for col in COLUMNS})
                               for c in sorted(set(CODES) - REQUIRED - present)]
    return ex.model_copy(update={"items": filled}), errors


def check_identities(ex: Extraction) -> list[str]:
    errors = []
    for lhs, rhs in IDENTITIES:
        codes = [lhs] + [c for _, c in rhs]
        items = [ex.get(c) for c in codes]
        if any(i is None for i in items):
            continue
        formula = f"{lhs} ≠ " + " ".join(f"{'+' if s > 0 else '−'} {c}" for s, c in rhs).lstrip("+ ")
        for col in COLUMNS:
            vals = [getattr(i, col) for i in items]
            if any(v is None for v in vals):
                continue
            left, right = vals[0], sum(s * v for (s, _), v in zip(rhs, vals[1:]))
            if not values_match(left, right):
                errors.append(f"F4: {formula} (cột {col}): {left:,.0f} ≠ {right:,.0f}")
    return errors


def check_shares(ex: Extraction) -> list[str]:
    item = ex.get("BS411")
    if item is None or item.current is None:
        return []
    shares = item.current / PAR_VALUE
    if not SHARES_MIN <= shares <= SHARES_MAX:
        return [f"F5: số cổ phiếu {shares:,.0f} ngoài khoảng hợp lý, nghi đọc sai đơn vị"]
    return []


def check_period(ex: Extraction, period: str) -> list[str]:
    expected = f"{period[:4]}-{PERIOD_END[period[4:].upper()]}"
    if ex.period_end != expected:
        return [f"F6: kỳ báo cáo {ex.period_end} không khớp tên file {period} (cần {expected})"]
    return []


def run_checks(a: Extraction, b: Extraction, period: str) -> tuple[Extraction | None, list[str]]:
    errors = compare_runs(a, b)
    if errors:
        return None, errors
    ex = normalize_units(a)
    ex, errors = check_required(ex)
    errors += check_identities(ex) + check_shares(ex) + check_period(ex, period)
    return (None, errors) if errors else (ex, [])

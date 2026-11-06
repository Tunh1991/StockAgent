"""
ratios.py - Tính chỉ số cơ bản từ BCTC đã kiểm tra (đơn vị: đồng). Chỉ số không tính được = None.
"""
from fundamentals.checks import PAR_VALUE
from fundamentals.schema import Extraction


def _v(ex: Extraction | None, code: str, col: str) -> float | None:
    if ex is None:
        return None
    item = ex.get(code)
    return None if item is None else getattr(item, col)


def _add(*vals):
    return None if any(v is None for v in vals) else sum(vals)


def _div(a, b, digits: int | None = 4):
    """a / b; None khi thiếu số hoặc mẫu số <= 0."""
    if a is None or b is None or b <= 0:
        return None
    r = a / b
    return round(r, digits) if digits is not None else r


def _avg(a, b):
    return None if a is None or b is None else (a + b) / 2


def _yoy(cur, prior):
    if cur is None or prior is None or prior <= 0:
        return None
    return round(cur / prior - 1, 4)


def compute_ratios(quarter: Extraction, annual: Extraction | None, sector: str, period: str) -> dict:
    is_q4 = period.upper().endswith("Q4")

    def ttm(code):
        if is_q4:
            return _v(quarter, code, "ytd_current")
        return _add(_v(annual, code, "current"), _v(quarter, code, "ytd_current"),
                    None if _v(quarter, code, "ytd_prior") is None else -_v(quarter, code, "ytd_prior"))

    cur = lambda code: _v(quarter, code, "current")  # noqa: E731
    pri = lambda code: _v(quarter, code, "prior")  # noqa: E731

    shares = _div(cur("BS411"), PAR_VALUE, None)
    eq_cur = _add(cur("BS400"), None if cur("BS429") is None else -cur("BS429"))
    eq_pri = _add(pri("BS400"), None if pri("BS429") is None else -pri("BS429"))
    npat_ttm, rev_ttm = ttm("IS61"), ttm("IS10")
    gm, gm_prior = _div(cur("IS20"), cur("IS10")), _div(pri("IS20"), pri("IS10"))
    equity_ok = eq_cur is not None and eq_cur > 0

    r = {
        "shares": shares,
        "revenue_ttm": rev_ttm,
        "npat_parent_ttm": npat_ttm,
        "eps_ttm": _div(npat_ttm, shares),
        "bvps": _div(eq_cur, shares) if equity_ok else None,
        "roe_ttm": _div(npat_ttm, _avg(eq_cur, eq_pri)) if equity_ok else None,
        "roa_ttm": _div(npat_ttm, _avg(cur("BS270"), pri("BS270"))),
        "gross_margin_q": gm,
        "gross_margin_q_prior": gm_prior,
        "net_margin_q": _div(cur("IS60"), cur("IS10")),
        "revenue_yoy_q": _yoy(cur("IS10"), pri("IS10")),
        "npat_parent_yoy_q": _yoy(cur("IS61"), pri("IS61")),
        "debt_to_equity": _div(_add(cur("BS320"), cur("BS338")), cur("BS400")),
        "current_ratio": _div(cur("BS100"), cur("BS310")),
        "interest_coverage": _div(_add(cur("IS50"), cur("IS23")), cur("IS23")),
        "ocf_to_npat_ytd": _div(_v(quarter, "CF20", "ytd_current"), _v(quarter, "IS60", "ytd_current")),
    }

    if sector == "BDS":
        adv_cur, adv_pri = _add(cur("BS312"), cur("BS332")), _add(pri("BS312"), pri("BS332"))
        r["customer_advances_to_equity"] = _div(adv_cur, cur("BS400"))
        r["customer_advances_change"] = _yoy(adv_cur, adv_pri)
        r["inventory_to_assets"] = _div(cur("BS140"), cur("BS270"))
    elif sector == "THEP":
        turnover = _div(ttm("IS11"), _avg(cur("BS140"), pri("BS140")), None)
        r["inventory_days"] = _div(365, turnover)
        r["gross_margin_change_yoy"] = None if gm is None or gm_prior is None else round(gm - gm_prior, 4)
    return r


def valuation(ratios: dict, price: float) -> dict:
    """P/E, P/B theo giá hiện tại (giá tính bằng nghìn đồng)."""
    price_vnd = price * 1000
    eps, bvps = ratios.get("eps_ttm"), ratios.get("bvps")
    out = {"pe": _div(price_vnd, eps, 2) if eps and eps > 0 else None,
           "pb": _div(price_vnd, bvps, 2) if bvps and bvps > 0 else None}
    if out["pe"] is None:
        out["pe_note"] = "EPS ≤ 0, P/E không có ý nghĩa"
    return out
